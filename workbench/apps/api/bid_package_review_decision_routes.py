"""Human row dispositions and their separate immutable history."""

from contextlib import contextmanager
from uuid import UUID

import psycopg
from fastapi import APIRouter, Body, Query, Request

from apps.api.auth import auth
from apps.api.bid_package_review_input_routes import input_errors
from apps.api.identity_routes import saved
from packages.contracts.package_review_decisions_api import validate
from packages.domain import bid_package_review_decisions as service
from packages.domain.runtime import DomainError

router = APIRouter(tags=["bid-package-review-human-decisions"])
BASE = (
    "/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}"
    "/review-runs/{run_id}"
)
ROW_BASE = BASE + "/requirements/{requirement_id}/human-decisions"


@contextmanager
def decision_errors():
    with input_errors():
        try:
            yield
        except (psycopg.IntegrityError, psycopg.DataError) as error:
            raise DomainError(
                "PACKAGE_REVIEW_DECISION_REJECTED",
                "人工处置的原结果、引用或版本校验未通过，未保存更改",
                409,
            ) from error


@router.get(BASE + "/human-decisions")
def current_decisions(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    input_id: UUID,
    execution_input_id: UUID,
    run_id: UUID,
    r: Request,
):
    auth(r)
    with decision_errors():
        return service.current(
            tuple(map(str, (bid_id, package_id, revision_id, inventory_id))),
            str(input_id),
            str(execution_input_id),
            str(run_id),
        )


@router.post(ROW_BASE, status_code=201)
def save_decision(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    input_id: UUID,
    execution_input_id: UUID,
    run_id: UUID,
    requirement_id: UUID,
    r: Request,
    body: dict = Body(...),
):
    actor = auth(r, True)
    validate("SavePackageReviewHumanDecision", body)
    with decision_errors():
        value, replayed = service.save(
            str(actor["member_id"]),
            tuple(map(str, (bid_id, package_id, revision_id, inventory_id))),
            str(input_id),
            str(execution_input_id),
            str(run_id),
            str(requirement_id),
            r.headers.get("idempotency-key"),
            body,
        )
        return saved(value, replayed)


@router.get(ROW_BASE)
def history_decisions(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    input_id: UUID,
    execution_input_id: UUID,
    run_id: UUID,
    requirement_id: UUID,
    r: Request,
    limit: int = Query(default=20, ge=1, le=20),
    cursor: str | None = None,
):
    auth(r)
    with decision_errors():
        return service.history(
            tuple(map(str, (bid_id, package_id, revision_id, inventory_id))),
            str(input_id),
            str(execution_input_id),
            str(run_id),
            str(requirement_id),
            limit=limit,
            cursor=cursor,
        )
