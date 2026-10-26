"""Visible formal execution refusal; no public mechanism-test permission switch."""

from uuid import UUID

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse

from apps.api.auth import auth
from apps.api.bid_package_requirement_routes import requirement_errors
from packages.domain.runtime import connection
from packages.model_governance import package_scoring_readiness as readiness

BASE = "/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/technical-scopes/{scope_id}"
router = APIRouter(prefix=BASE, tags=["package-technical-execution"])


@router.get("/execution-context")
def context(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    scope_id: UUID,
    r: Request,
    scale_id: UUID | None = Query(None),
):
    auth(r)
    with requirement_errors(), connection() as c:
        value, tag = readiness.context(
            c,
            tuple(map(str, (bid_id, package_id, revision_id))),
            str(scope_id),
            str(scale_id) if scale_id else None,
        )
        return JSONResponse(value, headers={"Cache-Control": "private, no-store", "ETag": tag})


@router.post("/executions")
def create(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    scope_id: UUID,
    r: Request,
    body: dict = Body(...),
):
    auth(r, True)
    with requirement_errors(), connection() as c:
        return readiness.request_execution(
            c,
            tuple(map(str, (bid_id, package_id, revision_id))),
            str(scope_id),
            body,
            r.headers.get("if-match"),
        )


@router.get("/material-execution-context")
def material_context(bid_id: UUID, package_id: UUID, revision_id: UUID, scope_id: UUID, r: Request):
    from packages.model_governance import package_material_execution_check as material

    auth(r)
    with requirement_errors(), connection() as c:
        value, tag = material.context(
            c, tuple(map(str, (bid_id, package_id, revision_id))), str(scope_id)
        )
        return JSONResponse(value, headers={"Cache-Control": "private, no-store", "ETag": tag})


@router.post("/material-execution-checks")
def material_check(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    scope_id: UUID,
    r: Request,
    body: dict = Body(...),
):
    from packages.model_governance import package_material_execution_check as material

    actor = auth(r, True)["member_id"]
    with requirement_errors(), connection() as c:
        result, replay = material.check(
            c,
            tuple(map(str, (bid_id, package_id, revision_id))),
            str(scope_id),
            actor,
            body,
            r.headers.get("if-match"),
            r.headers.get("idempotency-key"),
        )
        return JSONResponse(
            result["body"],
            status_code=result["status"],
            headers=result["headers"] | {"Idempotent-Replayed": str(replay).lower()},
        )
