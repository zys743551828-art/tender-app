"""Append human observations on two partial scopes without granting formal qualification."""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from apps.api.auth import auth
from apps.api.identity_routes import command, saved
from apps.api.partial_page_selection_routes import _comparison_context
from packages.domain import partial_page_selection_repository as repository
from packages.domain.bid_package_service import lock_bid
from packages.domain.runtime import DomainError, audit, clean, connection
from packages.knowledge import sources
from packages.lifecycle.service import assert_work_writable

router = APIRouter(prefix="/api/v1/bids/{bid_id}/partial-page-selections", tags=["partial pages"])
EVENT = "partial_pages.human_observation.v1"


class PartialScopeObservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: UUID | None = None
    expected_revision: int = Field(ge=0, strict=True)
    requirement_evidence_id: UUID
    technical_evidence_id: UUID | None = None
    outcome: Literal["observed_support", "observed_conflict", "not_applicable", "needs_review"]
    reason: str = Field(min_length=1, max_length=1000)
    confirmed: StrictBool


class PartialScopeObservationView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    item_id: UUID
    revision: int
    bid_id: UUID
    requirement_selection_id: UUID
    technical_selection_id: UUID
    requirement_proof_digest: str
    technical_proof_digest: str
    requirement_evidence_id: UUID
    technical_evidence_id: UUID | None
    outcome: Literal["observed_support", "observed_conflict", "not_applicable", "needs_review"]
    reason: str
    actor_id: UUID
    created_at: datetime
    origin: Literal["human_observation"] = "human_observation"
    coverage: Literal["partial"] = "partial"
    overall_result: Literal["unknown"] = "unknown"
    source_effectivity: Literal["not_verified"] = "not_verified"
    formal_qualification: Literal[False] = False
    model_execution_allowed: Literal[False] = False


class DecisionHistory(BaseModel):
    items: list[PartialScopeObservationView]
    scope_revalidated: bool
    has_more: bool


def _lock_proofs(c, bid_id, context):
    # Serialize source changes and hold each selected parse until commit.
    for side in (context["requirement"], context["technical"]):
        manifest = side["selection"]["proof"]["manifest"]
        source, span = manifest["source"], manifest["selection"]
        proof, current, material = repository.observe(
            c,
            bid_id,
            source["document_version_id"],
            source["parse_run_id"],
            span["first_page"],
            span["last_page"],
            manifest["purpose"],
            current=True,
        )
        if (
            not current
            or proof != side["selection"]["proof"]
            or material != side["selection"]["material_id"]
        ):
            raise DomainError(
                "PARTIAL_DECISION_SOURCE_STALE", "范围或材料已变化，请重新核对。", 409
            )


@router.post(
    "/{selection_id}/compare/{other_id}/decisions",
    status_code=201,
    response_model=PartialScopeObservationView,
)
def save_observation(
    bid_id: UUID,
    selection_id: UUID,
    other_id: UUID,
    r: Request,
    body: PartialScopeObservationRequest,
):
    actor = auth(r, True)
    if not body.confirmed or not body.reason.strip():
        raise DomainError("PARTIAL_DECISION_CONFIRMATION_REQUIRED", "请填写理由并明确确认。", 422)
    if (body.item_id is None) != (body.expected_revision == 0):
        raise DomainError("PARTIAL_DECISION_REVISION_INVALID", "请刷新后重新选择记录。", 422)
    if (
        body.outcome in {"observed_support", "observed_conflict"}
        and body.technical_evidence_id is None
    ):
        raise DomainError(
            "PARTIAL_DECISION_TECHNICAL_EVIDENCE_REQUIRED", "该意见须选择技术依据。", 422
        )
    with connection() as c:
        lock_bid(c, bid_id)
        request = body.model_dump(mode="json") | {
            "requirement_selection_id": str(selection_id),
            "technical_selection_id": str(other_id),
        }
        cmd = command(c, r, actor, "record_partial_observation", bid_id, request)
        assert_work_writable(c, bid_id)
        sources.lock_graph(c)
        context = _comparison_context(c, bid_id, selection_id, other_id)
        _lock_proofs(c, bid_id, context)
        if cmd.replay:
            return saved(cmd.replay, True)
        req = {str(item["id"]) for item in context["requirement"]["evidence"]["items"]}
        tech = {str(item["id"]) for item in context["technical"]["evidence"]["items"]}
        if str(body.requirement_evidence_id) not in req or (
            body.technical_evidence_id is not None and str(body.technical_evidence_id) not in tech
        ):
            raise DomainError(
                "PARTIAL_DECISION_EVIDENCE_OUTSIDE_SCOPE", "请选择范围内的依据。", 422
            )
        item_id = str(body.item_id or uuid4())
        previous = c.execute(
            """SELECT payload FROM design.audit_entries WHERE bid_id=%s AND event_type=%s
            AND payload->>'item_id'=%s ORDER BY (payload->>'revision')::int DESC LIMIT 1""",
            (bid_id, EVENT, item_id),
        ).fetchone()
        if body.expected_revision == 0:
            if previous is not None:
                raise DomainError("PARTIAL_DECISION_REVISION_CONFLICT", "记录已变化，请刷新。", 409)
        elif (
            previous is None
            or previous["payload"]["revision"] != body.expected_revision
            or previous["payload"]["requirement_selection_id"] != str(selection_id)
            or previous["payload"]["technical_selection_id"] != str(other_id)
            or previous["payload"]["requirement_evidence_id"] != str(body.requirement_evidence_id)
        ):
            raise DomainError("PARTIAL_DECISION_REVISION_CONFLICT", "记录已变化，请刷新。", 409)
        result = clean(
            {
                "id": str(uuid4()),
                "item_id": item_id,
                "revision": body.expected_revision + 1,
                "bid_id": bid_id,
                "requirement_selection_id": selection_id,
                "technical_selection_id": other_id,
                "requirement_proof_digest": context["requirement"]["selection"]["proof"]["digest"],
                "technical_proof_digest": context["technical"]["selection"]["proof"]["digest"],
                "requirement_evidence_id": body.requirement_evidence_id,
                "technical_evidence_id": body.technical_evidence_id,
                "outcome": body.outcome,
                "reason": body.reason.strip(),
                "actor_id": actor["member_id"],
                "created_at": c.execute("SELECT clock_timestamp() AS at").fetchone()["at"],
                "origin": "human_observation",
                "coverage": "partial",
                "overall_result": "unknown",
                "source_effectivity": "not_verified",
                "formal_qualification": False,
                "model_execution_allowed": False,
            }
        )
        audit(c, actor["member_id"], bid_id, EVENT, result, cmd.id)
        return saved(cmd.finish(result, 201, {}))


@router.get("/{selection_id}/compare/{other_id}/decisions", response_model=DecisionHistory)
def observation_history(bid_id: UUID, selection_id: UUID, other_id: UUID, r: Request):
    auth(r)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        rows = c.execute(
            """SELECT payload FROM design.audit_entries WHERE bid_id=%s AND event_type=%s
            AND payload->>'requirement_selection_id'=%s AND payload->>'technical_selection_id'=%s
            ORDER BY created_at DESC,id DESC LIMIT 101""",
            (bid_id, EVENT, str(selection_id), str(other_id)),
        ).fetchall()
        try:
            context = _comparison_context(c, bid_id, selection_id, other_id)
            current = all(
                row["payload"]["requirement_proof_digest"]
                == context["requirement"]["selection"]["proof"]["digest"]
                and row["payload"]["technical_proof_digest"]
                == context["technical"]["selection"]["proof"]["digest"]
                for row in rows[:100]
            )
        except DomainError:
            current = False
        return {
            "items": [row["payload"] for row in rows[:100]],
            "scope_revalidated": current,
            "has_more": len(rows) > 100,
        }
