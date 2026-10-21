"""Actual B3 qualification outputs; no client-supplied source authority object."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Positive = Annotated[int, Field(ge=1)]


class ExactModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuthoringExactInputIdentity(ExactModel):
    id: UUID
    digest: Hash
    context_digest: Hash


class AuthoringExactRevisionOrigin(ExactModel):
    kind: Literal["model_candidate_adoption"]
    job_id: UUID
    job_input_digest: Hash
    action_id: UUID
    action_digest: Hash
    candidate_digest: Hash
    command_id: UUID
    actor_id: UUID
    before_action_digest: Hash


class AuthoringExactRevisionMethod(ExactModel):
    protocol: Literal["authoring-exact-adoption-policy/1"]
    supported_content: Literal["plain_text_stable_node"]
    source_sha256: dict[str, Hash]


class AuthoringExactRevisionManifest(ExactModel):
    protocol: Literal["authoring-exact-revision/1"]
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
    origin: AuthoringExactRevisionOrigin
    source_scope: Literal["exact_package_context"]
    source_refs_digest: Hash
    rule_ids_digest: Hash
    method: AuthoringExactRevisionMethod
    method_digest: Hash
    candidate_adopted: Literal[True]
    content_correctness_certified: Literal[False]


class AuthoringExactRevisionView(ExactModel):
    manifest: AuthoringExactRevisionManifest
    digest: Hash


class AuthoringExactSectionBinding(ExactModel):
    section_id: UUID
    section_revision_id: UUID
    section_revision: Positive
    section_digest: Hash
    qualification_id: UUID
    qualification_digest: Hash
    authoring_input_id: UUID
    authoring_input_digest: Hash
    source_scope: Literal["exact_package_context"]


class AuthoringExactSnapshotExtension(ExactModel):
    protocol: Literal["authoring-exact-snapshot/1"]
    sections: Annotated[list[AuthoringExactSectionBinding], Field(min_length=1, max_length=1000)]
    digest: Hash


class AuthoringExactRevisionCapabilities(ExactModel):
    protocol: Literal["authoring-exact-revision-capabilities/1"]
    apply_available: bool
    build_available: bool
    ordinary_edit_available: Literal[False]
    supported_content: Literal["plain_text_stable_node"]
    blocking_reasons: list[str]


class AuthoringExactDraftStatus(ExactModel):
    protocol: Literal["authoring-exact-draft-status/1"]
    bid_id: UUID
    draft_id: UUID
    draft_revision: Positive
    snapshot_id: UUID
    snapshot_digest: Hash
    exact_sections: list[AuthoringExactSectionBinding]
    ordinary_edit_available: bool
    build_available: bool
    blocking_reasons: list[str]
