"""Whole-bid immutable package storage API; no review or paid execution implied."""

from contextlib import contextmanager
from uuid import UUID

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse, Response

from apps.api.auth import auth
from apps.api.identity_routes import command, saved
from packages.contracts.bid_package_api import validate
from packages.domain import bid_package_service as service
from packages.domain.bid_packages import PackageError
from packages.domain.runtime import DomainError, connection

router = APIRouter(prefix="/api/v1/bids/{bid_id}/packages", tags=["bid-packages"])


@contextmanager
def package_errors():
    try:
        yield
    except PackageError as error:
        status = 404 if error.code.endswith("NOT_FOUND") else 422
        if error.code.endswith("CORRUPT"):
            status = 500
        if error.code in {"PACKAGE_PROFILE_SCOPE_MISMATCH", "PACKAGE_STORAGE_CONSTRAINT_REJECTED"}:
            status = 409
        if error.code == "PACKAGE_CAS_MISMATCH":
            status = 412
        raise DomainError(
            error.code, "资料包操作未完成，请核对资料、范围或修订状态", status
        ) from error


@router.post("")
def create_package(bid_id: UUID, r: Request, body: dict = Body(...)):
    actor = auth(r, True)
    validate("CreateBidPackage", body)
    with package_errors(), connection() as c:
        service.lock_bid(c, bid_id)
        cmd = command(c, r, actor, "create_bid_package", bid_id, body)
        if cmd.replay:
            return saved(cmd.replay, True)
        package = service.create_revision(c, bid_id, body)
        return saved(cmd.finish(service.view(c, package), 201, {"ETag": service.head_tag(package)}))


@router.get("/{package_id}")
def get_head(bid_id: UUID, package_id: UUID, r: Request):
    auth(r)
    with package_errors(), connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        package = service.head(c, bid_id, package_id)
        return JSONResponse(service.view(c, package), headers={"ETag": service.head_tag(package)})


@router.post("/{package_id}/revisions")
def append_revision(bid_id: UUID, package_id: UUID, r: Request, body: dict = Body(...)):
    actor = auth(r, True)
    validate("AppendBidPackage", body)
    if not r.headers.get("if-match"):
        raise DomainError("PRECONDITION_REQUIRED", "请先读取资料包当前修订", 428)
    with package_errors(), connection() as c:
        service.lock_bid(c, bid_id)
        cmd = command(
            c, r, actor, "append_bid_package", package_id, {"bid_id": str(bid_id), **body}, True
        )
        if cmd.replay:
            return saved(cmd.replay, True)
        previous = service.head(c, bid_id, package_id)
        if r.headers["if-match"] != service.head_tag(previous):
            raise DomainError("REVISION_CONFLICT", "资料包已有新修订，请读取后核对", 412)
        package = service.create_revision(c, bid_id, body, previous)
        return saved(cmd.finish(service.view(c, package), 201, {"ETag": service.head_tag(package)}))


@router.get("/{package_id}/revisions/{revision_id}")
def get_revision(bid_id: UUID, package_id: UUID, revision_id: UUID, r: Request):
    auth(r)
    with package_errors(), connection() as c:
        package = service.historical(c, bid_id, package_id, revision_id)
        return service.view(c, package)


@router.get("/{package_id}/revisions/{revision_id}/manifest")
def get_manifest(bid_id: UUID, package_id: UUID, revision_id: UUID, r: Request):
    auth(r)
    with package_errors(), connection() as c:
        raw, digest = service.manifest_bytes(c, bid_id, package_id, revision_id)
        return Response(
            raw,
            media_type="application/json",
            headers={
                "ETag": f'"sha256:{digest}"',
                "X-Manifest-SHA256": digest,
            },
        )
