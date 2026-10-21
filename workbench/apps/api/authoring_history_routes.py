"""Opt-in exact chapter history GET; existing restore commands remain unchanged."""

from uuid import UUID

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse

from apps.api.auth import auth
from packages.authoring_history import service
from packages.contracts.authoring_history_api import PATH
from packages.domain.runtime import DomainError

router = APIRouter(tags=["authoring-history"])


@router.get(PATH)
def historical_section(
    bid_id: UUID,
    draft_id: UUID,
    section_id: UUID,
    r: Request,
    revision: int = Path(..., ge=1, le=2**63 - 1),
    expected_digest: str = Query(..., pattern="^[a-f0-9]{64}$"),
):
    auth(r)
    if (
        set(r.query_params) != {"expected_digest"}
        or len(r.query_params.getlist("expected_digest")) != 1
    ):
        raise DomainError(
            "AUTHORING_HISTORY_INVALID_REQUEST", "历史章节读取只接受单个明确的预期正文摘要", 422
        )
    return JSONResponse(
        service.resolve(
            str(bid_id), str(draft_id), str(section_id), revision, expected_digest=expected_digest
        ),
        headers={"Cache-Control": "private, no-store", "Vary": "Cookie"},
    )
