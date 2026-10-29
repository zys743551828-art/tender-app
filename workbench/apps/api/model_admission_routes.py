"""Business protocol freeze/read only; no certification or execution activation."""

from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from apps.api.auth import auth
from packages.domain.runtime import DomainError, connection
from packages.model_admission.application import AdmissionError, AdmissionProtocols
from packages.model_admission.infrastructure import NativeProtocols

router = APIRouter(prefix="/api/v1/model-admission", tags=["model-admission"])


class FreezeProtocol(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document: dict
    reason: str = Field(min_length=1, max_length=4000)


def service():
    return AdmissionProtocols(NativeProtocols(connection))


@router.post("/cohorts/{cohort_id}/protocol")
def freeze_protocol(cohort_id: UUID, body: FreezeProtocol, request: Request):
    actor = auth(request, True)
    try:
        return service().freeze(
            cohort_id,
            actor["member_id"],
            body.document,
            request.headers.get("idempotency-key"),
            body.reason,
        )
    except AdmissionError as error:
        raise DomainError(str(error), "请提供完整显式业务门槛与稳定请求身份", 422) from None


@router.get("/cohorts/{cohort_id}/protocol")
def read_protocol(cohort_id: UUID, request: Request):
    actor = auth(request)
    return service().read(cohort_id, actor["member_id"])
