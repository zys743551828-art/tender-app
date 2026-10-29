"""/3 protocol and native final-report admission evidence; no client metrics accepted."""

from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from apps.api.auth import auth
from packages.domain.runtime import DomainError, connection
from packages.model_governance.common import GovernanceError
from packages.package_model_admission.application import Admission
from packages.package_model_admission.infrastructure import NativeTransactions

router = APIRouter(prefix="/api/v1/package-model-admission", tags=["package-model-admission"])


class PackageAdmissionFreezeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document: dict
    reason: str = Field(min_length=1, max_length=4000)


class PackageAdmissionReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evaluation_job_id: UUID
    expected_packet_digest: str = Field(pattern="^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=4000)


def service():
    return Admission(NativeTransactions(connection))


def execute(action):
    try:
        return action()
    except GovernanceError:
        raise DomainError(
            "PACKAGE_ADMISSION_IDENTITY_INVALID", "冻结门槛或原生报告不匹配", 409
        ) from None


@router.get("/models/{model_id}/context")
def context(model_id: UUID, request: Request):
    actor = auth(request)
    return execute(lambda: service().context(model_id, actor["member_id"]))


@router.post("/models/{model_id}/protocol")
def freeze(model_id: UUID, body: PackageAdmissionFreezeRequest, request: Request):
    actor = auth(request, True)
    return execute(
        lambda: service().freeze(
            model_id,
            actor["member_id"],
            body.document,
            request.headers.get("idempotency-key"),
            body.reason,
        )
    )


@router.get("/models/{model_id}/protocol")
def read_protocol(model_id: UUID, request: Request):
    actor = auth(request)
    return execute(lambda: service().read_protocol(model_id, actor["member_id"]))


@router.get("/models/{model_id}/evaluation-jobs/{job_id}/report-preview")
def preview_report(model_id: UUID, job_id: UUID, request: Request):
    actor = auth(request)
    return execute(lambda: service().preview_report(model_id, job_id, actor["member_id"]))


@router.post("/models/{model_id}/report")
def register_report(model_id: UUID, body: PackageAdmissionReportRequest, request: Request):
    actor = auth(request, True)
    return execute(
        lambda: service().register_report(
            model_id,
            body.evaluation_job_id,
            actor["member_id"],
            body.expected_packet_digest,
            request.headers.get("idempotency-key"),
            body.reason,
        )
    )


@router.get("/models/{model_id}/report")
def read_report(model_id: UUID, request: Request):
    actor = auth(request)
    return execute(lambda: service().read_report(model_id, actor["member_id"]))
