"""Business mirror endpoints: host-injected capability, no client purpose flag."""

from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from apps.api.auth import auth
from packages.domain.runtime import DomainError, connection
from packages.model_governance.common import GovernanceError
from packages.package_model_live.application import Service
from packages.package_model_live.infrastructure import NativeTransactions

router = APIRouter(prefix="/api/v1/package-business-shadow", tags=["package-business-shadow"])


class BusinessEvidenceFreeze(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    expected_protocol_digest: str = Field(pattern="^[a-f0-9]{64}$")


class BusinessShadowCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: dict


def run(action):
    try:
        return action()
    except GovernanceError:
        raise DomainError("BUSINESS_SHADOW_INVALID", "业务镜像版本或来源不匹配", 409) from None


@router.post("/models/{model_id}/evidence-binding")
def freeze(model_id: UUID, body: BusinessEvidenceFreeze, request: Request):
    actor = auth(request, True)
    service = Service(NativeTransactions(connection), None)
    return run(
        lambda: service.freeze(
            actor["member_id"], model_id, body.expected_protocol_digest, str(body.command_id)
        )
    )


@router.post("/actions")
def execute(body: BusinessShadowCommand, request: Request):
    actor = auth(request, True)
    service = getattr(request.app.state, "business_shadow_service", None)
    if type(service) is not Service or service.enabled is not True:
        raise DomainError("BUSINESS_SHADOW_DISABLED", "业务镜像未启用", 503)
    return run(lambda: service.execute(actor["member_id"], body.command))
