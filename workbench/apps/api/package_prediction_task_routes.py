"""Durable certified prediction requests, opaque progress and API publication."""

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from apps.api.auth import auth
from apps.api.package_prediction_routes import PackagePredictionRequest
from packages.domain.errors import DomainError
from packages.model_governance.common import GovernanceError
from packages.package_prediction_tasks.application import Jobs

router = APIRouter(
    prefix="/api/v1/bids/{bid_id}/technical-scopes/{scope_id}/prediction-tasks",
    tags=["durable prediction"],
)


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def service(request):
    result = getattr(request.app.state, "package_prediction_jobs", None)
    if type(result) is not Jobs:
        raise DomainError("PREDICTION_TASK_DISABLED", "持久预测执行器未配置", 503)
    return result


def call(action):
    try:
        return action()
    except GovernanceError:
        raise DomainError("PREDICTION_TASK_REJECTED", "固定预测任务身份或资格不符", 409) from None


@router.post("", status_code=202)
def submit(bid_id: UUID, scope_id: UUID, body: PackagePredictionRequest, request: Request):
    actor = auth(request, True)
    return call(
        lambda: service(request).submit(
            actor["member_id"], bid_id, scope_id, body.certificate_id, body.command_id
        )
    )


@router.get("/{command_id}")
def read(bid_id: UUID, scope_id: UUID, command_id: UUID, request: Request):
    actor = auth(request)
    return JSONResponse(
        call(lambda: service(request).read(actor["member_id"], bid_id, scope_id, command_id)),
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/{command_id}/advance")
def advance(bid_id: UUID, scope_id: UUID, command_id: UUID, request: Request, body: EmptyRequest):
    actor = auth(request, True)
    return call(lambda: service(request).advance(actor["member_id"], bid_id, scope_id, command_id))


@router.post("/{command_id}/cancel")
def cancel(bid_id: UUID, scope_id: UUID, command_id: UUID, request: Request, body: EmptyRequest):
    actor = auth(request, True)
    return call(lambda: service(request).cancel(actor["member_id"], bid_id, scope_id, command_id))
