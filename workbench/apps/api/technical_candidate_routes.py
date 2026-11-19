"""Advisory checks for an exact immutable Word build, never publication authority."""

from typing import Annotated, Literal
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from apps.api.auth import auth
from packages.authoring import package_outputs, rich_build
from packages.authoring.generated_docx import MAX_DOCX_BYTES
from packages.authoring.technical_candidate_checks import (
    MAX_NAME_LENGTH,
    MAX_NAMES,
    frozen_page_margins,
    inspect_candidate_docx,
)
from packages.domain.runtime import DomainError, connection, sha
from packages.word_intake.inspection import MAX_BYTES as MAX_INSPECTION_BYTES

router = APIRouter(prefix="/api/v1", tags=["technical-qualification"])
MAX_CHECK_BYTES = min(MAX_DOCX_BYTES, MAX_INSPECTION_BYTES)
PATH = "/bids/{bid_id}/builds/{build_id}/technical-docx-check"
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ProjectName = Annotated[str, StringConstraints(min_length=1, max_length=MAX_NAME_LENGTH)]


class TechnicalDocxCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_version_id: UUID
    filename: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    prohibited_names: Annotated[list[ProjectName], Field(max_length=MAX_NAMES)] = Field(
        default_factory=list
    )


class TechnicalDocxCheckView(BaseModel):
    protocol: Literal["technical-candidate-docx-check/1"]
    bid_id: UUID
    build_id: UUID
    document_version_id: UUID
    snapshot_id: UUID
    snapshot_digest: Digest
    artifact_sha256: Digest
    policy_sha256: Digest
    blocking_codes: tuple[str, ...]
    manual_check_codes: tuple[str, ...]
    historical_advisory: Literal[True]
    publication_authorized: Literal[False]


@router.post(
    PATH,
    operation_id="checkTechnicalDocxCandidate",
    response_model=TechnicalDocxCheckView,
    openapi_extra={
        "security": [{"SessionCookie": []}],
        "parameters": [
            {"in": "header", "name": name, "required": True, "schema": {"type": "string"}}
            for name in ("Origin", "X-CSRF-Token")
        ],
    },
)
def check_technical_docx(
    bid_id: UUID, build_id: UUID, r: Request, body: TechnicalDocxCheckRequest
) -> TechnicalDocxCheckView:
    actor_id = auth(r, True)["member_id"]
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        packet = package_outputs.capture(
            c, bid_id, build_id, body.document_version_id, historical=True
        )
    proof, documents = packet["proof"], packet["documents"]
    if proof["format"] != "docx" or len(documents) != 1:
        raise DomainError("TECHNICAL_DOCX_BUILD_REQUIRED", "请选择该构建的确切 DOCX 输出", 422)
    descriptor = documents[0]
    if (
        proof["bid_id"] != str(bid_id)
        or proof["build_id"] != str(build_id)
        or proof["document_version_id"] != str(body.document_version_id)
        or descriptor["digest"] != proof["sha256"]
        or descriptor["byte_size"] != proof["byte_size"]
    ):
        raise DomainError("TECHNICAL_DOCX_BUILD_MISMATCH", "文件与所选构建不一致", 409)
    if type(proof["byte_size"]) is not int or not 0 < proof["byte_size"] <= MAX_CHECK_BYTES:
        raise DomainError("TECHNICAL_DOCX_CHECK_LIMIT", "文件大小超出 DOCX 检查范围", 422)
    try:
        data = rich_build.read_checked(descriptor)
    except (BotoCoreError, ClientError, OSError):
        raise DomainError(
            "OBJECT_STORE_UNAVAILABLE", "暂时无法读取构建文件", 503, retryable=True
        ) from None
    if len(data) != proof["byte_size"] or sha(data) != proof["sha256"]:
        raise DomainError("BUILD_OBJECT_CORRUPT", "构建对象实际字节与冻结摘要不符", 503)
    checked = inspect_candidate_docx(
        data,
        filename=body.filename,
        prohibited_names=body.prohibited_names,
        page_margins=frozen_page_margins(packet["snapshot"]),
    )
    # Observe a historical packet only, and do not infer current review eligibility.
    # Session and CSRF must still be valid after off-transaction I/O and parsing.
    if auth(r, True)["member_id"] != actor_id:
        raise DomainError("TECHNICAL_DOCX_ACTOR_CHANGED", "原检查会话已经变化，请重新登录", 403)
    identity = proof["build_identity"]
    return TechnicalDocxCheckView(
        protocol="technical-candidate-docx-check/1",
        bid_id=bid_id,
        build_id=build_id,
        document_version_id=body.document_version_id,
        snapshot_id=UUID(identity["snapshot_id"]),
        snapshot_digest=identity["snapshot_digest"],
        artifact_sha256=checked.artifact_sha256,
        policy_sha256=checked.policy_sha256,
        blocking_codes=checked.blocking_codes,
        manual_check_codes=checked.manual_check_codes,
        historical_advisory=True,
        publication_authorized=False,
    )
