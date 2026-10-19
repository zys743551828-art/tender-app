"""HTTP boundary for freezing and reading whole-package inputs; never launches jobs."""

from contextlib import contextmanager
from uuid import UUID

import psycopg
from fastapi import APIRouter, Body, Request

from apps.api.auth import auth
from apps.api.identity_routes import saved
from packages.contracts.bid_package_requirements_api import validate
from packages.domain import bid_package_requirement_repository as requirements
from packages.domain import bid_package_review_input_repository as repository
from packages.domain.bid_package_review_freezing import freeze
from packages.domain.bid_packages import PackageError
from packages.domain.runtime import DomainError, connection

router = APIRouter(tags=["bid-package-review-inputs"])


@contextmanager
def input_errors():
    try:
        yield
    except PackageError as error:
        status = (
            404
            if error.code.endswith("NOT_FOUND")
            else 500
            if error.code.endswith("CORRUPT")
            else 422
        )
        raise DomainError(
            error.code, "冻结输入不存在或与选定身份不一致", status, retryable=False
        ) from error
    except (psycopg.IntegrityError, psycopg.DataError) as error:
        if (error.diag.message_primary or "").startswith("review_freeze_"):
            raise DomainError(
                "PACKAGE_REVIEW_FREEZE_REJECTED",
                "冻结输入校验未通过，未保存记录或回执",
                409,
                retryable=False,
            ) from error
        raise requirements.storage_error(error) from error


@router.post("/{inventory_id}/frozen-review-inputs")
def freeze_review_input(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    r: Request,
    body: dict = Body(...),
):
    actor = auth(r, True)
    validate("FreezePackageReviewInput", body)
    with input_errors():
        stored, replayed = freeze(
            str(actor["member_id"]),
            (str(bid_id), str(package_id), str(revision_id), str(inventory_id)),
            r.headers.get("idempotency-key"),
            body,
        )
        return saved(stored, replayed)


@router.get("/{inventory_id}/frozen-review-inputs/{input_id}")
def get_frozen_review_input(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    input_id: UUID,
    r: Request,
):
    auth(r)
    with input_errors():
        with connection() as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            return repository.load(
                c,
                (str(bid_id), str(package_id), str(revision_id), str(inventory_id)),
                str(input_id),
            )
