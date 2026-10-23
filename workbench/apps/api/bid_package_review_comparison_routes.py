"""Compare two explicitly selected completed package-scope runs, without provider IO."""

from uuid import UUID

from fastapi import APIRouter, Query, Request

from apps.api.auth import auth
from apps.api.bid_package_review_input_routes import input_errors
from packages.contracts.package_review_comparisons_api import BASE
from packages.domain import bid_package_review_comparisons as service

router = APIRouter(tags=["bid-package-review-comparisons"])


@router.get(BASE)
def compare_runs(
    bid_id: UUID,
    left_run_id: UUID,
    right_run_id: UUID,
    r: Request,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
):
    auth(r)
    with input_errors():
        return service.read(
            str(bid_id), str(left_run_id), str(right_run_id), limit=limit, cursor=cursor
        )
