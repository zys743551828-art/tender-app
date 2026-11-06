"""Manual partial page selections; never a model or formal-review admission."""

import hashlib
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from apps.api.auth import auth
from apps.api.identity_routes import command, saved
from apps.api.views import evidence_views_selected
from packages.domain import partial_page_selection_repository as repository
from packages.domain.bid_package_service import lock_bid
from packages.domain.runtime import DomainError, audit, clean, connection
from packages.lifecycle.service import assert_work_writable

router = APIRouter(prefix="/api/v1/bids/{bid_id}/partial-page-selections", tags=["partial pages"])
EVENT = "partial_pages.manually_confirmed.v1"


class SelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_version_id: UUID
    parse_run_id: UUID
    first_page: int = Field(ge=1, le=1000, strict=True)
    last_page: int = Field(ge=1, le=1000, strict=True)
    purpose: Literal["technical_reference", "requirement_reference"]
    confirmed: StrictBool


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentGap(ClosedModel):
    physical_page: int
    code: str


class SourceIdentity(ClosedModel):
    bid_id: UUID
    document_version_id: UUID
    parse_run_id: UUID
    file_digest: str
    parser_digest: str
    config_digest: str
    page_count: int
    coverage: Literal["complete", "partial"]
    gaps: list[str | DocumentGap]


class PageRange(ClosedModel):
    first_page: int
    last_page: int


class PageStatus(ClosedModel):
    physical_page: int
    quality: Literal["usable", "partial", "failed"]
    gaps: list[str]


class BlockIdentity(ClosedModel):
    id: UUID
    physical_page: int
    ordinal: int
    kind: Literal["text", "table", "visual_observation"]
    digest: str


class SelectionManifest(ClosedModel):
    version: Literal["partial-page-selection/1"]
    source: SourceIdentity
    purpose: Literal["technical_reference", "requirement_reference"]
    selection: PageRange
    selected_pages: list[PageStatus]
    selected_blocks: list[BlockIdentity]
    omitted_ranges: list[PageRange]
    coverage: Literal["partial"]
    manual_confirmation_recorded: Literal[False]
    original_bytes_reverified: Literal[False]
    model_execution_allowed: Literal[False]
    formal_qualification: Literal[False]


class SelectionProof(ClosedModel):
    manifest: SelectionManifest
    digest: str


class SelectionView(ClosedModel):
    id: UUID
    bid_id: UUID
    material_id: UUID
    confirmed_by: UUID
    confirmed_at: datetime
    manual_confirmation_recorded: Literal[True]
    proof: SelectionProof
    current_material: bool
    source_effectivity: Literal["not_verified"]
    model_execution_allowed: Literal[False]
    formal_qualification: Literal[False]


class SelectionHistoryItem(ClosedModel):
    id: UUID
    confirmed_by: UUID
    created_at: datetime


class SelectionHistory(ClosedModel):
    items: list[SelectionHistoryItem]
    has_more: bool


class ScopedEvidenceItem(ClosedModel):
    id: UUID
    document_version_id: UUID
    parse_run_id: UUID
    physical_page: int
    printed_label: str | None
    kind: Literal["text", "table", "visual_observation"]
    quote: str
    bbox: list[float] | None
    page_width: float
    page_height: float
    rotation: int
    source_status: Literal["candidate", "published", "withdrawn"]


class ScopedEvidence(ClosedModel):
    selection_id: UUID
    proof_digest: str
    items: list[ScopedEvidenceItem]
    coverage: Literal["partial"] = "partial"
    model_execution_allowed: Literal[False] = False
    formal_qualification: Literal[False] = False


class ComparisonCandidate(ClosedModel):
    id: UUID
    document_version_id: UUID
    filename: str
    purpose: Literal["technical_reference", "requirement_reference"]
    first_page: int
    last_page: int
    created_at: datetime


class ComparisonCandidates(ClosedModel):
    items: list[ComparisonCandidate]
    has_more: bool


class ComparisonSide(ClosedModel):
    selection: SelectionView
    evidence: ScopedEvidence


class PartialComparison(ClosedModel):
    requirement: ComparisonSide
    technical: ComparisonSide
    coverage: Literal["partial"] = "partial"
    overall_result: Literal["unknown"] = "unknown"
    model_execution_allowed: Literal[False] = False
    formal_qualification: Literal[False] = False


@router.post("", status_code=201, response_model=SelectionView)
def confirm_selection(bid_id: UUID, r: Request, body: SelectionRequest):
    actor = auth(r, True)
    if body.confirmed is not True:
        raise DomainError("PARTIAL_SCOPE_CONFIRMATION_REQUIRED", "请先人工核对并确认页范围。", 422)
    request = body.model_dump(mode="json")
    with connection() as c:
        lock_bid(c, bid_id)
        cmd = command(c, r, actor, "confirm_partial_pages", bid_id, request)
        if cmd.replay:
            return saved(cmd.replay, True)
        assert_work_writable(c, bid_id)
        proof, _, material_id = repository.observe(
            c,
            bid_id,
            body.document_version_id,
            body.parse_run_id,
            body.first_page,
            body.last_page,
            body.purpose,
            current=True,
        )
        identity = str(uuid4())
        timestamp = c.execute("SELECT clock_timestamp() AS at").fetchone()["at"]
        result = clean(
            {
                "id": identity,
                "bid_id": bid_id,
                "material_id": material_id,
                "confirmed_by": actor["member_id"],
                "confirmed_at": timestamp,
                "manual_confirmation_recorded": True,
                "proof": proof,
                "current_material": True,
                "source_effectivity": "not_verified",
                "model_execution_allowed": False,
                "formal_qualification": False,
            }
        )
        # The append-only event carries only metadata and evidence digests, not
        # document text. Each later read re-observes the exact parse identity.
        audit(c, actor["member_id"], bid_id, EVENT, result, cmd.id)
        return saved(cmd.finish(result, 201, {}))


@router.get("/candidates", response_model=ComparisonCandidates)
def comparison_candidates(bid_id: UUID, r: Request):
    """List references for choosing two scopes; load/revalidate before use."""
    auth(r)
    with connection() as c:
        rows = c.execute(
            """SELECT a.payload->>'id' AS id,
            a.payload#>>'{proof,manifest,source,document_version_id}' AS document_version_id,
            d.original_name AS filename,
            a.payload#>>'{proof,manifest,purpose}' AS purpose,
            (a.payload#>>'{proof,manifest,selection,first_page}')::int AS first_page,
            (a.payload#>>'{proof,manifest,selection,last_page}')::int AS last_page,a.created_at
            FROM design.audit_entries a JOIN design.document_versions d
              ON d.bid_id=a.bid_id AND d.id=(a.payload#>>'{proof,manifest,source,document_version_id}')::uuid
            WHERE a.bid_id=%s AND a.event_type=%s
            ORDER BY a.created_at DESC,a.id DESC LIMIT 101""",
            (bid_id, EVENT),
        ).fetchall()
        return {"items": clean(rows[:100]), "has_more": len(rows) > 100}


@router.get("/{selection_id}", response_model=SelectionView)
def get_selection(bid_id: UUID, selection_id: UUID, r: Request):
    auth(r)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return _load_selection(c, bid_id, selection_id)


def _load_selection(c, bid_id: UUID, selection_id: UUID):
    rows = c.execute(
        """SELECT payload FROM design.audit_entries WHERE bid_id=%s AND event_type=%s
            AND payload->>'id'=%s ORDER BY created_at LIMIT 2""",
        (bid_id, EVENT, str(selection_id)),
    ).fetchall()
    if len(rows) != 1:
        raise DomainError("PARTIAL_SCOPE_NOT_FOUND", "未找到指定的人工页范围记录。", 404)
    result = rows[0]["payload"]
    source = result["proof"]["manifest"]["source"]
    selection = result["proof"]["manifest"]["selection"]
    proof, current, current_material_id = repository.observe(
        c,
        bid_id,
        source["document_version_id"],
        source["parse_run_id"],
        selection["first_page"],
        selection["last_page"],
        result["proof"]["manifest"]["purpose"],
        current=False,
    )
    if proof != result["proof"]:
        raise DomainError("PARTIAL_SCOPE_SOURCE_CHANGED", "原件或解析依据已变化，请重新核对。", 409)
    return result | {"current_material": current and result["material_id"] == current_material_id}


@router.get("/{selection_id}/evidence", response_model=ScopedEvidence)
def get_scoped_evidence(bid_id: UUID, selection_id: UUID, r: Request):
    """Return selected evidence for manual review, never a model input grant."""
    auth(r)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        result = _load_selection(c, bid_id, selection_id)
        return _scoped_evidence(c, bid_id, selection_id, result)


def _scoped_evidence(c, bid_id, selection_id, result):
    manifest = result["proof"]["manifest"]
    expected = {item["id"]: item for item in manifest["selected_blocks"]}
    selected = evidence_views_selected(
        c, bid_id, manifest["source"]["parse_run_id"], sorted(expected)
    )
    if len(selected) != len(expected) or any(
        item["physical_page"] != expected[item["id"]]["physical_page"]
        or hashlib.sha256(item["quote"].encode("utf-8")).hexdigest()
        != expected[item["id"]]["digest"]
        for item in selected
    ):
        raise DomainError("PARTIAL_SCOPE_SOURCE_CHANGED", "选中证据已改变，请重新核对。", 409)
    return {
        "selection_id": selection_id,
        "proof_digest": result["proof"]["digest"],
        "items": selected,
    }


@router.get("/{selection_id}/compare/{other_id}", response_model=PartialComparison)
def compare_scopes(bid_id: UUID, selection_id: UUID, other_id: UUID, r: Request):
    """Present two proven page selections side by side; never decide compliance."""
    auth(r)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        requirement = _load_selection(c, bid_id, selection_id)
        technical = _load_selection(c, bid_id, other_id)
        if (
            not requirement["current_material"]
            or not technical["current_material"]
            or requirement["proof"]["manifest"]["purpose"] != "requirement_reference"
            or technical["proof"]["manifest"]["purpose"] != "technical_reference"
        ):
            raise DomainError(
                "PARTIAL_COMPARISON_STALE_OR_WRONG_PURPOSE", "请选择当前要求范围和技术范围。", 409
            )
        requirement_evidence = _scoped_evidence(c, bid_id, selection_id, requirement)
        technical_evidence = _scoped_evidence(c, bid_id, other_id, technical)
        if not requirement_evidence["items"] or not technical_evidence["items"]:
            raise DomainError(
                "PARTIAL_COMPARISON_NO_EVIDENCE", "所选范围缺少可对照的解析依据。", 409
            )
        if any(
            item["source_status"] == "withdrawn"
            for evidence in (requirement_evidence, technical_evidence)
            for item in evidence["items"]
        ):
            raise DomainError(
                "PARTIAL_COMPARISON_SOURCE_WITHDRAWN", "所选依据已撤回，请重新核对来源。", 409
            )
        return {
            "requirement": {
                "selection": requirement,
                "evidence": requirement_evidence,
            },
            "technical": {
                "selection": technical,
                "evidence": technical_evidence,
            },
        }


@router.get("", response_model=SelectionHistory)
def list_selections(bid_id: UUID, r: Request, document_version_id: UUID = Query()):
    auth(r)
    with connection() as c:
        rows = c.execute(
            """SELECT payload->>'id' AS id,actor_id::text AS confirmed_by,created_at
            FROM design.audit_entries WHERE bid_id=%s AND event_type=%s
            AND payload#>>'{proof,manifest,source,document_version_id}'=%s
            ORDER BY created_at DESC,id DESC LIMIT 101""",
            (bid_id, EVENT, str(document_version_id)),
        ).fetchall()
        return {"items": clean(rows[:100]), "has_more": len(rows) > 100}
