"""Exact-inventory human corrections with immutable history and explicit apply."""

from uuid import UUID

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from apps.api.auth import auth
from apps.api.identity_routes import saved
from packages.contracts import package_rule_corrections_api as contracts
from packages.domain.runtime import clean, connection

BASE = (
    "/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}"
    "/requirement-inventories/{inventory_id}"
)
router = APIRouter(prefix=BASE, tags=["bid-package-rule-corrections"])


def service():
    from packages.domain import bid_package_rule_corrections

    return bid_package_rule_corrections


def errors():
    from apps.api.bid_package_requirement_routes import requirement_errors

    return requirement_errors()


def scope(bid_id, package_id, revision_id, inventory_id):
    return tuple(map(str, (bid_id, package_id, revision_id, inventory_id)))


def read_response(value):
    return JSONResponse(clean(value), headers={"Cache-Control": "private, no-store"})


@router.post("/rule-corrections/preview")
def preview(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    r: Request,
    body: dict = Body(...),
):
    auth(r, True)
    with errors():
        contracts.validate("PackageRuleCorrectionRequest", body)
        with connection() as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            return read_response(
                service().preview(c, scope(bid_id, package_id, revision_id, inventory_id), body)
            )


@router.post("/rule-corrections")
async def apply(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    r: Request,
    body: dict = Body(...),
):
    actor = await run_in_threadpool(auth, r, True)
    with errors():
        contracts.validate("ApplyPackageRuleCorrection", body)
        result, replay = await run_in_threadpool(
            service().apply,
            scope(bid_id, package_id, revision_id, inventory_id),
            actor["member_id"],
            r.headers.get("idempotency-key"),
            body,
            r.headers.get("if-match"),
            final_auth=lambda: auth(r, True)["member_id"],
        )
        return saved(result, replay)


@router.get("/rule-corrections")
def history(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    r: Request,
    cursor: str | None = Query(None, max_length=2000),
    limit: int = Query(20, ge=1, le=50),
):
    auth(r)
    with errors(), connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        return read_response(
            service().history(
                c,
                scope(bid_id, package_id, revision_id, inventory_id),
                cursor=cursor,
                limit=limit,
            )
        )


@router.get("/rule-corrections/{correction_id}")
def detail(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    correction_id: UUID,
    r: Request,
):
    auth(r)
    with errors(), connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        return read_response(
            service().load(
                c, scope(bid_id, package_id, revision_id, inventory_id), str(correction_id)
            )
        )


@router.get("/rule-correction-evidence")
def evidence_directory(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    r: Request,
    cursor: str | None = Query(None, max_length=2000),
    limit: int = Query(20, ge=1, le=50),
):
    auth(r)
    with errors(), connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        return read_response(
            service().evidence_directory(
                c,
                scope(bid_id, package_id, revision_id, inventory_id),
                cursor=cursor,
                limit=limit,
            )
        )


@router.get("/rule-correction-evidence/{evidence_id}")
def evidence_detail(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    evidence_id: UUID,
    r: Request,
):
    auth(r)
    with errors(), connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        return read_response(
            service().evidence_detail(
                c, scope(bid_id, package_id, revision_id, inventory_id), str(evidence_id)
            )
        )
