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


@router.get("/material-qualifications/{qualification_id}")
def qualification_read(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    scope_id: UUID,
    qualification_id: UUID,
    r: Request,
):
    from packages.model_governance import material_qualification_registry as registry

    auth(r)
    with requirement_errors(), connection() as c:
        value, tag = registry.read(
            c,
            tuple(map(str, (bid_id, package_id, revision_id))),
            str(scope_id),
            str(qualification_id),
        )
        return JSONResponse(value, headers={"ETag": tag, "Cache-Control": "private, no-store"})


@router.post("/material-qualifications")
def qualification_register(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    scope_id: UUID,
    r: Request,
    body: dict = Body(...),
):
    from packages.model_governance import material_qualification_registry as registry

    actor = auth(r, True)["member_id"]
    with requirement_errors(), connection() as c:
        result, replay = registry.register(
            c,
            tuple(map(str, (bid_id, package_id, revision_id))),
            str(scope_id),
            actor,
            body,
            r.headers.get("idempotency-key"),
        )
        return JSONResponse(
            result["body"],
            status_code=result["status"],
            headers=result["headers"] | {"Idempotent-Replayed": str(replay).lower()},
        )


@router.post("/material-qualifications/{qualification_id}/decisions")
def qualification_review(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    scope_id: UUID,
    qualification_id: UUID,
    r: Request,
    body: dict = Body(...),
):
    from packages.model_governance import material_qualification_registry as registry

    actor = auth(r, True)["member_id"]
    with requirement_errors(), connection() as c:
        result, replay = registry.review(
            c,
            tuple(map(str, (bid_id, package_id, revision_id))),
            str(scope_id),
            str(qualification_id),
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


def _qualified_resume(scope, scope_id, actor, intent_id):
    from packages.domain.errors import DomainError
    from packages.model_governance import material_qualification_guard as guard
    from packages.model_governance import material_qualified_job_transport as transport
    from packages.model_governance import material_qualified_jobs as qualified

    # The intent/Command transaction has committed. No API source, bid, review
    # or ledger lock spans the independent-purpose native transaction.
    with connection() as c:
        row = qualified.intent(c, scope, scope_id, actor, intent_id)
        value = qualified.observe(c, row)
        if value["job"] is not None:
            return value
        try:
            guard.audit(c)
            if row["document"].get("guard_digest") != guard.method_digest():
                qualified.policy.fail("GUARD_CHANGED", "原申请的资格守卫版本已变化", 409)
            qualified.current(c, scope_id, row["document"]["request"])
        except DomainError as error:
            # Re-read after acquiring the review lock: a native commit may have
            # won the race with a concurrent revocation or expiration.
            return qualified.observe(c, row, pending_reason=error.code)
        command = row["document"]["command"]
    outcome = transport.submit(command)
    with connection() as c:
        row = qualified.intent(c, scope, scope_id, actor, intent_id)
        return qualified.observe(c, row, pending_reason="NATIVE_" + outcome.upper())


@router.post("/material-qualified-jobs")
def qualified_job_request(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    scope_id: UUID,
    r: Request,
    body: dict = Body(...),
):
    from packages.model_governance import material_qualified_jobs as qualified

    actor = auth(r, True)["member_id"]
    scope = tuple(map(str, (bid_id, package_id, revision_id)))
    with requirement_errors():
        with connection() as c:
            intent_id = qualified.prepare(
                c,
                scope,
                str(scope_id),
                actor,
                body,
                r.headers.get("if-match"),
                r.headers.get("idempotency-key"),
            )
        value = _qualified_resume(scope, str(scope_id), actor, intent_id)
        return JSONResponse(
            value,
            status_code=200 if value["job"] else 202,
            headers={"Cache-Control": "private, no-store"},
        )


@router.get("/material-qualified-jobs/{intent_id}")
def qualified_job_read(
    bid_id: UUID, package_id: UUID, revision_id: UUID, scope_id: UUID, intent_id: UUID, r: Request
):
    from packages.model_governance import material_qualified_jobs as qualified

    actor = auth(r)["member_id"]
    with requirement_errors(), connection() as c:
        row = qualified.intent(
            c,
            tuple(map(str, (bid_id, package_id, revision_id))),
            str(scope_id),
            actor,
            str(intent_id),
        )
        return JSONResponse(
            qualified.observe(c, row), headers={"Cache-Control": "private, no-store"}
        )


@router.get("/material-qualified-jobs/{intent_id}/execution-state")
def qualified_execution_state(
    bid_id: UUID, package_id: UUID, revision_id: UUID, scope_id: UUID, intent_id: UUID, r: Request
):
    from packages.model_governance import material_execution_status as status
    from packages.model_governance import material_qualified_jobs as qualified

    actor = auth(r)["member_id"]
    with requirement_errors(), connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        row = qualified.intent(
            c,
            tuple(map(str, (bid_id, package_id, revision_id))),
            str(scope_id),
            actor,
            str(intent_id),
        )
        return JSONResponse(status.observe(c, row), headers={"Cache-Control": "private, no-store"})
