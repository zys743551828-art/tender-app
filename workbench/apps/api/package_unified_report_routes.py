"""Synchronous unified report over an explicitly selected completed review."""

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from apps.api.auth import auth
from packages.domain.errors import DomainError
from packages.model_governance.common import GovernanceError
from packages.package_model_live.producer import Executor
from packages.package_prediction.application import Predictions
from packages.package_prediction.infrastructure import NativeTransactions
from packages.package_prediction_reports.projection import MaterialProjection
from packages.package_unified_reports.application import UnifiedReports
from packages.package_unified_reports.infrastructure import NativeUnifiedTransactions
from packages.package_unified_reports.projection import sections

router = APIRouter(
    prefix="/api/v1/bids/{bid_id}/technical-scopes/{scope_id}/formal-predictions/{command_id}",
    tags=["unified review report"],
)


def render(request, bid, scope, command, review, simulation, format):
    actor = auth(request)
    configured = getattr(request.app.state, "package_prediction_service", None)
    if (
        type(configured) is not Predictions
        or type(configured.executor) is not Executor
        or type(configured.transactions) is not NativeTransactions
    ):
        raise DomainError("UNIFIED_REPORT_DISABLED", "统一报告消费者未配置", 503)
    service = UnifiedReports(
        NativeUnifiedTransactions(configured.transactions.connections, bid),
        MaterialProjection(configured.executor.store, configured.executor.index),
    )
    try:
        return service.render(actor["member_id"], bid, scope, command, review, simulation, format)
    except GovernanceError:
        raise DomainError(
            "UNIFIED_REPORT_CHANGED", "统一报告身份、资格或原件已变化，请重新核验", 409
        ) from None


@router.get("/unified-report")
def report(
    bid_id: UUID,
    scope_id: UUID,
    command_id: UUID,
    review_id: UUID,
    request: Request,
    simulation_id: UUID | None = None,
):
    result = render(request, bid_id, scope_id, command_id, review_id, simulation_id, "json")
    return JSONResponse(
        result | {"sections": sections(result)}, headers={"Cache-Control": "private, no-store"}
    )


@router.get("/unified-report.docx")
def word(
    bid_id: UUID,
    scope_id: UUID,
    command_id: UUID,
    review_id: UUID,
    request: Request,
    simulation_id: UUID | None = None,
):
    return Response(
        render(request, bid_id, scope_id, command_id, review_id, simulation_id, "docx"),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": 'attachment; filename="unified-review-report.docx"',
        },
    )
