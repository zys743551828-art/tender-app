"""Explicit plan saving and immutable history; no execution or qualification endpoints."""

from contextlib import contextmanager
from uuid import UUID

import psycopg
from fastapi import APIRouter, Body, Depends, Query, Request

from apps.api.auth import auth
from apps.api.bid_package_review_input_routes import input_errors
from apps.api.dependency_body_limit import require_dependency_request_bytes
from apps.api.identity_routes import saved
from packages.contracts.bid_package_requirements_api import validate
from packages.domain import bid_package_dependency_plans as service
from packages.domain.bid_package_dependency_plan_directory import directory
from packages.domain.runtime import DomainError

router = APIRouter(tags=["bid-package-dependency-plans"])
BASE = "/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/dependency-plans"


@contextmanager
def plan_errors():
    with input_errors():
        try:
            yield
        except (psycopg.IntegrityError, psycopg.DataError) as error:
            raise DomainError(
                "PACKAGE_DEPENDENCY_PLAN_REJECTED", "计划保存校验未通过，未保存记录或回执", 409
            ) from error


@router.post(BASE, dependencies=[Depends(require_dependency_request_bytes)])
def save_plan(
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
    validate("SavePackageDependencyPlan", body)
    with plan_errors():
        value, replayed = service.save(
            str(actor["member_id"]),
            tuple(map(str, (bid_id, package_id, revision_id, inventory_id))),
            str(input_id),
            str(execution_input_id),
            r.headers.get("idempotency-key"),
            body,
        )
        return saved(value, replayed)


@router.get(BASE)
def list_plans(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    input_id: UUID,
    execution_input_id: UUID,
    r: Request,
    limit: int = Query(default=10, ge=1, le=20),
    cursor: str | None = None,
):
    auth(r)
    with plan_errors():
        return directory(
            tuple(map(str, (bid_id, package_id, revision_id, inventory_id))),
            str(input_id),
            str(execution_input_id),
            limit,
            cursor,
        )


@router.get(BASE + "/{plan_id}")
def get_plan(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    input_id: UUID,
    execution_input_id: UUID,
    plan_id: UUID,
    r: Request,
):
    auth(r)
    with plan_errors():
        return service.read(
            tuple(map(str, (bid_id, package_id, revision_id, inventory_id))),
            str(input_id),
            str(execution_input_id),
            str(plan_id),
        )
