"""Explicit multi-section generation, bounded retries and one draft confirmation."""

from uuid import UUID

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse

from apps.api.auth import auth
from apps.api.authoring import response
from packages.assistant import generation_batch_contracts as contracts
from packages.domain.runtime import clean, connection

router = APIRouter(prefix="/api/v1", tags=["authoring-generation-batches"])
BASE = "/bids/{bid_id}/drafts/{draft_id}/generation-batches"


def service():
    # Keep the optional assistant runtime out of API startup and contract export.
    from packages.assistant import generation_batches

    return generation_batches


def _read(value, *, tagged=False):
    headers = {"Cache-Control": "private, no-store"}
    if tagged:
        headers["ETag"] = value["etag"]
    return JSONResponse(clean(value), headers=headers)


@router.get("/authoring/generation-batch-capabilities")
def capabilities(r: Request):
    auth(r)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        return _read(service().capabilities(c))


@router.post(BASE)
def create(bid_id: UUID, draft_id: UUID, r: Request, body: dict = Body(...)):
    actor = auth(r, True)
    contracts.validate("AuthoringGenerationBatchCreateRequest", body)
    with connection() as c:
        value, replay = service().create(
            c,
            bid_id,
            draft_id,
            actor["member_id"],
            r.headers.get("idempotency-key"),
            body,
            r.headers.get("if-match"),
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
        return _read(service().history(c, bid_id, draft_id, cursor=cursor, limit=limit))


@router.get(BASE + "/{batch_id}")
def detail(bid_id: UUID, draft_id: UUID, batch_id: UUID, r: Request):
    auth(r)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        return _read(service().load(c, bid_id, draft_id, batch_id), tagged=True)


@router.get(BASE + "/{batch_id}/candidates/{action_id}")
def candidate(bid_id: UUID, draft_id: UUID, batch_id: UUID, action_id: UUID, r: Request):
    auth(r)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        return _read(service().candidate(c, bid_id, draft_id, batch_id, action_id), tagged=True)


@router.post(BASE + "/{batch_id}/retry")
def retry(bid_id: UUID, draft_id: UUID, batch_id: UUID, r: Request, body: dict = Body(...)):
    actor = auth(r, True)
    contracts.validate("AuthoringGenerationBatchRetryRequest", body)
    with connection() as c:
        value, replay = service().retry(
            c,
            bid_id,
            draft_id,
            batch_id,
            actor["member_id"],
            r.headers.get("idempotency-key"),
            body,
            r.headers.get("if-match"),
        )
        return response(value, replay)


@router.post(BASE + "/{batch_id}/resolve")
def resolve(bid_id: UUID, draft_id: UUID, batch_id: UUID, r: Request, body: dict = Body(...)):
    actor = auth(r, True)
    contracts.validate("AuthoringGenerationBatchResolveRequest", body)
    with connection() as c:
        value, replay = service().resolve(
            c,
            bid_id,
            draft_id,
            batch_id,
            actor["member_id"],
            r.headers.get("idempotency-key"),
            body,
            r.headers.get("if-match"),
        )
        return response(value, replay)
