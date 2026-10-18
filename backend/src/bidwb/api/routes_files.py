"""资料上传（同源分片转传）、文件版本与原件读取。"""

from __future__ import annotations

from email.utils import formatdate
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import Connection
from starlette.concurrency import run_in_threadpool

from bidwb import db
from bidwb.api.deps import Body, Ctr, CurrentSession, IdemKey, Session, mutate
from bidwb.errors import Conflict, Unavailable, Unprocessable
from bidwb.logs import get_logger
from bidwb.runtime import Container
from bidwb.schemas import (
    FileVersion,
    UploadComplete,
    UploadRequest,
    UploadResult,
    UploadSession,
    WordAdoptRequest,
    WordRetryRequest,
    WordStatus,
)
from bidwb.services import files, pipeline, word_materials

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


@router.put(
    "/uploads/{upload_id}/parts/{part_number}",
    operation_id="uploadPart",
    response_class=Response,
    openapi_extra={
        "requestBody": {"required": True, "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}
    },
    responses={200: {"description": "分片已保存", "headers": {"ETag": {"schema": {"type": "string"}}}}},
)
async def put_upload_part(upload_id: str, part_number: int, request: Request, session: CurrentSession, ctr: Ctr) -> Response:
    def expected_size() -> int:
        with ctr.engine.connect() as conn:
            return files.upload_part_size(conn, session.actor, upload_id, part_number)

    expected = await run_in_threadpool(expected_size)
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > expected:
            raise Unprocessable("part_size_mismatch", "分片大小超出声明范围", expected=expected)
        data.extend(chunk)

    def persist() -> str:
        with db.transaction(ctr.engine) as conn:
            return files.upload_part(conn, ctr.store, session.actor, upload_id, part_number, bytes(data))

    etag = await run_in_threadpool(persist)
    return Response(headers={"ETag": etag, "Cache-Control": "private, no-store"})


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


@router.post("/files/{version_id}/word:adopt", response_model=WordStatus, operation_id="adoptWordPdf")
def adopt_word_pdf(version_id: str, body: WordAdoptRequest, session: CurrentSession, key: IdemKey, ctr: Ctr) -> Body:
    def apply(conn: Connection) -> WordStatus:
        version = files.get_version(conn, session.actor, version_id)
        if not body.reviewed_pdf:
            raise Unprocessable("pdf_review_required", "请先查看并核对实际 PDF")
        word_materials.adopt(conn, version.project_id, version_id, body.link_id, session.actor.member_id, body.reason)
        if ctr.settings.auto_analysis:
            pipeline.advance(conn, ctr.store, version.project_id)
        return word_materials.status(conn, version.project_id, version_id)

    return mutate(ctr, session, key, f"POST /files/{version_id}/word:adopt", body, apply)


@router.post("/files/{version_id}/word:retry", response_model=WordStatus, operation_id="retryWordConversion")
def retry_word(version_id: str, body: WordRetryRequest, session: CurrentSession, key: IdemKey, ctr: Ctr) -> Body:
    def apply(conn: Connection) -> WordStatus:
        version = files.get_version(conn, session.actor, version_id)
        settings = ctr.settings
        if not settings.word_renderer_fingerprint:
            raise Unavailable("word_renderer_not_configured", "转换服务尚未启用，请为此稿补交 PDF")
        word_materials.lock(conn, version.project_id)
        original = word_materials.source(conn, version.project_id, version_id)
        if not word_materials.current(conn, original):
            raise Conflict("word_source_stale", "该 Word 已有新版本")
        if db.scalar(
            conn,
            """SELECT count(*) FROM jobs WHERE project_id=:p AND kind='parse'
            AND input_json->>'file_version_id'=:v AND state IN ('queued','running','cancel_requested')""",
            {"p": version.project_id, "v": version_id},
        ):
            raise Conflict("word_conversion_running", "此稿转换仍在进行")
        word_materials.enqueue_parse(conn, version.project_id, version_id, f"word-retry:{session.actor.member_id}:{key}")
        return word_materials.status(conn, version.project_id, version_id)

    return mutate(ctr, session, key, f"POST /files/{version_id}/word:retry", body, apply)


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
