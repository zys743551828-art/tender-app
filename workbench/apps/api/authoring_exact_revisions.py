"""Read real B3 adoption capabilities and immutable revision qualification."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from psycopg.errors import QueryCanceled

from apps.api.auth import auth
from packages.authoring import candidate_source_trace, exact_sources, exact_text_edit_service
from packages.authoring import exact_revision_contracts as models
from packages.authoring.exact_marked_text_edit_contracts import (
    AuthoringExactMarkedManualRevisionView,
    AuthoringExactMarkedTextEditCapabilities,
    AuthoringExactMarkedTextEditRequest,
    AuthoringExactMarkedTextEditResult,
)
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
from packages.domain.runtime import DomainError, connection

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
    | AuthoringExactMultiManualRevisionView
    | AuthoringExactMarkedManualRevisionView,
)
def qualification(bid_id: UUID, revision_id: UUID, r: Request):
    auth(r)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return exact_sources.load(c, bid_id, revision_id)


@router.get(
    "/bids/{bid_id}/authoring/section-revisions/{revision_id}/candidate-source-trace",
    operation_id="readHistoricalAuthoringCandidateSources",
    response_model=candidate_source_trace.HistoricalCandidateTrace,
    openapi_extra={"security": [{"SessionCookie": []}]},
)
def historical_candidate_sources(
    bid_id: UUID,
    revision_id: UUID,
    r: Request,
    snapshot_id: UUID,
    snapshot_digest: Annotated[str, Query(pattern=r"^[0-9a-f]{64}$")],
    qualification_digest: Annotated[str, Query(pattern=r"^[0-9a-f]{64}$")],
    action_id: UUID,
):
    auth(r)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        c.execute("SET LOCAL statement_timeout = '5s'")
        try:
            return candidate_source_trace.read(
                c,
                bid_id,
                revision_id,
                snapshot_id,
                snapshot_digest,
                qualification_digest,
                action_id,
            )
        except QueryCanceled as exc:
            raise DomainError(
                "AUTHORING_CANDIDATE_TRACE_TIMEOUT",
                "读取原候选原页超时，可重试同一份回执。",
                503,
                retryable=True,
            ) from exc


@router.get(
    "/authoring/exact-text-edit-capabilities",
    response_model=AuthoringExactTextEditCapabilities | AuthoringExactMultiTextEditCapabilities,
)
def text_edit_capabilities(r: Request):
    auth(r)
    with connection() as c:
        return exact_text_edit_service.capabilities(c)


@router.get(
    "/authoring/exact-marked-text-edit-capabilities",
    response_model=AuthoringExactMarkedTextEditCapabilities,
)
def marked_text_edit_capabilities(r: Request):
    auth(r)
    with connection() as c:
        return exact_text_edit_service.marked_capabilities(c)


@router.post(
    "/bids/{bid_id}/authoring/drafts/{draft_id}/exact-text-edits",
    response_model=AuthoringExactTextEditResult
    | AuthoringExactMultiTextEditResult
    | AuthoringExactMarkedTextEditResult,
)
def edit_text(
    bid_id: UUID,
    draft_id: UUID,
    r: Request,
    body: AuthoringExactTextEditRequest
    | AuthoringExactMultiTextEditRequest
    | AuthoringExactMarkedTextEditRequest,
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
