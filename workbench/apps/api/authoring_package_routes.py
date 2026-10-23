"""Explicit generated-file adoption; no implicit current-body or review action."""

from uuid import UUID

from fastapi import APIRouter, Body, Request

from apps.api.auth import auth
from apps.api.bid_package_routes import package_errors
from apps.api.identity_routes import saved
from packages.authoring import package_adoptions

router = APIRouter(prefix="/api/v1", tags=["authoring package adoption"])


@router.post("/bids/{bid_id}/builds/{build_id}/package-adoptions")
def adopt_output(bid_id: UUID, build_id: UUID, r: Request, body: dict = Body(...)):
    actor = auth(r, True)
    with package_errors():
        response, replayed = package_adoptions.adopt(
            bid_id,
            build_id,
            actor["member_id"],
            r.headers.get("idempotency-key"),
            body,
            r.headers.get("if-match"),
            final_auth=lambda: auth(r, True)["member_id"],
        )
        return saved(response, replayed)
