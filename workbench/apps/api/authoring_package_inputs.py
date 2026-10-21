"""Optional exact authoring input API. No dispatch, apply, or build endpoint."""

from contextlib import contextmanager
from uuid import UUID

import psycopg
from fastapi import APIRouter, Query, Request

from apps.api.auth import auth
from apps.api.identity_routes import saved
from packages.authoring import package_input as service
from packages.authoring import package_input_contracts as models
from packages.authoring import package_input_repository as repository
from packages.domain.bid_packages import PackageError
from packages.domain.runtime import DomainError, connection

router = APIRouter(prefix="/api/v1", tags=["authoring-package-inputs"])


@contextmanager
def errors():
    try:
        yield
    except PackageError as error:
        raise DomainError(
            error.code,
            "固定整包记录与明确选择不一致",
            404 if error.code.endswith("NOT_FOUND") else 409,
        ) from error
    except (psycopg.IntegrityError, psycopg.DataError) as error:
        if (error.diag.message_primary or "").startswith("authoring_package_"):
            raise DomainError(
                "AUTHORING_PACKAGE_INPUT_REJECTED", "固定编写输入约束未通过，未保存半份记录", 409
            ) from error
        raise


@router.get(
    "/authoring/package-input-capabilities", response_model=models.PackageAuthoringInputCapabilities
)
def capabilities(r: Request):
    auth(r)
    with connection() as c:
        return repository.capabilities(c)


@router.post(
    "/bids/{bid_id}/authoring/package-inputs",
    response_model=models.PackageAuthoringInputView,
    status_code=201,
)
def create(bid_id: UUID, r: Request, body: models.PackageAuthoringInputRequest):
    actor = auth(r, True)
    with errors():
        result, replayed = service.save(
            actor["member_id"],
            bid_id,
            r.headers.get("idempotency-key"),
            body.model_dump(mode="json"),
            final_auth=lambda: auth(r, True),
        )
        return saved(result, replayed)


@router.get(
    "/bids/{bid_id}/authoring/package-inputs", response_model=models.PackageAuthoringInputPage
)
def directory(
    bid_id: UUID,
    r: Request,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
):
    auth(r)
    with errors(), connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return repository.directory(c, bid_id, limit=limit, cursor=cursor)


@router.get(
    "/bids/{bid_id}/authoring/package-inputs/{input_id}",
    response_model=models.PackageAuthoringInputView,
)
def get(bid_id: UUID, input_id: UUID, r: Request):
    auth(r)
    with errors(), connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return repository.view(repository.load(c, bid_id, input_id))


@router.get(
    "/bids/{bid_id}/authoring/package-inputs/{input_id}/context",
    response_model=models.PackageAuthoringInputContext,
)
def context(bid_id: UUID, input_id: UUID, r: Request):
    auth(r)
    with errors(), connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return repository.public_context(repository.load(c, bid_id, input_id))


@router.post(
    "/bids/{bid_id}/authoring/package-inputs/{input_id}/check",
    response_model=models.PackageAuthoringInputStatus,
)
def check(bid_id: UUID, input_id: UUID, r: Request, body: models.PackageAuthoringInputCheck):
    auth(r, True)
    with errors():
        return service.status(bid_id, input_id, body.input_digest)


@router.post(
    "/bids/{bid_id}/authoring/package-inputs/{input_id}/fact-withdrawals",
    response_model=models.PackageAuthoringFactScopeView,
    status_code=201,
)
def withdraw(bid_id: UUID, input_id: UUID, r: Request, body: models.PackageAuthoringFactWithdrawal):
    actor = auth(r, True)
    with errors():
        result, replayed = service.withdraw(
            actor["member_id"],
            bid_id,
            input_id,
            r.headers.get("idempotency-key"),
            body.model_dump(mode="json"),
        )
        return saved(result, replayed)
