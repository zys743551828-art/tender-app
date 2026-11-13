"""Explicit human text edits retain exact provenance without inheriting model approval."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from packages.authoring.exact_revision_contracts import (
    AuthoringExactInputIdentity,
    ExactModel,
    Hash,
    Positive,
)


class AuthoringExactMarkedTextEditRequest(ExactModel):
    protocol: Literal["authoring-exact-marked-text-edit/1"]
    base_draft_revision: Positive
    section_revision_id: UUID
    node_id: Annotated[str, Field(min_length=1, max_length=128)]
    before_node_digest: Hash
    replacement_text: Annotated[str, Field(min_length=1, max_length=20000)]
    reason: Annotated[str, Field(min_length=1, max_length=1000)]


class AuthoringExactMarkedTextEditMethod(ExactModel):
    protocol: Literal["authoring-exact-text-edit-policy/3"]
    supported_content: Literal["single_marked_text_leaf_preserve_marks"]
    source_sha256: dict[str, Hash]


class AuthoringExactMarkedTextEditOrigin(ExactModel):
    kind: Literal["manual_marked_text_edit"]
    parent_qualification_id: UUID
    parent_qualification_digest: Hash
    root_qualification_id: UUID
    root_qualification_digest: Hash
    command_id: UUID
    actor_id: UUID
    before_action_digest: Hash
    node_id: str
    before_node_digest: Hash
    replacement_text_digest: Hash
    preserved_marks_digest: Hash
    reason: str


class AuthoringExactMarkedManualRevisionManifest(ExactModel):
    protocol: Literal["authoring-exact-manual-revision/3"]
    id: UUID
    bid_id: UUID
    draft_id: UUID
    draft_revision: Positive
    section_id: UUID
    section_revision_id: UUID
    section_revision: Positive
    section_digest: Hash
    schema_digest: Hash
    parent_section_revision_id: UUID
    parent_section_revision: Positive
    parent_section_digest: Hash
    input: AuthoringExactInputIdentity
    origin: AuthoringExactMarkedTextEditOrigin
    source_scope: Literal["exact_package_context"]
    source_refs_digest: Hash
    rule_ids_digest: Hash
    method: AuthoringExactMarkedTextEditMethod
    method_digest: Hash
    candidate_adopted: Literal[False]
    content_correctness_certified: Literal[False]


class AuthoringExactMarkedManualRevisionView(ExactModel):
    manifest: AuthoringExactMarkedManualRevisionManifest
    digest: Hash


class AuthoringExactMarkedTextEditCapabilities(ExactModel):
    protocol: Literal["authoring-exact-text-edit-capabilities/3"]
    available: bool
    supported_content: Literal["single_marked_text_leaf_preserve_marks"]
    preserves_source_refs: Literal[True]
    preserves_rule_ids: Literal[True]
    preserves_marks: Literal[True]
    ordinary_edit_available: Literal[False]
    blocking_reasons: list[str]


class AuthoringExactMarkedTextEditResult(ExactModel):
    protocol: Literal["authoring-exact-text-edit-result/3"]
    bid_id: UUID
    draft_id: UUID
    draft_revision: Positive
    snapshot_id: UUID
    snapshot_digest: Hash
    parent_section_revision_id: UUID
    section_revision_id: UUID
    section_digest: Hash
    qualification: AuthoringExactMarkedManualRevisionView
