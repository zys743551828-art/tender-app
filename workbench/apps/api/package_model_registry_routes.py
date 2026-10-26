"""Version-specific /3 registry; never creates a business route or certificate."""

from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from apps.api.auth import auth
from packages.domain.runtime import DomainError, connection
from packages.model_governance.common import GovernanceError
from packages.package_model_registry.application import Registry
from packages.package_model_registry.infrastructure import NativeTransactions

router = APIRouter(prefix="/api/v1/package-model-registry", tags=["package-model-registry"])


class Registration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_artifact_digest: str = Field(pattern="^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=4000)


def service():
    return Registry(NativeTransactions(connection))


def run(action):
    try:
        return action()
    except GovernanceError:
        raise DomainError("PACKAGE_MODEL_IDENTITY_INVALID", "模型身份或版本不匹配", 409) from None


@router.get("/training-jobs/{job_id}/preview")
def preview(job_id: UUID, request: Request):
    actor = auth(request)
    from packages.domain.review_identity import digest

    document = run(lambda: service().preview(job_id, actor["member_id"]))
    return {
        "document": document,
        "artifact_digest": digest(document),
        "formal_eligibility": "unavailable",
    }


@router.post("/training-jobs/{job_id}/registration")
def register(job_id: UUID, body: Registration, request: Request):
    actor = auth(request, True)
    return run(
        lambda: service().register(
            job_id,
            actor["member_id"],
            request.headers.get("idempotency-key"),
            body.reason,
            body.expected_artifact_digest,
        )
    )


@router.get("/models/{model_id}")
def read(model_id: UUID, request: Request):
    actor = auth(request)
    return run(lambda: service().read(model_id, actor["member_id"]))
