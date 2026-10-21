"""Opt-in saved draft/build work contexts and explicit four-stage choices."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request

from apps.api.auth import auth
from apps.api.work_context_routes import query, response
from packages.contracts.work_context_catalog_api import BUILD_PATH, CHOICES_PATH, SNAPSHOT_PATH
from packages.work_contexts import authoring_service as service

router = APIRouter(tags=["explicit-work-contexts"])


@router.get(CHOICES_PATH)
def choices(
    bid_id: UUID,
    r: Request,
    kind: Literal["draft_snapshot", "build", "package_review_run", "package_submission"] = Query(
        ...
    ),
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, min_length=1, max_length=4096),
    draft_id: UUID | None = Query(default=None),
    package_id: UUID | None = Query(default=None),
    revision_id: UUID | None = Query(default=None),
):
    auth(r)
    query(r, ("kind", "limit", "cursor", "draft_id", "package_id", "revision_id"))
    return response(
        service.choices(
            str(bid_id),
            kind,
            limit=limit,
            cursor=cursor,
            draft_id=str(draft_id) if draft_id else None,
            package_id=str(package_id) if package_id else None,
            revision_id=str(revision_id) if revision_id else None,
        )
    )


@router.get(SNAPSHOT_PATH)
def resolve_snapshot(
    bid_id: UUID,
    snapshot_id: UUID,
    r: Request,
    expected_selection_digest: str | None = Query(default=None, pattern="^[a-f0-9]{64}$"),
):
    auth(r)
    query(r, ("expected_selection_digest",))
    return response(
        service.resolve_snapshot(
            str(bid_id), str(snapshot_id), expected_selection_digest=expected_selection_digest
        )
    )


@router.get(BUILD_PATH)
def resolve_build(
    bid_id: UUID,
    build_id: UUID,
    r: Request,
    expected_selection_digest: str | None = Query(default=None, pattern="^[a-f0-9]{64}$"),
):
    auth(r)
    query(r, ("expected_selection_digest",))
    return response(
        service.resolve_build(
            str(bid_id), str(build_id), expected_selection_digest=expected_selection_digest
        )
    )
