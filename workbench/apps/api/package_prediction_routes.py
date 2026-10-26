"""Explicit certified /3 consumption; legacy single-body scoring stays independent."""

from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from apps.api.auth import auth
from packages.domain.runtime import DomainError, connection
from packages.model_governance.common import GovernanceError
from packages.package_prediction.application import Predictions
from packages.package_prediction.infrastructure import NativeTransactions

router = APIRouter(
    prefix="/api/v1/bids/{bid_id}/technical-scopes/{scope_id}/formal-predictions",
    tags=["package formal prediction"],
)


class PackagePredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    certificate_id: UUID
    command_id: UUID


def run(action):
    try:
        return action()
    except GovernanceError:
        raise DomainError(
            "PACKAGE_PREDICTION_INVALID", "预测材料、方法或认证不满足要求", 409
        ) from None


@router.post("")
def execute(bid_id: UUID, scope_id: UUID, body: PackagePredictionRequest, request: Request):
    actor = auth(request, True)
    service = getattr(request.app.state, "package_prediction_service", None)
    if type(service) is not Predictions or service.executor is None:
        raise DomainError("PACKAGE_PREDICTION_DISABLED", "正式预测消费者未配置", 503)
    return run(
        lambda: service.execute(
            actor["member_id"], bid_id, scope_id, body.certificate_id, body.command_id
        )
    )


@router.get("/{command_id}")
def read(bid_id: UUID, scope_id: UUID, command_id: UUID, request: Request):
    actor = auth(request)
    result = run(
        lambda: Predictions(NativeTransactions(connection)).read(
            actor["member_id"], bid_id, scope_id, command_id
        )
    )
    if result is None:
        raise DomainError("PACKAGE_PREDICTION_NOT_FOUND", "尚无此预测回执，可用同一请求恢复", 404)
    return result
