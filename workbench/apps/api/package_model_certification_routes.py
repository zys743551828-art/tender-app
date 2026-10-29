"""Certificate lifecycle; clients supply IDs, never evidence or verified flags."""

from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from apps.api.auth import auth
from packages.domain.runtime import DomainError, connection
from packages.model_governance.common import GovernanceError
from packages.package_model_certification.application import Certificates
from packages.package_model_certification.infrastructure import NativeTransactions

router = APIRouter(
    prefix="/api/v1/package-model-certification", tags=["package-model-certification"]
)


class PackageCertificateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shadow_event_id: UUID
    rollback_event_id: UUID
    valid_until: str
    reason: str = Field(min_length=1, max_length=4000)


class PackageCertificateIssueRequest(PackageCertificateRequest):
    expected_source_digest: str = Field(pattern="^[a-f0-9]{64}$")


class PackageCertificateRevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=4000)


def service():
    return Certificates(NativeTransactions(connection))


def execute(action):
    try:
        return action()
    except GovernanceError:
        raise DomainError(
            "PACKAGE_CERTIFICATION_INVALID", "认证绑定、门槛或有效期不满足", 409
        ) from None


@router.post("/models/{model_id}/preview")
def preview(model_id: UUID, body: PackageCertificateRequest, request: Request):
    actor = auth(request, True)
    return execute(
        lambda: service().preview(actor["member_id"], model_id, body.model_dump(mode="json"))
    )


@router.post("/models/{model_id}/certificates")
def issue(model_id: UUID, body: PackageCertificateIssueRequest, request: Request):
    actor = auth(request, True)
    return execute(
        lambda: service().issue(
            actor["member_id"],
            model_id,
            body.model_dump(mode="json", exclude={"expected_source_digest"}),
            request.headers.get("idempotency-key"),
            body.expected_source_digest,
        )
    )


@router.get("/certificates/{certificate_id}")
def read(certificate_id: UUID, request: Request):
    actor = auth(request)
    return execute(lambda: service().read(actor["member_id"], certificate_id))


@router.post("/certificates/{certificate_id}/revoke")
def revoke(certificate_id: UUID, body: PackageCertificateRevokeRequest, request: Request):
    actor = auth(request, True)
    return execute(
        lambda: service().revoke(
            actor["member_id"], certificate_id, request.headers.get("idempotency-key"), body.reason
        )
    )
