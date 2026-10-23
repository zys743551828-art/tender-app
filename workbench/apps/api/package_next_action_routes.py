"""A selected run and expected immutable input are required; GET has no command effects."""

from uuid import UUID

from fastapi import APIRouter, Query, Request

from apps.api.auth import auth
from apps.api.work_context_routes import query, response
from packages.contracts.package_next_actions import PATH
from packages.work_contexts.next_actions import read

router = APIRouter(tags=["package-next-actions"])


@router.get(PATH)
def next_actions(
    bid_id: UUID,
    run_id: UUID,
    r: Request,
    expected_input_digest: str = Query(pattern="^[a-f0-9]{64}$"),
):
    auth(r)
    query(r, ("expected_input_digest",))
    return response(read(str(bid_id), str(run_id), expected_input_digest))
