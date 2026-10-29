"""Human package fact operations; every write authenticates intent, CSRF and exact scope."""

from contextlib import contextmanager
from uuid import UUID

import psycopg
from fastapi import APIRouter, Body, Query, Request

from apps.api.auth import auth
from apps.api.bid_package_review_input_routes import input_errors
from apps.api.identity_routes import saved
from packages.contracts.bid_package_requirements_api import validate
from packages.domain import bid_package_current_facts as current
from packages.domain import bid_package_fact_changes as changes
from packages.domain.runtime import DomainError

router = APIRouter(tags=["bid-package-fact-changes"])
BASE = "/{inventory_id}/frozen-review-inputs/{input_id}"


@contextmanager
def change_errors():
    with input_errors():
        try:
            yield
        except (psycopg.IntegrityError, psycopg.DataError) as error:
            raise DomainError(
                "PACKAGE_FACT_CHANGE_REJECTED", "事实操作校验未通过，未保存事实或回执", 409
            ) from error


def _scope(bid, package, revision, inventory):
    return tuple(map(str, (bid, package, revision, inventory)))


@router.post(BASE + "/fact-confirmations")
def confirm_fact(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    input_id: UUID,
    r: Request,
    body: dict = Body(...),
):
    actor = auth(r, True)
    validate("ConfirmPackageFact", body)
    with change_errors():
        value, replayed = changes.confirm(
            str(actor["member_id"]),
            _scope(bid_id, package_id, revision_id, inventory_id),
            str(input_id),
            r.headers.get("idempotency-key"),
            body,
        )
        return saved(value, replayed)


@router.post(BASE + "/fact-withdrawals")
def withdraw_fact(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    input_id: UUID,
    r: Request,
    body: dict = Body(...),
):
    actor = auth(r, True)
    validate("WithdrawPackageFact", body)
    with change_errors():
        value, replayed = changes.withdraw(
            str(actor["member_id"]),
            _scope(bid_id, package_id, revision_id, inventory_id),
            str(input_id),
            r.headers.get("idempotency-key"),
            body,
        )
        return saved(value, replayed)


@router.get(BASE + "/fact-changes/{command_id}")
def get_change(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    input_id: UUID,
    command_id: UUID,
    r: Request,
):
    auth(r)
    with change_errors():
        return changes.load(
            _scope(bid_id, package_id, revision_id, inventory_id), str(input_id), str(command_id)
        )


@router.get(BASE + "/fact-context")
def list_facts(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    input_id: UUID,
    r: Request,
    frozen_digest: str = Query(pattern="^[a-f0-9]{64}$"),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=4096),
):
    auth(r)
    with change_errors():
        return current.directory(
            _scope(bid_id, package_id, revision_id, inventory_id),
            str(input_id),
            frozen_digest,
            limit,
            cursor,
        )


@router.get(BASE + "/facts/{fact_id}")
def get_fact(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    input_id: UUID,
    fact_id: UUID,
    r: Request,
    frozen_digest: str = Query(pattern="^[a-f0-9]{64}$"),
):
    auth(r)
    with change_errors():
        return current.detail(
            _scope(bid_id, package_id, revision_id, inventory_id),
            str(input_id),
            frozen_digest,
            str(fact_id),
        )
