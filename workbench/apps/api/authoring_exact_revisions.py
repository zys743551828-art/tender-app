"""Read real B3 adoption capabilities and immutable revision qualification."""

from uuid import UUID

from fastapi import APIRouter, Request

from apps.api.auth import auth
from packages.authoring import exact_revision_contracts as models
from packages.authoring import exact_sources, exact_text_edit_service
from packages.authoring.exact_text_edit_contracts import (
    AuthoringExactManualRevisionView,
    AuthoringExactMultiManualRevisionView,
    AuthoringExactMultiTextEditCapabilities,
    AuthoringExactMultiTextEditRequest,
    AuthoringExactMultiTextEditResult,
    AuthoringExactTextEditCapabilities,
    AuthoringExactTextEditRequest,
    AuthoringExactTextEditResult,
)
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
    response_model=models.AuthoringExactRevisionView
    | AuthoringExactManualRevisionView
    | AuthoringExactMultiManualRevisionView,
)
def qualification(bid_id: UUID, revision_id: UUID, r: Request):
    auth(r)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return exact_sources.load(c, bid_id, revision_id)


@router.get(
    "/authoring/exact-text-edit-capabilities",
    response_model=AuthoringExactTextEditCapabilities | AuthoringExactMultiTextEditCapabilities,
)
def text_edit_capabilities(r: Request):
    auth(r)
    with connection() as c:
        return exact_text_edit_service.capabilities(c)


@router.post(
    "/bids/{bid_id}/authoring/drafts/{draft_id}/exact-text-edits",
    response_model=AuthoringExactTextEditResult | AuthoringExactMultiTextEditResult,
)
def edit_text(
    bid_id: UUID,
    draft_id: UUID,
    r: Request,
    body: AuthoringExactTextEditRequest | AuthoringExactMultiTextEditRequest,
):
    from apps.api.authoring import response

    actor = auth(r, True)
    result, replay = exact_text_edit_service.save(
        actor["member_id"],
        bid_id,
        draft_id,
        r.headers.get("idempotency-key"),
        r.headers.get("if-match"),
        body.model_dump(mode="json"),
        final_auth=lambda: auth(r, True),
    )
    return response(result, replay)
