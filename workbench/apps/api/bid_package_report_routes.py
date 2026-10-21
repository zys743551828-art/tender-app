"""Explicit historical report copies; no original-body adoption or scoring changes."""

from contextlib import contextmanager
from uuid import UUID

import psycopg
from fastapi import APIRouter, Body, Query, Request

from apps.api.auth import auth
from apps.api.bid_package_review_input_routes import input_errors
from apps.api.identity_routes import saved
from packages.contracts.package_review_reports_api import validate
from packages.domain import bid_package_reports as service
from packages.domain.runtime import DomainError

router = APIRouter(tags=["bid-package-reports"])
BASE = "/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/review-runs/{run_id}"


@contextmanager
def report_errors():
    with input_errors():
        try:
            yield
        except (psycopg.IntegrityError, psycopg.DataError) as error:
            raise DomainError(
                "PACKAGE_REPORT_REQUEST_REJECTED", "报告申请的冻结依据或事务回执校验未通过", 409
            ) from error


@router.get(BASE + "/report-context")
def report_context(
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
    with report_errors():
        return service.read_context(
            tuple(map(str, (bid_id, package_id, revision_id, inventory_id))),
            str(input_id),
            str(execution_input_id),
            str(run_id),
        )


@router.post(BASE + "/report-exports", status_code=202)
def start_report(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    input_id: UUID,
    execution_input_id: UUID,
    run_id: UUID,
    r: Request,
    body: dict = Body(...),
):
    actor = auth(r, True)
    validate("StartPackageReviewReport", body)
    with report_errors():
        value, replayed = service.start(
            str(actor["member_id"]),
            tuple(map(str, (bid_id, package_id, revision_id, inventory_id))),
            str(input_id),
            str(execution_input_id),
            str(run_id),
            r.headers.get("idempotency-key"),
            body,
        )
        return saved(value, replayed)


@router.get(BASE + "/report-exports")
def list_reports(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    input_id: UUID,
    execution_input_id: UUID,
    run_id: UUID,
    r: Request,
    limit: int = Query(default=10, ge=1, le=50),
    cursor: str | None = None,
):
    auth(r)
    with report_errors():
        return service.directory(
            tuple(map(str, (bid_id, package_id, revision_id, inventory_id))),
            str(input_id),
            str(execution_input_id),
            str(run_id),
            limit=limit,
            cursor=cursor,
        )


@router.get(BASE + "/report-exports/{export_id}")
def get_report(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    input_id: UUID,
    execution_input_id: UUID,
    run_id: UUID,
    export_id: UUID,
    r: Request,
):
    auth(r)
    with report_errors():
        return service.read(
            tuple(map(str, (bid_id, package_id, revision_id, inventory_id))),
            str(input_id),
            str(execution_input_id),
            str(run_id),
            str(export_id),
        )
