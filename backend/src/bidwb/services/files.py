"""资料上传与文件版本。

流程（TECH-001 §6.3）：
    initUpload      服务端分配 upload ID，在暂存键上开分片上传并签发预签名分片地址
    浏览器直传      分片直接 PUT 到对象存储，应用服务器不经手大文件
    completeUpload  合并分片 → 流式复算 SHA-256 与大小 → 一致则复制到内容寻址的不可覆盖键，
                    并在一个事务里提交产物与文件版本；不一致则隔离，不可下载
文件版本一旦写入不可改（触发器强制）。版本关系显式声明：上传请求带 ``version_of_file_id`` 才成为该文件的下一版本
（``supersedes`` 指向上一版本）；不带则总是新的逻辑文件，即使用途与原名相同。
唯一的隐式规则是去重：字节完全相同的再次上传（不带 ``version_of_file_id`` 时要求同项目、同用途、同原名，且命中某文件的最新版本；
带时与该文件的最新版本比较）直接返回已有版本，``duplicate=true``，不新建版本、不再解析。
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import Connection

from bidwb import db, tasks
from bidwb.access import Actor, require_project
from bidwb.config import Settings
from bidwb.errors import Conflict, ContentMismatch, NotFound, Unavailable, Unprocessable
from bidwb.logs import get_logger
from bidwb.schemas import ArtifactRef, FileVersion, PartUrl, UploadComplete, UploadRequest, UploadResult, UploadSession
from bidwb.services import audit
from bidwb.storage import ObjectStore, ObjectStoreError, content_key, staging_key
from bidwb.util import canonical_json, new_id, sha256_hex, utcnow

log = get_logger(__name__)

PART_BYTES = 8 * 1024 * 1024
MAX_PARTS = 13
ALLOWED_MEDIA_TYPES = frozenset(
    {
        "application/pdf",
        "application/zip",
        "application/msword",
        "text/plain",
        "text/csv",
        "image/png",
        "image/jpeg",
        "image/tiff",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "application/octet-stream",
    }
)
CONTRACT_VERSION = "file-v1"


@dataclass(frozen=True)
class StoredContent:
    """``/files/{id}/content`` 需要的最小信息。"""

    object_key: str
    byte_size: int
    media_type: str
    sha256: str
    original_name: str


def _session_response(store: ObjectStore, settings: Settings, row: db.Row) -> UploadSession:
    ttl = settings.upload_url_ttl_seconds
    expires = min(utcnow() + timedelta(seconds=ttl), row["expires_at"])
    count = math.ceil(row["expected_bytes"] / row["part_bytes"])
    parts = [
        PartUrl(part_number=n, url=store.presign_part(row["staging_key"], row["oss_upload_id"], n, ttl), expires_at=expires)
        for n in range(1, count + 1)
    ]
    return UploadSession(upload_id=row["id"], part_bytes=row["part_bytes"], part_count=count, parts=parts, expires_at=row["expires_at"])


def init_upload(
    conn: Connection,
    store: ObjectStore,
    settings: Settings,
    actor: Actor,
    project_id: str,
    req: UploadRequest,
    idempotency_key: str,
    request_id: str,
) -> UploadSession:
    require_project(conn, actor, project_id)
    if req.byte_size > settings.upload_max_bytes:
        raise Unprocessable("file_too_large", f"单个文件不能超过 {settings.upload_max_bytes // (1024 * 1024)} MiB，请按原分册拆分上传")
    if req.media_type not in ALLOWED_MEDIA_TYPES:
        raise Unprocessable("media_type_not_allowed", "不支持的文件类型", media_type=req.media_type)
    if math.ceil(req.byte_size / PART_BYTES) > MAX_PARTS:
        raise Unprocessable("too_many_parts", "文件分片数超过上限")
    if req.version_of_file_id is not None:
        target = db.one(conn, "SELECT project_id, role FROM files WHERE id=:f", {"f": req.version_of_file_id})
        if target is None or target["project_id"] != project_id or target["role"] != req.role:
            raise Unprocessable(
                "version_of_invalid", "version_of_file_id 必须是本项目内同一用途的文件", version_of_file_id=req.version_of_file_id
            )
    request_hash = sha256_hex(canonical_json(req.model_dump()))
    existing = db.one(
        conn,
        "SELECT * FROM upload_sessions WHERE project_id=:p AND actor_id=:a AND idempotency_key=:k",
        {"p": project_id, "a": actor.member_id, "k": idempotency_key},
    )
    if existing is not None:
        if existing["request_hash"] != request_hash:
            raise Conflict("idempotency_conflict", "同一个幂等键已用于不同的上传请求")
        if existing["state"] != "open":
            raise Conflict("upload_not_open", "该上传会话已结束", state=existing["state"])
        return _session_response(store, settings, existing)
    upload_id = new_id("upl")
    key = staging_key(upload_id)
    try:
        oss_upload_id = store.create_multipart(key, req.media_type)
    except ObjectStoreError as exc:
        raise Unavailable("storage_unavailable", "对象存储暂不可用，请稍后重试") from exc
    now = utcnow()
    db.run(
        conn,
        """INSERT INTO upload_sessions(id,project_id,actor_id,role,original_name,expected_sha256,expected_bytes,expires_at,state,
                                       idempotency_key,request_hash,staging_key,oss_upload_id,part_bytes,created_at,media_type,version_of_file_id)
           VALUES (:id,:p,:a,:role,:name,:sha,:bytes,:exp,'open',:idem,:rh,:key,:oss,:pb,:now,:mt,:vof)""",
        {
            "id": upload_id,
            "p": project_id,
            "a": actor.member_id,
            "role": req.role,
            "name": req.original_name,
            "sha": req.sha256,
            "bytes": req.byte_size,
            "exp": now + timedelta(seconds=settings.upload_session_ttl_seconds),
            "idem": idempotency_key,
            "rh": request_hash,
            "key": key,
            "oss": oss_upload_id,
            "pb": PART_BYTES,
            "now": now,
            "mt": req.media_type,
            "vof": req.version_of_file_id,
        },
    )
    audit.record(
        conn,
        actor_id=actor.member_id,
        project_id=project_id,
        action="upload.init",
        object_kind="upload",
        object_id=upload_id,
        request_id=request_id,
        details={"role": req.role, "bytes": req.byte_size, "version_of_file_id": req.version_of_file_id},
    )
    row = db.one(conn, "SELECT * FROM upload_sessions WHERE id=:i", {"i": upload_id})
    assert row is not None
    return _session_response(store, settings, row)


_SESSION_SQL = "SELECT * FROM upload_sessions WHERE id=:i"
_SESSION_FOR_UPDATE_SQL = "SELECT * FROM upload_sessions WHERE id=:i FOR UPDATE"


def _own_open_session(conn: Connection, actor: Actor, upload_id: str, *, lock: bool = False) -> db.Row:
    row = db.one(conn, _SESSION_FOR_UPDATE_SQL if lock else _SESSION_SQL, {"i": upload_id})
    if row is None or row["actor_id"] != actor.member_id:
        raise NotFound("upload_not_found")
    require_project(conn, actor, row["project_id"])
    return row


def refresh_urls(conn: Connection, store: ObjectStore, settings: Settings, actor: Actor, upload_id: str) -> UploadSession:
    row = _own_open_session(conn, actor, upload_id)
    if row["state"] != "open":
        raise Conflict("upload_not_open", "该上传会话已结束", state=row["state"])
    if row["expires_at"] <= utcnow():
        raise Conflict("upload_expired", "上传会话已过期，请重新开始")
    return _session_response(store, settings, row)


def _artifact_for(conn: Connection, *, sha256: str, size: int, media_type: str, key: str, status: str) -> str:
    """同内容复用同一产物行（``object_key`` 唯一）。

    先插入、冲突则不动，再按键读出：两个项目同时完成同一内容的上传时，后到的一方等先到的事务结束后读到同一行，
    不会撞唯一约束。
    """
    db.run(
        conn,
        """INSERT INTO artifacts(id,sha256,object_key,byte_size,media_type,contract_version,created_at,status)
           VALUES (:i,:sha,:k,:size,:mt,:cv,:now,:st) ON CONFLICT (object_key) DO NOTHING""",
        {
            "i": new_id("art"),
            "sha": sha256,
            "k": key,
            "size": size,
            "mt": media_type,
            "cv": CONTRACT_VERSION,
            "now": utcnow(),
            "st": status,
        },
    )
    return str(db.scalar(conn, "SELECT id FROM artifacts WHERE object_key=:k", {"k": key}))


def complete_upload(
    conn: Connection,
    store: ObjectStore,
    actor: Actor,
    upload_id: str,
    req: UploadComplete,
    request_id: str,
) -> UploadResult:
    row = _own_open_session(conn, actor, upload_id, lock=True)
    if row["state"] == "completed":  # 重放：返回已生成的版本
        return _result(get_version(conn, actor, row["version_id"]), duplicate=row["duplicate"])
    if row["state"] != "open":
        raise Conflict("upload_not_open", "该上传会话已结束", state=row["state"])
    if row["expires_at"] <= utcnow():
        raise Conflict("upload_expired", "上传会话已过期，请重新开始")
    if req.sha256 != row["expected_sha256"]:
        raise Unprocessable("sha256_mismatch", "提交的校验值与声明不一致")
    expected_parts = math.ceil(row["expected_bytes"] / row["part_bytes"])
    numbers = sorted(p.part_number for p in req.parts)
    if numbers != list(range(1, expected_parts + 1)):
        raise Unprocessable("parts_incomplete", "分片编号不完整或超出范围", expected=expected_parts)
    key = row["staging_key"]
    try:
        store.complete_multipart(key, row["oss_upload_id"], [(p.part_number, p.etag) for p in req.parts])
        info = store.head(key)
        actual_sha = store.sha256(key) if info is not None else ""
    except ObjectStoreError as exc:
        raise Unavailable("storage_unavailable", "对象存储暂不可用，请稍后重试") from exc
    if info is None or info.size != row["expected_bytes"] or actual_sha != row["expected_sha256"]:
        _quarantine(conn, row, actual_sha, info.size if info else 0, request_id)
        raise ContentMismatch("content_mismatch", "服务端复算的校验值或大小与声明不一致，文件已隔离，请重新上传")
    final_key = content_key(actual_sha)
    try:
        store.copy_if_absent(key, final_key)
    except ObjectStoreError as exc:
        raise Unavailable("storage_unavailable", "对象存储暂不可用，请稍后重试") from exc
    artifact_id = _artifact_for(conn, sha256=actual_sha, size=info.size, media_type=row["media_type"], key=final_key, status="committed")
    version_id, duplicate = _commit_version(conn, row, artifact_id)
    db.run(
        conn,
        "UPDATE upload_sessions SET state='completed', version_id=:v, duplicate=:d WHERE id=:i",
        {"v": version_id, "d": duplicate, "i": upload_id},
    )
    for part in req.parts:
        size = min(row["part_bytes"], row["expected_bytes"] - (part.part_number - 1) * row["part_bytes"])
        db.run(
            conn,
            "INSERT INTO upload_parts(upload_id,part_number,etag,byte_size) VALUES (:u,:n,:e,:s) ON CONFLICT DO NOTHING",
            {"u": upload_id, "n": part.part_number, "e": part.etag, "s": size},
        )
    if not duplicate and row["role"] in {"tender", "supplement", "body", "submission"}:
        tasks.enqueue(
            conn,
            project_id=row["project_id"],
            kind="parse",
            purpose="business",
            idempotency_key=f"parse:{version_id}",
            input_json={"file_version_id": version_id},
        )
    audit.record(
        conn,
        actor_id=actor.member_id,
        project_id=row["project_id"],
        action="upload.complete",
        object_kind="file_version",
        object_id=version_id,
        request_id=request_id,
        details={
            "sha256": actual_sha,
            "bytes": info.size,
            "duplicate_of_latest": duplicate,
            "version_of_file_id": row["version_of_file_id"],
        },
    )
    try:
        store.delete(key)  # 暂存键已无用；失败只是多留一个对象，由生命周期规则清理
    except ObjectStoreError:
        log.warning("staging_cleanup_failed", upload_id=upload_id)
    return _result(get_version(conn, actor, version_id), duplicate=duplicate)


def _commit_version(conn: Connection, row: db.Row, artifact_id: str) -> tuple[str, bool]:
    """返回 ``(版本 ID, 是否命中字节去重)``；去重命中不新建版本。"""
    existing = _identical_latest(conn, row, artifact_id)
    if existing is not None:
        return str(existing["id"]), True
    previous = _latest_of_file(conn, row["version_of_file_id"]) if row["version_of_file_id"] else None
    return _insert_version(conn, row, artifact_id, previous), False


def _result(version: FileVersion, *, duplicate: bool) -> UploadResult:
    return UploadResult(**version.model_dump(), duplicate=duplicate, new_file=not duplicate and version.version_number == 1)


def _quarantine(conn: Connection, row: db.Row, actual_sha: str, size: int, request_id: str) -> None:
    """校验失败：保留证据（暂存对象不删），登记隔离产物，会话标为失败。"""
    if actual_sha:
        _artifact_for(
            conn, sha256=actual_sha, size=size, media_type="application/octet-stream", key=row["staging_key"], status="quarantined"
        )
    db.run(conn, "UPDATE upload_sessions SET state='failed' WHERE id=:i", {"i": row["id"]})
    audit.record(
        conn,
        actor_id=row["actor_id"],
        project_id=row["project_id"],
        action="upload.quarantine",
        object_kind="upload",
        object_id=row["id"],
        request_id=request_id,
        details={"expected": row["expected_sha256"], "actual": actual_sha},
    )
    log.warning("upload_quarantined", upload_id=row["id"], expected_bytes=row["expected_bytes"], actual_bytes=size)


def _latest_of_file(conn: Connection, file_id: str) -> db.Row | None:
    return db.one(
        conn,
        "SELECT id, file_id, artifact_id FROM file_versions WHERE file_id=:f ORDER BY obtained_at DESC, id DESC LIMIT 1",
        {"f": file_id},
    )


def _identical_latest(conn: Connection, row: db.Row, artifact_id: str) -> db.Row | None:
    """字节相同的已有版本（必须是其逻辑文件的最新版本）。

    声明了 ``version_of_file_id``：只与该文件的最新版本比较；没有声明：在同项目、同用途、同原名的文件中找。
    """
    if row["version_of_file_id"]:
        latest = _latest_of_file(conn, row["version_of_file_id"])
        return latest if latest is not None and latest["artifact_id"] == artifact_id else None
    return db.one(
        conn,
        """SELECT fv.id, fv.file_id, fv.artifact_id FROM file_versions fv JOIN files f ON f.id = fv.file_id
           WHERE fv.project_id=:p AND f.role=:role AND fv.original_name=:name AND fv.artifact_id=:a
             AND NOT EXISTS (SELECT 1 FROM file_versions n WHERE n.supersedes = fv.id)
           ORDER BY fv.obtained_at DESC, fv.id DESC LIMIT 1""",
        {"p": row["project_id"], "role": row["role"], "name": row["original_name"], "a": artifact_id},
    )


def is_latest_version(conn: Connection, project_id: str, version_id: str) -> bool:
    """该版本是否仍是它所属逻辑文件的最新版本。"""
    latest = db.one(
        conn,
        """SELECT fv.id FROM file_versions fv WHERE fv.project_id=:p AND fv.file_id=(SELECT file_id FROM file_versions WHERE id=:v)
           ORDER BY fv.obtained_at DESC, fv.id DESC LIMIT 1""",
        {"p": project_id, "v": version_id},
    )
    return latest is not None and latest["id"] == version_id


def _insert_version(conn: Connection, row: db.Row, artifact_id: str, previous: db.Row | None) -> str:
    now = utcnow()
    if previous is None:
        file_id = new_id("fil")
        db.run(
            conn,
            "INSERT INTO files(id,project_id,role,created_at) VALUES (:i,:p,:r,:now)",
            {"i": file_id, "p": row["project_id"], "r": row["role"], "now": now},
        )
    else:
        file_id = previous["file_id"]
    version_id = new_id("ver")
    db.run(
        conn,
        """INSERT INTO file_versions(id,project_id,file_id,artifact_id,original_name,obtained_at,association_status,supersedes,created_by)
           VALUES (:i,:p,:f,:a,:name,:now,'pending',:sup,:by)""",
        {
            "i": version_id,
            "p": row["project_id"],
            "f": file_id,
            "a": artifact_id,
            "name": row["original_name"],
            "now": now,
            "sup": previous["id"] if previous else None,
            "by": row["actor_id"],
        },
    )
    return version_id


# ------------------------------------------------------------------ 查询与读取
_VERSION_SQL = """SELECT fv.id,fv.project_id,fv.file_id,fv.original_name,f.role,fv.obtained_at,fv.document_date,fv.association_status,fv.supersedes,
       a.id AS art_id,a.sha256,a.media_type,a.byte_size,a.contract_version,a.status AS art_status,
       (SELECT count(*) FROM file_versions x WHERE x.file_id=fv.file_id AND (x.obtained_at, x.id) <= (fv.obtained_at, fv.id)) AS version_number
       FROM file_versions fv JOIN files f ON f.id=fv.file_id JOIN artifacts a ON a.id=fv.artifact_id """


def _version_from(row: db.Row) -> FileVersion:
    return FileVersion(
        version_id=row["id"],
        project_id=row["project_id"],
        file_id=row["file_id"],
        version_number=row["version_number"],
        original_name=row["original_name"],
        role=row["role"],
        artifact=ArtifactRef(
            artifact_id=row["art_id"],
            sha256=row["sha256"],
            media_type=row["media_type"],
            byte_size=row["byte_size"],
            contract_version=row["contract_version"],
        ),
        obtained_at=row["obtained_at"],
        document_date=row["document_date"],
        association_status=row["association_status"],
        supersedes=row["supersedes"],
    )


def get_version(conn: Connection, actor: Actor, version_id: str) -> FileVersion:
    row = db.one(conn, _VERSION_SQL + "WHERE fv.id=:i", {"i": version_id})
    if row is None:
        raise NotFound("file_not_found")
    require_project(conn, actor, row["project_id"])
    return _version_from(row)


def list_versions(conn: Connection, actor: Actor, project_id: str) -> list[FileVersion]:
    require_project(conn, actor, project_id)
    rows = db.all_(
        conn, _VERSION_SQL + "WHERE fv.project_id=:p AND a.status='committed' ORDER BY fv.obtained_at DESC, fv.id DESC", {"p": project_id}
    )
    return [_version_from(r) for r in rows]


def locate_content(conn: Connection, actor: Actor, version_id: str) -> StoredContent:
    """用于下载：只有已提交（未隔离）的产物可读。"""
    row = db.one(conn, _VERSION_SQL.replace("a.id AS art_id", "a.object_key,a.id AS art_id") + "WHERE fv.id=:i", {"i": version_id})
    if row is None:
        raise NotFound("file_not_found")
    require_project(conn, actor, row["project_id"])
    if row["art_status"] != "committed":
        raise NotFound("file_not_found")
    return StoredContent(row["object_key"], row["byte_size"], row["media_type"], row["sha256"], row["original_name"])


def parse_range(header: str | None, size: int) -> tuple[int, int, bool]:
    """解析单段 ``Range: bytes=a-b``。返回 ``(起, 止(含), 是否部分内容)``；不合法抛 ``Unprocessable``（API 层转 416）。"""
    if not header:
        return 0, size - 1, False
    unit, _, spec = header.partition("=")
    if unit.strip().lower() != "bytes" or "," in spec:
        raise Unprocessable("range_not_satisfiable", "只支持单段字节范围")
    start_s, _, end_s = spec.strip().partition("-")
    try:
        if start_s == "":  # 后缀范围：最后 N 字节
            length = int(end_s)
            if length <= 0:
                raise ValueError
            start, end = max(size - length, 0), size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else size - 1
    except ValueError as exc:
        raise Unprocessable("range_not_satisfiable", "字节范围格式不正确") from exc
    if start >= size or end < start:
        raise Unprocessable("range_not_satisfiable", "字节范围超出文件大小")
    return start, min(end, size - 1), True


def stream(store: ObjectStore, key: str, start: int, end: int) -> Iterator[bytes]:
    try:
        yield from store.read_range(key, start, end)
    except ObjectStoreError as exc:
        raise Unavailable("storage_unavailable", "对象存储暂不可用") from exc
