"""Current local tariff quote; never queues work or makes a provider call."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from apps.api.auth import auth
from packages.assistant.generation_batch_contracts import MAX_MINOR
from packages.authoring import package_fee_quote
from packages.domain.runtime import connection
from packages.tasks import templates

router = APIRouter(prefix="/api/v1", tags=["task templates"])
PATH = "/bids/{bid_id}/task-definitions/{definition_id}/authoring-fee-quote"


class AuthoringFeeQuoteView(BaseModel):
    protocol: Literal["exact-authoring-fee-quote/1"]
    bid_id: UUID
    definition_id: UUID
    definition_version_id: UUID
    template_etag: str
    price_version_id: UUID
    currency: Literal["CNY", "USD"]
    amount_scale: Literal[1000000000]
    reserved_minor: int = Field(ge=0, le=MAX_MINOR)
    valid_until: datetime
    estimate_not_provider_spend_cap: Literal[True]


@router.get(
    PATH,
    response_model=AuthoringFeeQuoteView,
    operation_id="getExactAuthoringFeeQuote",
    openapi_extra={"security": [{"SessionCookie": []}]},
)
def authoring_fee_quote(
    bid_id: UUID, definition_id: UUID, r: Request, response: Response
) -> AuthoringFeeQuoteView:
    auth(r)
    response.headers["Cache-Control"] = "private,no-store"
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        row = templates.current(c, bid_id, definition_id)
        return AuthoringFeeQuoteView.model_validate(package_fee_quote.quote(c, row))
