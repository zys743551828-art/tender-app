"""Explicit whole-package authoring input selection; no execution authority."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Hash = Annotated[str, Field(pattern="^[0-9a-f]{64}$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PackageReference(Strict):
    package_id: UUID
    revision_id: UUID
    manifest_digest: Hash


class InventoryReference(Strict):
    id: UUID
    digest: Hash
    rule_set_id: UUID


class PackageContext(Strict):
    target: PackageReference
    authority: PackageReference
    inventory: InventoryReference


class SectionSelection(Strict):
    draft_id: UUID
    snapshot_id: UUID
    snapshot_digest: Hash
    base_draft_revision: int = Field(ge=1, strict=True)
    section_id: UUID
    section_revision_id: UUID
    base_section_revision: int = Field(ge=1, strict=True)
    section_digest: Hash
    schema_digest: Hash
    node_id: str = Field(min_length=1, max_length=200)
    before_node_digest: Hash


class FactSubject(Strict):
    kind: Literal["engineering_project", "lot", "round", "bidder"]
    id: UUID


class FactUse(Strict):
    fact_id: UUID
    fact_item_digest: Hash
    subject: FactSubject
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class FactSelection(Strict):
    fact_set_id: UUID
    fact_head_revision: int = Field(ge=1, strict=True)
    identity_fact_ids: list[UUID] = Field(min_length=5, max_length=5)
    uses: list[FactUse] = Field(max_length=500)

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.identity_fact_ids)) != 5 or len({u.fact_id for u in self.uses}) != len(
            self.uses
        ):
            raise ValueError("事实身份或用途声明不可重复")
        return self


class PackageAuthoringInputRequest(Strict):
    protocol: Literal["package-authoring-input-request/1"]
    purpose: Literal["authoring"]
    target_relation: Literal["draft_using_package_context"]
    package_context: PackageContext
    target_section: SectionSelection
    facts: FactSelection


class PackageAuthoringInputCapabilities(Strict):
    protocol: Literal["package-authoring-input-capabilities/1"]
    capture_available: bool
    generation_available: Literal[False]
    publication_available: Literal[False]
    apply_available: Literal[False]
    build_available: Literal[False]
    automatic_input_selection: Literal[False]
    supported_target: Literal["plain_text_stable_node"]
    target_relation: Literal["draft_using_package_context"]
    context_limit_bytes: int
    blocking_reasons: list[str]


class PackageAuthoringInputView(Strict):
    manifest: dict
    digest: Hash


class PackageAuthoringInputPage(Strict):
    items: list[PackageAuthoringInputView]
    next_cursor: str | None
    has_more: bool


class PackageAuthoringInputContext(Strict):
    input_id: UUID
    input_digest: Hash
    stored_context_digest: Hash
    context: dict
    redacted_fields: list[Literal["documents[*].object_key"]]
    original_bytes_reverified: Literal[False]


class PackageAuthoringFactScopeView(Strict):
    manifest: dict
    digest: Hash


class PackageAuthoringInputCheck(Strict):
    input_digest: Hash


class PackageAuthoringInputStatus(Strict):
    protocol: Literal["package-authoring-input-status/1"]
    input_id: UUID
    input_digest: Hash
    current_input_matches: bool
    original_bytes_reverified: Literal[False]
    checked_at: str
    generation_available: Literal[False]
    publication_available: Literal[False]
    apply_available: Literal[False]
    build_available: Literal[False]
    blocking_reasons: list[str]


class PackageAuthoringFactWithdrawal(Strict):
    input_digest: Hash
    fact_id: UUID
    declaration_digest: Hash
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")
