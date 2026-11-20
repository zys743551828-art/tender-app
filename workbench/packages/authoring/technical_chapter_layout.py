"""Observe the current saved chapter's exact-authoring/Word layout prerequisite."""

from typing import Literal
from uuid import UUID

from psycopg.errors import QueryCanceled
from pydantic import BaseModel, ConfigDict, Field

from packages.authoring import (
    combined_authoring_scope,
    exact_sources,
    format_bindings,
    saved_chapter_plans,
    snapshot_structure,
)
from packages.authoring.technical_chapter_templates import observed_chapter_head
from packages.domain.runtime import DomainError, fetch, sha

LayoutState = Literal[
    "plain_draft",
    "structured_layout_rechecked",
    "layout_review_required",
    "layout_basis_changed",
    "structure_not_supported",
]

UnsupportedReason = Literal["saved_chapter_plans", "bound_project_format", "word_import_sources"]
PlanState = Literal["none", "requires_fixed_evidence", "not_configured", "target_stale"]


class TechnicalChapterLayoutView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bid_id: UUID
    draft_id: UUID
    section_id: UUID
    snapshot_id: UUID
    draft_revision: int = Field(ge=1)
    section_revision: int = Field(ge=1)
    state: LayoutState
    unsupported_reasons: list[UnsupportedReason]
    plan_state: PlanState
    section_plan_revision: int | None = Field(ge=1)
    ordinary_structure_protected: bool


def _structure_protected(c, bid, draft):
    try:
        exact_sources.assert_ordinary_edit(c, bid, draft)
    except DomainError as error:
        if error.code != "AUTHORING_EXACT_REVISION_OPERATION_UNSUPPORTED":
            raise
        return True
    return False


def _plan_state(c, extension, section) -> tuple[PlanState, int | None]:
    if not extension or not extension["plans"]:
        return "none", None
    selected = saved_chapter_plans.selected_plan(extension, str(section))
    revision = selected["revision"] if selected else None
    if not saved_chapter_plans.installed(c):
        return "not_configured", revision
    if saved_chapter_plans.stale_target(extension, str(section)):
        return "target_stale", revision
    return "requires_fixed_evidence", revision


def _state(c, bid, extension, plan_state) -> tuple[LayoutState, list[UnsupportedReason]]:
    if extension is None:
        return "plain_draft", []
    metadata = extension["metadata"]
    reasons: list[UnsupportedReason] = []
    if plan_state in {"not_configured", "target_stale"}:
        reasons.append("saved_chapter_plans")
    if not combined_authoring_scope.ready(c, extension):
        reasons.append("bound_project_format")
    if metadata.get("word_import_sources"):
        reasons.append("word_import_sources")
    if reasons:
        # This reads the saved prerequisite only. Full rules and original
        # source selection still require B1; nothing is removed or authorized.
        return "structure_not_supported", reasons
    try:
        format_bindings.assert_snapshot(c, bid, extension, lock_sources=False)
    except DomainError as error:
        if error.code == "AUTHORING_FORMAT_REVIEW_REQUIRED":
            return "layout_review_required", []
        if error.code in {
            "AUTHORING_FORMAT_BINDING_INVALID",
            "AUTHORING_FORMAT_BINDING_STALE",
            "AUTHORING_FORMAT_RULE_STALE",
            "AUTHORING_FORMAT_RULE_UNCONFIRMED",
            "AUTHORING_SOURCE_STALE",
            "FACT_EVIDENCE_REQUIRED",
            "SOURCE_CLOSURE_INCOMPLETE",
        }:
            return "layout_basis_changed", []
        raise
    return "structured_layout_rechecked", []


def read(c, bid, draft, section):
    c.execute("SET LOCAL statement_timeout = '5s'")
    try:
        head = observed_chapter_head(c, bid, draft, section)
        snapshot = fetch(
            c,
            """SELECT manifest FROM design.draft_snapshots
               WHERE bid_id=%s AND draft_id=%s AND id=%s AND revision=%s""",
            (bid, draft, head["snapshot_id"], head["draft_revision"]),
        )["manifest"]
        if (
            not isinstance(snapshot, dict)
            or snapshot.get("draft_id") != str(draft)
            or snapshot.get("revision") != head["draft_revision"]
            or sha(snapshot) != head["snapshot_digest"]
        ):
            raise DomainError(
                "TECHNICAL_CHAPTER_LAYOUT_UNVERIFIED", "无法完整核对当前草稿的结构快照。", 409
            )
        extension = snapshot_structure.snapshot_extension(snapshot)
        plan_state, plan_revision = _plan_state(c, extension, section)
        state, reasons = _state(c, bid, extension, plan_state)
        protected = _structure_protected(c, bid, draft)
    except QueryCanceled as error:
        raise DomainError(
            "TECHNICAL_CHAPTER_LAYOUT_READ_TIMEOUT", "当前草稿的版式前置核对超时。", 503
        ) from error
    return TechnicalChapterLayoutView(
        bid_id=bid,
        draft_id=draft,
        section_id=section,
        snapshot_id=head["snapshot_id"],
        draft_revision=head["draft_revision"],
        section_revision=head["section_revision"],
        state=state,
        unsupported_reasons=reasons,
        plan_state=plan_state,
        section_plan_revision=plan_revision,
        ordinary_structure_protected=protected,
    )
