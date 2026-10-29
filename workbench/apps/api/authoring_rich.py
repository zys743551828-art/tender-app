"""RICH image API; separately registered, never silently enabled by the text router."""

import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from apps.api.auth import auth
from apps.api.authoring import response
from packages.authoring import rich_assets, rich_uploads
from packages.domain import storage
from packages.domain.runtime import DomainError, clean, connection, fetch, sha
from packages.domain.work_access import begin

router = APIRouter(prefix="/api/v1", tags=["authoring-rich"])
MAX_REQUEST_BYTES = 12 * 1024 * 1024


@router.get("/authoring/rich-capabilities")
def capabilities(r: Request):
    auth(r)
    from packages.authoring import rich_content
    from packages.authoring.rich_profile import configured
    from packages.authoring.rich_schema import BUILD

    try:
        installed = configured() is not None
    except DomainError:
        installed = False
    return {
        "schema_digest": rich_content.SCHEMA_DIGEST,
        "schema": rich_content.SCHEMA,
        "build_schema_digest": sha(BUILD),
        "image_upload_max_bytes": 8 * 1024 * 1024,
        "renderer_configured": installed,
        "runtime_verified_by_this_read": False,
        "table_pdf_geometry": "unverified",
        "pagination_modes": [
            {
                "mode": "chapter_start_new_page",
                "page_count_impact": "每章另起一页，可能增加物理页数",
            },
            {"mode": "continuous", "page_count_impact": "连续排版；实际章末页可能未知"},
        ],
    }


@router.post("/bids/{bid_id}/authoring-images")
async def upload(bid_id: UUID, r: Request):
    actor = await run_in_threadpool(auth, r, True)
    if r.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        raise DomainError("INVALID_AUTHORING_IMAGE_UPLOAD", "请使用明确JSON图片上传请求", 415)
    raw = bytearray()
    async for chunk in r.stream():
        if len(raw) + len(chunk) > MAX_REQUEST_BYTES:
            raise DomainError("AUTHORING_IMAGE_SIZE_LIMIT", "图片上传请求超过12MiB", 413)
        raw.extend(chunk)
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise DomainError(
            "INVALID_AUTHORING_IMAGE_UPLOAD", "图片上传请求不是有效JSON", 422
        ) from None
    value, replay = await run_in_threadpool(
        rich_uploads.upload,
        bid_id,
        actor["member_id"],
        r.headers.get("idempotency-key"),
        body,
        final_auth=lambda: auth(r, True)["member_id"],
    )
    return response(value, replay)


@router.get("/bids/{bid_id}/authoring-image-uploads/{upload_id}")
def upload_status(bid_id: UUID, upload_id: str, r: Request):
    actor = auth(r)
    if len(upload_id) != 64 or any(c not in "0123456789abcdef" for c in upload_id):
        raise DomainError("NOT_FOUND", "未找到图片上传记录", 404)
    with connection() as c:
        rows = c.execute(
            """SELECT event_type,payload,created_at FROM audit_entries
            WHERE bid_id=%s AND actor_id=%s AND payload->>'upload_id'=%s
              AND event_type=ANY(%s) ORDER BY created_at DESC,id DESC""",
            (
                bid_id,
                actor["member_id"],
                upload_id,
                [
                    "authoring.image_upload_prepared",
                    "authoring.image_upload_unconfirmed",
                    "authoring.image_upload_rejected",
                    "authoring.image_upload_completed",
                ],
            ),
        ).fetchall()
        if not rows:
            raise DomainError("NOT_FOUND", "未找到本成员的图片上传记录", 404)
        completed = next(
            (row for row in rows if row["event_type"] == "authoring.image_upload_completed"), None
        )
        row = completed or rows[0]
        data = row["payload"]
        return {
            "upload_id": upload_id,
            "state": data["state"],
            "asset_id": data.get("asset_id"),
            "asset_version_id": data.get("asset_version_id"),
            "error_code": data.get("error_code"),
            "automatic_retry": False,
            "retry_requires_same_input": True,
            "updated_at": row["created_at"],
        }


@router.get("/bids/{bid_id}/authoring-images")
def images(
    bid_id: UUID, r: Request, cursor: UUID | None = None, limit: int = Query(50, ge=1, le=100)
):
    auth(r)
    with connection() as c:
        fetch(c, "SELECT id FROM bids WHERE id=%s", (bid_id,))
        rows = c.execute(
            "SELECT id FROM authoring_image_assets WHERE bid_id=%s AND (%s::uuid IS NULL OR id>%s) ORDER BY id LIMIT %s",
            (bid_id, cursor, cursor, limit + 1),
        ).fetchall()
        return {
            "items": [rich_assets.version(c, bid_id, row["id"]) for row in rows[:limit]],
            "next_cursor": str(rows[limit - 1]["id"]) if len(rows) > limit else None,
        }


@router.get("/bids/{bid_id}/authoring-images/{asset_id}")
def current(bid_id: UUID, asset_id: UUID, r: Request):
    auth(r)
    with connection() as c:
        value = rich_assets.version(c, bid_id, asset_id)
        return JSONResponse(clean(value), headers={"ETag": value["etag"]})


@router.get("/bids/{bid_id}/authoring-images/{asset_id}/versions/{version_id}")
def history(bid_id: UUID, asset_id: UUID, version_id: UUID, r: Request):
    auth(r)
    with connection() as c:
        return rich_assets.version(c, bid_id, asset_id, version_id)


@router.post("/bids/{bid_id}/authoring-images/{asset_id}/withdraw")
def withdraw(bid_id: UUID, asset_id: UUID, r: Request, body: dict = Body(...)):
    actor = auth(r, True)
    if set(body) != {"reason"}:
        raise DomainError("INVALID_REQUEST", "请记录停用原因", 422)
    if not r.headers.get("if-match"):
        raise DomainError("PRECONDITION_REQUIRED", "请刷新图片后重试", 428)
    with connection() as c:
        fetch(
            c, "SELECT id FROM authoring_image_assets WHERE bid_id=%s AND id=%s", (bid_id, asset_id)
        )
        command = begin(
            c,
            actor["member_id"],
            "withdraw-authoring-image",
            asset_id,
            r.headers.get("idempotency-key"),
            body,
            r.headers.get("if-match"),
            bid=bid_id,
        )
        if command.replay:
            return response(command.replay, True)
        value = rich_assets.withdraw(
            c, bid_id, asset_id, actor["member_id"], r.headers.get("if-match"), body["reason"]
        )
        return response(command.finish(value, headers={"ETag": value["etag"]}))


@router.get("/bids/{bid_id}/authoring-images/{asset_id}/versions/{version_id}/bytes/{variant}")
def image_bytes(
    bid_id: UUID,
    asset_id: UUID,
    version_id: UUID,
    variant: Literal["original", "normalized"],
    r: Request,
):
    auth(r)
    with connection() as c:
        value = rich_assets.version(c, bid_id, asset_id, version_id)
        blob = fetch(c, "SELECT * FROM blobs WHERE id=%s", (UUID(value[variant + "_blob_id"]),))
    data = storage.get(blob["object_key"])
    if len(data) != blob["byte_size"] or sha(data) != blob["digest"]:
        raise DomainError("AUTHORING_IMAGE_BYTES_CHANGED", "图片历史字节与登记摘要不同", 409)
    suffix = "jpg" if blob["media_type"] == "image/jpeg" else "png"
    return Response(
        data,
        media_type=blob["media_type"],
        headers={
            "Content-Disposition": f'attachment; filename="image-{variant}.{suffix}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
