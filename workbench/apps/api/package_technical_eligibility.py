"""Read-only exact technical scope qualification and historical association."""

from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from apps.api.auth import auth
from apps.api.bid_package_requirement_routes import requirement_errors
from packages.domain import bid_package_technical_eligibility_service as service
from packages.domain.runtime import connection

BASE = "/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/technical-scopes/{scope_id}"
router = APIRouter(prefix=BASE, tags=["package-technical-eligibility"])


def _response(result):
    value, tag = result
    return JSONResponse(value, headers={"Cache-Control": "private, no-store", "ETag": tag})


@router.get("/scoring-context")
def scoring_context(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    scope_id: UUID,
    r: Request,
    scale_id: UUID | None = Query(None),
):
    auth(r)
    with requirement_errors(), connection() as c:
        return _response(
            service.scoring_context(
                c, tuple(map(str, (bid_id, package_id, revision_id))), str(scope_id), scale_id
            )
        )


@router.get("/sample-context")
def sample_context(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    scope_id: UUID,
    r: Request,
    submission_id: UUID = Query(...),
    outcome_id: UUID | None = Query(None),
    scale_id: UUID | None = Query(None),
):
    auth(r)
    with requirement_errors(), connection() as c:
        return _response(
            service.sample_context(
                c,
                tuple(map(str, (bid_id, package_id, revision_id))),
                str(scope_id),
                str(submission_id),
                outcome_id,
                scale_id,
            )
        )
