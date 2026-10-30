"""Separate, opt-in TEST application. Never mounted by the business ASGI app."""

from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from apps.api.auth import auth
from packages.domain.errors import DomainError
from packages.model_governance.common import GovernanceError
from packages.prediction_sandbox.application import Sandbox


class Issue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    source_ref: str
    valid_until: str


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    certificate_id: UUID
    scope_id: UUID


class Revoke(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    reason: str


def create_app(sandbox=None):
    app = FastAPI(title="TEST ONLY prediction acceptance", docs_url=None, redoc_url=None)

    def service():
        if type(sandbox) is not Sandbox:
            raise DomainError("PREDICTION_SANDBOX_DISABLED", "测试执行器未配置", 503)
        return sandbox

    @app.exception_handler(DomainError)
    def domain_error(request, error):
        return JSONResponse({"code": error.code, "test_only": True}, status_code=error.status)

    @app.exception_handler(GovernanceError)
    def governance_error(request, error):
        return JSONResponse(
            {"code": "PREDICTION_SANDBOX_REJECTED", "test_only": True}, status_code=409
        )

    @app.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Prediction-Test-Only"] = "true"
        return response

    def identity(request, bid, scope, certificate, command, write):
        actor = auth(request, write)
        return {
            "actor": str(actor["member_id"]),
            "bid": str(bid),
            "scope": str(scope),
            "certificate": str(certificate),
            "command": str(command),
        }

    prefix = "/test-only/bids/{bid_id}"

    @app.post(prefix + "/certificates", status_code=201)
    def issue(bid_id: UUID, body: Issue, request: Request):
        actor = auth(request, True)
        return service().issue(
            actor["member_id"], bid_id, body.command_id, body.source_ref, body.valid_until
        )

    @app.post(prefix + "/certificates/{certificate_id}/revoke")
    def revoke(bid_id: UUID, certificate_id: UUID, body: Revoke, request: Request):
        actor = auth(request, True)
        return service().revoke(
            {
                "actor": str(actor["member_id"]),
                "bid": str(bid_id),
                "certificate": str(certificate_id),
            },
            body.command_id,
            body.reason,
        )

    @app.post(prefix + "/tasks", status_code=202)
    def submit(bid_id: UUID, body: Task, request: Request):
        return service().submit(
            identity(request, bid_id, body.scope_id, body.certificate_id, body.command_id, True)
        )

    @app.post(prefix + "/tasks/advance")
    def advance(bid_id: UUID, body: Task, request: Request):
        return service().advance(
            identity(request, bid_id, body.scope_id, body.certificate_id, body.command_id, True)
        )

    @app.post(prefix + "/tasks/cancel")
    def cancel(bid_id: UUID, body: Task, request: Request):
        return service().cancel(
            identity(request, bid_id, body.scope_id, body.certificate_id, body.command_id, True)
        )

    @app.get(prefix + "/tasks/{command_id}")
    def read(
        bid_id: UUID, command_id: UUID, scope_id: UUID, certificate_id: UUID, request: Request
    ):
        return service().read(
            identity(request, bid_id, scope_id, certificate_id, command_id, False)
        )

    return app
