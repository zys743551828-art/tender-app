"""Explicit DOCX candidates, complete mapping previews and confirmed draft appends."""

from uuid import UUID

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from apps.api.auth import auth
from apps.api.authoring import response
from packages.authoring import docx_import_contracts as contracts
from packages.authoring import docx_import_service as service
from packages.domain import storage
from packages.domain.runtime import DomainError, clean, connection, sha

router = APIRouter(prefix="/api/v1", tags=["authoring-word-import"])
BASE = "/bids/{bid_id}/drafts/{draft_id}/word-imports"


@router.get("/authoring/word-import-capabilities")
def capabilities(r: Request):
    auth(r)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        return service.capabilities(c)


@router.post(BASE)
async def prepare(bid_id: UUID, draft_id: UUID, r: Request, body: dict = Body(...)):
    actor = await run_in_threadpool(auth, r, True)
    contracts.validate("AuthoringWordImportPrepareRequest", body)
    value, replay = await run_in_threadpool(
        service.prepare,
        bid_id,
        draft_id,
        actor["member_id"],
        r.headers.get("idempotency-key"),
        body,
        r.headers.get("if-match"),
        final_auth=lambda: auth(r, True)["member_id"],
    )
    return response(value, replay)


@router.get(BASE)
def history(
    bid_id: UUID,
    draft_id: UUID,
    r: Request,
    cursor: str | None = Query(None, max_length=2000),
    limit: int = Query(20, ge=1, le=50),
):
    auth(r)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        return service.history(c, bid_id, draft_id, cursor=cursor, limit=limit)


@router.get(BASE + "/{candidate_id}")
def candidate(bid_id: UUID, draft_id: UUID, candidate_id: UUID, r: Request):
    auth(r)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        value = service.load(c, bid_id, draft_id, candidate_id)
        return JSONResponse(clean(value))


@router.post(BASE + "/{candidate_id}/resolve")
async def resolve(
    bid_id: UUID, draft_id: UUID, candidate_id: UUID, r: Request, body: dict = Body(...)
):
    actor = await run_in_threadpool(auth, r, True)
    contracts.validate("AuthoringWordImportResolveRequest", body)
    value, replay = await run_in_threadpool(
        service.resolve,
        bid_id,
        draft_id,
        candidate_id,
        actor["member_id"],
        r.headers.get("idempotency-key"),
        body,
        r.headers.get("if-match"),
        final_auth=lambda: auth(r, True)["member_id"],
    )
    return response(value, replay)


@router.get(BASE + "/{candidate_id}/images/{image_key}")
def image_preview(bid_id: UUID, draft_id: UUID, candidate_id: UUID, image_key: UUID, r: Request):
    auth(r)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        descriptor = service.image_descriptor(c, bid_id, draft_id, candidate_id, image_key)
    # Historical previews use the exact staged normalized raster. No object read
    # or source qualification is performed while a database transaction is open.
    data = storage.get(descriptor["object_key"])
    if (
        descriptor["media_type"] != "image/png"
        or len(data) != descriptor["byte_size"]
        or sha(data) != descriptor["digest"]
    ):
        raise DomainError(
            "AUTHORING_WORD_IMPORT_IMAGE_CHANGED", "导入图片预览与候选记录的字节不一致", 409
        )
    return Response(
        data,
        media_type="image/png",
        headers={
            "Content-Disposition": 'inline; filename="word-import-image.png"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "X-Content-SHA256": descriptor["digest"],
        },
    )
