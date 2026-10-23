"""Current exact-package technical scope declarations; no model execution route."""

from uuid import UUID

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from apps.api.auth import auth
from apps.api.bid_package_requirement_routes import requirement_errors
from apps.api.identity_routes import saved
from packages.contracts import package_technical_scope_api as contracts
from packages.domain.runtime import clean, connection, etag

BASE = "/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}"
router = APIRouter(prefix=BASE, tags=["package-technical-scopes"])


def service():
    from packages.domain import bid_package_technical_scope_service

    return bid_package_technical_scope_service


def _scope(bid, package, revision):
    return tuple(map(str, (bid, package, revision)))


def _response(value, tag=None):
    headers = {"Cache-Control": "private, no-store"}
    if tag is not None:
        headers["ETag"] = tag
    return JSONResponse(clean(value), headers=headers)


@router.get("/technical-scope-context")
def context(
    bid_id: UUID, package_id: UUID, revision_id: UUID, r: Request, inventory_id: UUID = Query(...)
):
    auth(r)
    with requirement_errors(), connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        value = service().context(c, _scope(bid_id, package_id, revision_id), str(inventory_id))
        return _response(value, value["etag"])


@router.post("/technical-scope-previews")
def preview(bid_id: UUID, package_id: UUID, revision_id: UUID, r: Request, body: dict = Body(...)):
    auth(r, True)
    contracts.validate("PackageTechnicalScopeRequest", body)
    with requirement_errors(), connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        value = service().preview(c, _scope(bid_id, package_id, revision_id), body)
        return _response(value, service().preview_etag(value))


@router.post("/technical-scopes", status_code=201)
async def freeze(
    bid_id: UUID, package_id: UUID, revision_id: UUID, r: Request, body: dict = Body(...)
):
    actor = await run_in_threadpool(auth, r, True)
    contracts.validate("FreezePackageTechnicalScope", body)
    with requirement_errors():
        result, replay = await run_in_threadpool(
            service().freeze,
            _scope(bid_id, package_id, revision_id),
            actor["member_id"],
            r.headers.get("idempotency-key"),
            body,
            r.headers.get("if-match"),
            final_auth=lambda: auth(r, True)["member_id"],
        )
        return saved(result, replay)


@router.get("/technical-scopes")
def history(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    r: Request,
    cursor: str | None = Query(None, max_length=2000),
    limit: int = Query(20, ge=1, le=50),
):
    auth(r)
    with requirement_errors(), connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        return _response(
            service().history(c, _scope(bid_id, package_id, revision_id), cursor, limit)
        )


@router.get("/technical-scopes/{scope_id}")
def detail(bid_id: UUID, package_id: UUID, revision_id: UUID, scope_id: UUID, r: Request):
    auth(r)
    with requirement_errors(), connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        value = service().load(c, _scope(bid_id, package_id, revision_id), str(scope_id))
        return _response(value, etag("package-technical-scope", str(scope_id), value["digest"]))
