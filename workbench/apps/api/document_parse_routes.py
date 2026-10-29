"""Explicit standalone PDF parse requests, independent of material/body selection."""

from uuid import UUID

from fastapi import APIRouter, Body, Query, Request

from apps.api.auth import auth
from apps.api.identity_routes import saved
from packages.domain import document_parses

router = APIRouter(
    prefix="/api/v1/bids/{bid_id}/documents/{document_version_id}", tags=["document parsing"]
)


@router.get("/parse-context")
def context(bid_id: UUID, document_version_id: UUID, r: Request):
    auth(r)
    return document_parses.read_context(bid_id, document_version_id)


@router.post("/parse-requests")
def start(bid_id: UUID, document_version_id: UUID, r: Request, body: dict = Body(...)):
    actor = auth(r, True)
    response, replayed = document_parses.start(
        bid_id,
        document_version_id,
        actor["member_id"],
        r.headers.get("idempotency-key"),
        body,
        final_auth=lambda: auth(r, True)["member_id"],
    )
    return saved(response, replayed)


@router.get("/parse-requests")
def directory(
    bid_id: UUID,
    document_version_id: UUID,
    r: Request,
    limit: int = Query(default=10, ge=1, le=50),
    cursor: str | None = None,
):
    auth(r)
    return document_parses.directory(bid_id, document_version_id, limit=limit, cursor=cursor)


@router.get("/parse-requests/{request_id}")
def read(bid_id: UUID, document_version_id: UUID, request_id: UUID, r: Request):
    auth(r)
    return document_parses.read(bid_id, document_version_id, request_id)
