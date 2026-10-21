"""Explicit launch and historical run/report reads for declared package scope."""

from contextlib import contextmanager
from uuid import UUID

import psycopg
from fastapi import APIRouter, Body, Query, Request

from apps.api.auth import auth
from apps.api.bid_package_review_input_routes import input_errors
from apps.api.identity_routes import saved
from packages.contracts.package_review_runs_api import validate
from packages.domain import bid_package_review_runs as service
from packages.domain.runtime import DomainError

router = APIRouter(tags=["bid-package-review-runs"])
BASE = "/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/review-runs"


@contextmanager
def run_errors():
    with input_errors():
        try:
            yield
        except (psycopg.IntegrityError, psycopg.DataError) as error:
            raise DomainError(
                "PACKAGE_REVIEW_RUN_REJECTED", "核查任务校验未通过，未保存任务或启动回执", 409
            ) from error


@router.post(BASE, status_code=202)
def start_run(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    input_id: UUID,
    execution_input_id: UUID,
    r: Request,
    body: dict = Body(...),
):
    actor = auth(r, True)
    validate("StartPackageReviewRun", body)
    with run_errors():
        value, replayed = service.start(
            str(actor["member_id"]),
            tuple(map(str, (bid_id, package_id, revision_id, inventory_id))),
            str(input_id),
            str(execution_input_id),
            r.headers.get("idempotency-key"),
            body,
        )
        return saved(value, replayed)


@router.get(BASE)
def list_runs(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    input_id: UUID,
    execution_input_id: UUID,
    r: Request,
    limit: int = Query(default=10, ge=1, le=100),
    cursor: str | None = None,
):
    auth(r)
    with run_errors():
        return service.directory(
            tuple(map(str, (bid_id, package_id, revision_id, inventory_id))),
            str(input_id),
            str(execution_input_id),
            limit,
            cursor,
        )


@router.get(BASE + "/{run_id}")
def get_run(
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
    with run_errors():
        return service.read(
            tuple(map(str, (bid_id, package_id, revision_id, inventory_id))),
            str(input_id),
            str(execution_input_id),
            str(run_id),
        )


@router.get(BASE + "/{run_id}/input")
def get_run_input(
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
    with run_errors():
        return service.read_input(
            tuple(map(str, (bid_id, package_id, revision_id, inventory_id))),
            str(input_id),
            str(execution_input_id),
            str(run_id),
        )
