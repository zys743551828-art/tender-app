"""Explicit human fact applicability declarations; never task or qualification requests."""

from contextlib import contextmanager
from uuid import UUID

import psycopg
from fastapi import APIRouter, Body, Request

from apps.api.auth import auth
from apps.api.bid_package_review_input_routes import input_errors
from apps.api.identity_routes import saved
from packages.contracts.bid_package_requirements_api import validate
from packages.domain import bid_package_fact_scope_repository as repository
from packages.domain import bid_package_fact_scopes as service
from packages.domain.bid_package_fact_scope_observation import inspect
from packages.domain.runtime import DomainError, connection

router = APIRouter(tags=["bid-package-fact-scopes"])
BASE = "/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}"


@contextmanager
def scope_errors():
    try:
        with input_errors():
            try:
                yield
            except (psycopg.IntegrityError, psycopg.DataError) as error:
                # Includes deferred COMMIT failure; no successful ACK escapes first.
                raise DomainError(
                    "PACKAGE_FACT_SCOPE_REJECTED", "事实范围校验未通过，未保存记录或回执", 409
                ) from error
    except ValueError as error:
        raise DomainError(
            "PACKAGE_FACT_SCOPE_UNPROVEN", "事实、依据或主体范围已变化，请重读后核对", 409
        ) from error


@router.post(BASE + "/fact-scope-declarations")
def change_fact_scope(
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
    validate("ChangePackageFactScope", body)
    with scope_errors():
        value, replayed = service.save(
            str(actor["member_id"]),
            (str(bid_id), str(package_id), str(revision_id), str(inventory_id)),
            str(input_id),
            str(execution_input_id),
            r.headers.get("idempotency-key"),
            body,
        )
        return saved(value, replayed)


@router.get(BASE + "/fact-scope-declarations/{declaration_id}")
def read_fact_scope(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    input_id: UUID,
    execution_input_id: UUID,
    declaration_id: UUID,
    r: Request,
):
    auth(r)
    with scope_errors():
        with connection() as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            return repository.load(
                c,
                (str(bid_id), str(package_id), str(revision_id), str(inventory_id)),
                str(input_id),
                str(execution_input_id),
                str(declaration_id),
            )


@router.get(BASE + "/facts/{fact_id}/scope-declaration")
def observe_fact_scope(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    input_id: UUID,
    execution_input_id: UUID,
    fact_id: UUID,
    r: Request,
):
    auth(r)
    with scope_errors():
        return inspect(
            (str(bid_id), str(package_id), str(revision_id), str(inventory_id)),
            str(input_id),
            str(execution_input_id),
            str(fact_id),
        )
