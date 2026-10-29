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


class AuthoringExactTextEditRequest(ExactModel):
    base_draft_revision: Positive
    section_revision_id: UUID
    node_id: Annotated[str, Field(min_length=1, max_length=128)]
    before_node_digest: Hash
    replacement_text: Annotated[str, Field(max_length=20000)]
    reason: Annotated[str, Field(min_length=1, max_length=1000)]


class AuthoringExactTextEditMethod(ExactModel):
    protocol: Literal["authoring-exact-text-edit-policy/1"]
    supported_content: Literal["plain_text_stable_node"]
    source_sha256: dict[str, Hash]


class AuthoringExactTextEditOrigin(ExactModel):
    kind: Literal["manual_text_edit"]
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
    reason: str


class AuthoringExactManualRevisionManifest(ExactModel):
    protocol: Literal["authoring-exact-manual-revision/1"]
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
    origin: AuthoringExactTextEditOrigin
    source_scope: Literal["exact_package_context"]
    source_refs_digest: Hash
    rule_ids_digest: Hash
    method: AuthoringExactTextEditMethod
    method_digest: Hash
    candidate_adopted: Literal[False]
    content_correctness_certified: Literal[False]


class AuthoringExactManualRevisionView(ExactModel):
    manifest: AuthoringExactManualRevisionManifest
    digest: Hash


class AuthoringExactTextEditCapabilities(ExactModel):
    protocol: Literal["authoring-exact-text-edit-capabilities/1"]
    available: bool
    supported_content: Literal["plain_text_stable_node"]
    preserves_source_refs: Literal[True]
    preserves_rule_ids: Literal[True]
    ordinary_edit_available: Literal[False]
    blocking_reasons: list[str]


class AuthoringExactTextEditResult(ExactModel):
    protocol: Literal["authoring-exact-text-edit-result/1"]
    bid_id: UUID
    draft_id: UUID
    draft_revision: Positive
    snapshot_id: UUID
    snapshot_digest: Hash
    parent_section_revision_id: UUID
    section_revision_id: UUID
    section_digest: Hash
    qualification: AuthoringExactManualRevisionView


class AuthoringExactTextChange(ExactModel):
    node_id: Annotated[str, Field(min_length=1, max_length=128)]
    before_node_digest: Hash
    replacement_text: Annotated[str, Field(max_length=20000)]


class AuthoringExactMultiTextEditRequest(ExactModel):
    protocol: Literal["authoring-exact-multi-text-edit/1"]
    base_draft_revision: Positive
    section_revision_id: UUID
    edits: Annotated[list[AuthoringExactTextChange], Field(min_length=2, max_length=20)]
    reason: Annotated[str, Field(min_length=1, max_length=1000)]


class AuthoringExactMultiTextEditMethod(ExactModel):
    protocol: Literal["authoring-exact-text-edit-policy/2"]
    supported_content: Literal["plain_text_stable_nodes"]
    source_sha256: dict[str, Hash]


class AuthoringExactTextChangeOrigin(ExactModel):
    node_id: str
    before_node_digest: Hash
    replacement_text_digest: Hash


class AuthoringExactMultiTextEditOrigin(ExactModel):
    kind: Literal["manual_multi_text_edit"]
    parent_qualification_id: UUID
    parent_qualification_digest: Hash
    root_qualification_id: UUID
    root_qualification_digest: Hash
    command_id: UUID
    actor_id: UUID
    before_action_digest: Hash
    edits: Annotated[list[AuthoringExactTextChangeOrigin], Field(min_length=2, max_length=20)]
    reason: str


class AuthoringExactMultiManualRevisionManifest(ExactModel):
    protocol: Literal["authoring-exact-manual-revision/2"]
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
    origin: AuthoringExactMultiTextEditOrigin
    source_scope: Literal["exact_package_context"]
    source_refs_digest: Hash
    rule_ids_digest: Hash
    method: AuthoringExactMultiTextEditMethod
    method_digest: Hash
    candidate_adopted: Literal[False]
    content_correctness_certified: Literal[False]


class AuthoringExactMultiManualRevisionView(ExactModel):
    manifest: AuthoringExactMultiManualRevisionManifest
    digest: Hash


class AuthoringExactMultiTextEditResult(ExactModel):
    protocol: Literal["authoring-exact-text-edit-result/2"]
    bid_id: UUID
    draft_id: UUID
    draft_revision: Positive
    snapshot_id: UUID
    snapshot_digest: Hash
    parent_section_revision_id: UUID
    section_revision_id: UUID
    section_digest: Hash
    qualification: AuthoringExactMultiManualRevisionView


class AuthoringExactMultiTextEditCapabilities(ExactModel):
    protocol: Literal["authoring-exact-text-edit-capabilities/2"]
    available: bool
    supported_content: Literal["plain_text_stable_nodes"]
    preserves_source_refs: Literal[True]
    preserves_rule_ids: Literal[True]
    ordinary_edit_available: Literal[False]
    blocking_reasons: list[str]
