"""Observe the current saved chapter's exact-authoring/Word layout prerequisite."""

from typing import Literal
from uuid import UUID

from psycopg.errors import QueryCanceled
from pydantic import BaseModel, ConfigDict, Field

from packages.authoring import exact_sources, format_bindings, snapshot_structure
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
    ordinary_structure_protected: bool


def _structure_protected(c, bid, draft):
    try:
        exact_sources.assert_ordinary_edit(c, bid, draft)
    except DomainError as error:
        if error.code != "AUTHORING_EXACT_REVISION_OPERATION_UNSUPPORTED":
            raise
        return True
    return False


def _state(c, bid, manifest) -> tuple[LayoutState, list[UnsupportedReason]]:
    extension = snapshot_structure.snapshot_extension(manifest)
    if extension is None:
        return "plain_draft", []
    metadata = extension["metadata"]
    reasons: list[UnsupportedReason] = []
    if extension["plans"]:
        reasons.append("saved_chapter_plans")
    if metadata.get("format_bindings"):
        reasons.append("bound_project_format")
    if metadata.get("word_import_sources"):
        reasons.append("word_import_sources")
    if reasons:
        # This observes the whole saved snapshot, not just the selected node.
        # Exact B1 does not inherit these sources. Nothing is removed.
        return "structure_not_supported", reasons
    try:
        format_bindings.assert_snapshot(c, bid, extension, lock_sources=False)
    except DomainError as error:
        if error.code == "AUTHORING_FORMAT_REVIEW_REQUIRED":
            return "layout_review_required", []
        if error.code == "AUTHORING_FORMAT_BINDING_STALE":
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
        state, reasons = _state(c, bid, snapshot)
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
        ordinary_structure_protected=protected,
    )
