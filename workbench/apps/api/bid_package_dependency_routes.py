"""Authenticated readonly dependency checks; no command, persistence or task dispatch."""

from uuid import UUID

from fastapi import APIRouter, Body, Depends, Request

from apps.api.auth import auth
from apps.api.bid_package_review_input_routes import input_errors
from apps.api.dependency_body_limit import require_dependency_request_bytes
from packages.domain.bid_package_input_dependencies import check

router = APIRouter(tags=["bid-package-input-dependencies"])


@router.post(
    "/{inventory_id}/frozen-review-inputs/{input_id}/execution-inputs/{execution_input_id}/dependency-check",
    dependencies=[Depends(require_dependency_request_bytes)],
)
def check_dependencies(
    bid_id: UUID,
    package_id: UUID,
    revision_id: UUID,
    inventory_id: UUID,
    input_id: UUID,
    execution_input_id: UUID,
    r: Request,
    body: dict = Body(...),
):
    auth(r, True)
    with input_errors():
        return check(
            tuple(map(str, (bid_id, package_id, revision_id, inventory_id))),
            str(input_id),
            str(execution_input_id),
            body,
        )
