"""Read real B3 adoption capabilities and immutable revision qualification."""

from uuid import UUID

from fastapi import APIRouter, Request

from apps.api.auth import auth
from packages.authoring import exact_revision_contracts as models
from packages.authoring import exact_sources
from packages.domain.runtime import connection

router = APIRouter(prefix="/api/v1", tags=["authoring-exact-revisions"])


@router.get(
    "/authoring/exact-revision-capabilities",
    response_model=models.AuthoringExactRevisionCapabilities,
)
def capabilities(r: Request):
    auth(r)
    with connection() as c:
        return exact_sources.capabilities(c)


@router.get(
    "/bids/{bid_id}/authoring/drafts/{draft_id}/exact-qualification",
    response_model=models.AuthoringExactDraftStatus,
)
def draft_status(bid_id: UUID, draft_id: UUID, r: Request):
    auth(r)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return exact_sources.draft_status(c, bid_id, draft_id)


@router.get(
    "/bids/{bid_id}/authoring/section-revisions/{revision_id}/exact-qualification",
    response_model=models.AuthoringExactRevisionView,
)
def qualification(bid_id: UUID, revision_id: UUID, r: Request):
    auth(r)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return exact_sources.load(c, bid_id, revision_id)
