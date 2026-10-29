"""Fresh formal report views; no public object grants or stale cached Word artifacts."""

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from apps.api.auth import auth
from packages.domain.errors import DomainError
from packages.model_governance.common import GovernanceError
from packages.package_model_live.producer import Executor
from packages.package_prediction.application import Predictions
from packages.package_prediction_reports.application import Reports
from packages.package_prediction_reports.projection import MaterialProjection

router = APIRouter(
    prefix="/api/v1/bids/{bid_id}/technical-scopes/{scope_id}/formal-predictions/{command_id}",
    tags=["package prediction report"],
)


def render(request, bid, scope, command, format):
    actor = auth(request)
    configured = getattr(request.app.state, "package_prediction_service", None)
    if type(configured) is not Predictions or type(configured.executor) is not Executor:
        raise DomainError("PACKAGE_PREDICTION_REPORT_DISABLED", "正式报告消费者未配置", 503)
    service = Reports(
        configured.transactions,
        MaterialProjection(configured.executor.store, configured.executor.index),
    )
    try:
        return service.render(actor["member_id"], bid, scope, command, format)
    except GovernanceError:
        raise DomainError(
            "PACKAGE_PREDICTION_REPORT_INVALID", "报告来源、认证或展示设置已变化，请重新核验", 409
        ) from None


@router.get("/report")
def report(bid_id: UUID, scope_id: UUID, command_id: UUID, request: Request):
    return JSONResponse(
        render(request, bid_id, scope_id, command_id, "json"),
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/report.docx")
def word(bid_id: UUID, scope_id: UUID, command_id: UUID, request: Request):
    return Response(
        render(request, bid_id, scope_id, command_id, "docx"),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": 'attachment; filename="prediction-report.docx"',
        },
    )
