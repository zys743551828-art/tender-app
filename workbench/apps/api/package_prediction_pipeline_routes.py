"""Observe/advance the existing project start intent; never accept a client certificate."""

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from apps.api.auth import auth
from apps.api.package_prediction_task_routes import EmptyRequest, call
from packages.domain.errors import DomainError
from packages.package_prediction_pipeline.application import Pipeline

router = APIRouter(
    prefix="/api/v1/bids/{bid_id}/technical-scopes/{scope_id}/prediction-pipeline",
    tags=["project prediction pipeline"],
)


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID


def service(request):
    value = getattr(request.app.state, "package_prediction_pipeline", None)
    if type(value) is not Pipeline:
        raise DomainError("PREDICTION_PIPELINE_DISABLED", "项目自动预测尚未配置", 503)
    return value


@router.get("")
def read(bid_id: UUID, scope_id: UUID, request: Request):
    actor = auth(request)
    return JSONResponse(
        call(lambda: service(request).read(actor["member_id"], bid_id, scope_id)),
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/advance")
def advance(bid_id: UUID, scope_id: UUID, request: Request, body: EmptyRequest):
    actor = auth(request, True)
    return call(lambda: service(request).advance(actor["member_id"], bid_id, scope_id))


@router.post("/cancel")
def cancel(bid_id: UUID, scope_id: UUID, request: Request, body: CancelRequest):
    actor = auth(request, True)
    return call(
        lambda: service(request).cancel(actor["member_id"], bid_id, scope_id, body.command_id)
    )
