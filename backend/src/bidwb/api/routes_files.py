"""资料上传（预签名分片直传）、文件版本与原件读取。"""

from __future__ import annotations

from email.utils import formatdate
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Header, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import Connection

from bidwb import db
from bidwb.api.deps import Body, Ctr, CurrentSession, IdemKey, Session, mutate
from bidwb.errors import Unprocessable
from bidwb.logs import get_logger
from bidwb.runtime import Container
from bidwb.schemas import FileVersion, UploadComplete, UploadRequest, UploadResult, UploadSession
from bidwb.services import files, pipeline

router = APIRouter(tags=["files"])
log = get_logger(__name__)
_INLINE_TYPES = frozenset({"application/pdf", "image/png", "image/jpeg", "text/plain"})


@router.post("/projects/{project_id}/uploads", response_model=UploadSession, operation_id="initUpload")
def init_upload(project_id: str, body: UploadRequest, session: CurrentSession, key: IdemKey, ctr: Ctr) -> UploadSession:
    # 上传会话自带（项目, 成员, 幂等键）唯一约束与请求哈希，不经过通用幂等表。
    with db.transaction(ctr.engine) as conn:
        return files.init_upload(conn, ctr.store, ctr.settings, session.actor, project_id, body, key, session.request_id)


@router.post("/uploads/{upload_id}/urls", response_model=UploadSession, operation_id="refreshUploadUrls")
def refresh_urls(upload_id: str, session: CurrentSession, _key: IdemKey, ctr: Ctr) -> UploadSession:
    with db.transaction(ctr.engine) as conn:
        return files.refresh_urls(conn, ctr.store, ctr.settings, session.actor, upload_id)


@router.post("/uploads/{upload_id}/complete", response_model=UploadResult, operation_id="completeUpload")
def complete_upload(upload_id: str, body: UploadComplete, session: CurrentSession, key: IdemKey, ctr: Ctr) -> Body:
    return mutate(
        ctr,
        session,
        key,
        f"POST /uploads/{upload_id}/complete",
        body,
        lambda c: _complete_and_advance(c, ctr, session, upload_id, body),
    )


def _complete_and_advance(conn: Connection, ctr: Container, session: Session, upload_id: str, body: UploadComplete) -> UploadResult:
    """资料入库即开始自动评审：在资料齐全之前只更新项目状态，齐全后依次入队解析、规则提取与核对。"""
    result = files.complete_upload(conn, ctr.store, session.actor, upload_id, body, session.request_id)
    if not result.duplicate and ctr.settings.auto_analysis:
        try:
            with conn.begin_nested():  # 推进失败不能让上传本身回滚；回收器会再推进
                pipeline.advance(conn, ctr.store, result.project_id)
        except Exception:
            log.warning("pipeline_advance_failed", project_id=result.project_id, exc_info=True)
    return result


@router.get("/projects/{project_id}/files", response_model=list[FileVersion], operation_id="listFiles")
def list_files(project_id: str, session: CurrentSession, ctr: Ctr) -> list[FileVersion]:
    with ctr.engine.connect() as conn:
        return files.list_versions(conn, session.actor, project_id)


@router.get(
    "/files/{version_id}/content",
    operation_id="getFileContent",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}, 206: {"description": "部分内容"}, 304: {"description": "未修改"}},
)
def get_file_content(
    version_id: str,
    session: CurrentSession,
    ctr: Ctr,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
) -> Response:
    """原件内容，支持单段 HTTP Range（PDF.js 按需取页）。原件按内容寻址、不可变，因此可以带 ETag 缓存。"""
    with ctr.engine.connect() as conn:
        content = files.locate_content(conn, session.actor, version_id)
    etag = f'"{content.sha256}"'
    base_headers = {
        "ETag": etag,
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
        "Last-Modified": formatdate(usegmt=True),
    }
    if if_none_match and etag in {t.strip() for t in if_none_match.split(",")}:
        return Response(status_code=304, headers={k: v for k, v in base_headers.items() if k != "Last-Modified"})
    try:
        start, end, partial = files.parse_range(range_header, content.byte_size)
    except Unprocessable:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{content.byte_size}"})
    disposition = "inline" if content.media_type in _INLINE_TYPES else "attachment"
    headers = {
        **base_headers,
        "Content-Length": str(end - start + 1),
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(content.original_name)}",
    }
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{content.byte_size}"
    return StreamingResponse(
        files.stream(ctr.store, content.object_key, start, end),
        status_code=206 if partial else 200,
        media_type=content.media_type,
        headers=headers,
    )
