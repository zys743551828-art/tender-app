"""Immutable rule projections and explicit human scope declarations.

The error boundary includes connection exit: deferred COMMIT rejection must never
return a successful ACK or become the generic retryable database 503.
"""

from contextlib import contextmanager
from uuid import UUID

import psycopg
from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse

from apps.api.auth import auth
from apps.api.bid_package_dependency_plan_routes import router as dependency_plan_router
from apps.api.bid_package_dependency_routes import router as dependency_router
from apps.api.bid_package_fact_change_routes import router as fact_change_router
from apps.api.bid_package_fact_scope_routes import router as fact_scope_router
from apps.api.bid_package_review_input_routes import router as input_router
from apps.api.identity_routes import saved
from packages.contracts.bid_package_requirements_api import validate
from packages.domain import bid_package_requirement_repository as repository
from packages.domain.bid_package_service import historical, lock_bid
from packages.domain.bid_packages import PackageError
from packages.domain.runtime import Command, DomainError, connection, etag, require_read_committed

router = APIRouter(
    prefix="/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}/requirement-inventories",
    tags=["bid-package-requirements"],
)
router.include_router(input_router)
router.include_router(fact_scope_router)
router.include_router(fact_change_router)
router.include_router(dependency_router)
router.include_router(dependency_plan_router)


@contextmanager
def requirement_errors():
    try:
        yield
    except PackageError as error:
        status = 422
        if error.code.endswith("NOT_FOUND"):
            status = 404
        elif error.code.endswith("CORRUPT"):
            status = 500
        elif error.code.endswith("CAS_MISMATCH"):
            status = 412
        elif any(
            word in error.code
            for word in ("STALE", "SOURCE_NOT_EFFECTIVE", "SOURCE_UNPROVEN", "NOT_CONFIRMED")
        ):
            status = 409
        raise DomainError(
            error.code,
            "要求清单或人工核验范围与冻结依据不一致，请核对后操作",
            status,
            retryable=False,
        ) from error
    except (psycopg.IntegrityError, psycopg.DataError) as error:
        raise repository.storage_error(error) from error


def tag(target: str, value: str):
    return etag("requirement-inventory", target, value)


def command(c, r, actor, kind, target, body, scope, condition=None):
    require_read_committed(c)
    return Command(
        c,
        actor["member_id"],
        kind,
        UUID(target),
        r.headers.get("idempotency-key"),
        {"scope": scope, "body": body},
        condition,
    )


@router.post("")
def create_inventory(
    bid_id: UUID, package_id: UUID, revision_id: UUID, r: Request, body: dict = Body(...)
):
    actor = auth(r, True)
    validate("CreatePackageRequirementInventory", body)
    first = r.headers.get("if-none-match")
    expected = r.headers.get("if-match")
    if not first and not expected:
        raise DomainError(
            "PRECONDITION_REQUIRED", "首版请用If-None-Match:*，后续请核对清单当前ETag", 428
        )
    if (first and expected) or (first and first != "*"):
        raise DomainError("INVALID_REQUEST", "清单前置条件必须明确选择首版或当前修订", 422)
    bid, package, target = map(str, (bid_id, package_id, revision_id))
    with requirement_errors():
        with connection() as c:
            lock_bid(c, bid)
            historical(c, bid, package, target)
            cmd = command(
                c,
                r,
                actor,
                "create_package_requirement_inventory",
                target,
                body,
                [bid, package, target],
                {"if_match": expected, "if_none_match": first},
            )
            if cmd.replay:
                return saved(cmd.replay, True)
            current = repository.head(c, target, lock=True)
            if (first and current) or (
                expected and (not current or expected != tag(target, current["digest"]))
            ):
                raise DomainError(
                    "REVISION_CONFLICT", "要求清单已有变化，请保留选择并核对当前清单", 412
                )
            value = repository.create_inventory(
                c,
                bid,
                package,
                target,
                body | {"actor_id": str(actor["member_id"])},
                expected_digest=current["digest"] if current else None,
            )
            return saved(cmd.finish(value, 201, {"ETag": tag(target, value["digest"])}))


@router.get("")
def list_inventories(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    r: Request,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
):
    auth(r)
    bid, package, target = map(str, (bid_id, package_id, revision_id))
    with requirement_errors():
        with connection() as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            value = repository.directory(c, bid, package, target, limit=limit, cursor=cursor)
            current = repository.head(c, target)
            return JSONResponse(
                value, headers={"ETag": tag(target, current["digest"])} if current else {}
            )


@router.get("/{inventory_id}")
def get_inventory(
    bid_id: UUID, package_id: UUID, revision_id: UUID, inventory_id: UUID, r: Request
):
    auth(r)
    with requirement_errors():
        with connection() as c:
            value = repository.load_inventory(
                c, *map(str, (bid_id, package_id, revision_id, inventory_id))
            )
            return JSONResponse(value, headers={"ETag": tag(str(revision_id), value["digest"])})


@router.post("/{inventory_id}/coverage-attempts")
def create_attempt(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    r: Request,
    body: dict = Body(...),
):
    actor = auth(r, True)
    validate("CreatePackageCoverageAttempt", body)
    bid, package, target, inventory = map(str, (bid_id, package_id, revision_id, inventory_id))
    with requirement_errors():
        with connection() as c:
            lock_bid(c, bid)
            repository.load_inventory(c, bid, package, target, inventory)
            cmd = command(
                c,
                r,
                actor,
                "create_package_coverage_attempt",
                inventory,
                body,
                [bid, package, target, inventory],
            )
            if cmd.replay:
                return saved(cmd.replay, True)
            value = repository.create_attempt(
                c, bid, package, target, inventory, body | {"actor_id": str(actor["member_id"])}
            )
            return saved(cmd.finish(value, 201))


@router.get("/{inventory_id}/coverage-attempts")
def list_attempts(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    r: Request,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
):
    auth(r)
    with requirement_errors():
        with connection() as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            return repository.directory(
                c,
                *map(str, (bid_id, package_id, revision_id)),
                inventory_id=str(inventory_id),
                limit=limit,
                cursor=cursor,
            )


@router.get("/{inventory_id}/coverage-attempts/{attempt_id}")
def get_attempt(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    attempt_id: UUID,
    r: Request,
):
    auth(r)
    with requirement_errors():
        with connection() as c:
            return repository.load_attempt(
                c, *map(str, (bid_id, package_id, revision_id, inventory_id, attempt_id))
            )


@router.post("/{inventory_id}/review-input-preview")
def preview_review_input(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    r: Request,
    body: dict = Body(...),
):
    from packages.domain.bid_package_review_preview import preview

    auth(r, True)
    validate("PackageReviewInputPreviewRequest", body)
    with requirement_errors():
        with connection() as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            return preview(
                c, str(bid_id), str(package_id), str(revision_id), str(inventory_id), body
            )


@router.post("/{inventory_id}/review-original-verification")
def verify_review_originals(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    r: Request,
    body: dict = Body(...),
):
    from packages.domain.bid_package_original_verification import verify

    auth(r, True)
    validate("PackageReviewOriginalVerificationRequest", body)
    with requirement_errors():
        return verify(str(bid_id), str(package_id), str(revision_id), str(inventory_id), body)
