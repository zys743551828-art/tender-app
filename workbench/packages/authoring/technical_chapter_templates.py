"""Bounded, read-only lookup of saved exact authoring templates for one chapter."""

from uuid import UUID

from psycopg.errors import QueryCanceled
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from packages.authoring import package_input_repository
from packages.authoring.package_input_contracts import PackageAuthoringInputRequest
from packages.domain.runtime import DomainError, fetch, sha
from packages.tasks.models import ExactPackageAuthoringSelection, TemplateRequest

MAX_TEMPLATES = 12


class TechnicalChapterTemplateItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: UUID
    template_version_id: UUID
    template_revision: int = Field(ge=1)
    template_digest: str = Field(pattern="^[a-f0-9]{64}$")
    name: str = Field(min_length=1, max_length=200)
    paused: bool
    input_id: UUID
    input_digest: str = Field(pattern="^[a-f0-9]{64}$")
    input_snapshot_id: UUID
    input_draft_revision: int = Field(ge=1)
    input_section_revision: int = Field(ge=1)
    bound_to_observed_chapter: bool


class TechnicalChapterTemplatePage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bid_id: UUID
    draft_id: UUID
    section_id: UUID
    observed_snapshot_id: UUID
    observed_draft_revision: int = Field(ge=1)
    observed_section_revision: int = Field(ge=1)
    available: bool
    has_more: bool
    items: list[TechnicalChapterTemplateItem] = Field(max_length=MAX_TEMPLATES)


def invalid():
    return DomainError(
        "TECHNICAL_CHAPTER_TEMPLATE_LINK_INVALID",
        "已保存编写模板和固定输入的身份不能核验，未替换其他记录。",
        409,
    )


def checked_item(row, head, bid, draft, section):
    try:
        config, manifest = row["config"], row["input_manifest"]
        definition = TemplateRequest.model_validate(config["definition"])
        frozen = PackageAuthoringInputRequest.model_validate(manifest["selection"])
        target = frozen.target_section
        source = definition.source_selection
        if (
            config.get("schema") != "task-template/1"
            or config.get("formal_decisions_allowed") is not False
            or config.get("paused") is not row["paused"]
            or sha(config) != row["template_digest"]
            or definition.section_id != section
            or not isinstance(source, ExactPackageAuthoringSelection)
            or source.input.authoring_input_id != row["input_id"]
            or source.input.authoring_input_digest != row["input_digest"]
            or manifest.get("protocol") != "package-authoring-input/1"
            or manifest.get("bid_id") != str(bid)
            or manifest.get("id") != str(row["input_id"])
            or sha(manifest) != row["input_digest"]
            or target.draft_id != draft
            or target.section_id != section
        ):
            raise invalid()
        return TechnicalChapterTemplateItem(
            template_id=row["template_id"],
            template_version_id=row["template_version_id"],
            template_revision=row["template_revision"],
            template_digest=row["template_digest"],
            name=definition.name,
            paused=row["paused"],
            input_id=row["input_id"],
            input_digest=row["input_digest"],
            input_snapshot_id=target.snapshot_id,
            input_draft_revision=target.base_draft_revision,
            input_section_revision=target.base_section_revision,
            bound_to_observed_chapter=(
                target.snapshot_id == head["snapshot_id"]
                and target.snapshot_digest == head["snapshot_digest"]
                and target.base_draft_revision == head["draft_revision"]
                and target.section_revision_id == head["section_revision_id"]
                and target.section_digest == head["section_digest"]
                and target.base_section_revision == head["section_revision"]
            ),
        )
    except (KeyError, TypeError, ValidationError) as error:
        raise invalid() from error


def read(c, bid, draft, section):
    c.execute("SET LOCAL statement_timeout = '5s'")
    try:
        # Before any discovery, resolve the nested identity in the observed
        # current snapshot; a different bid/draft and a removed section aren't alternatives.
        head = fetch(
            c,
            """SELECT d.revision AS draft_revision,snap.id AS snapshot_id,
                      snap.digest AS snapshot_digest,r.id AS section_revision_id,
                      r.revision AS section_revision,r.digest AS section_digest
               FROM design.drafts d
               JOIN design.draft_snapshots snap
                 ON snap.bid_id=d.bid_id AND snap.draft_id=d.id AND snap.revision=d.revision
               JOIN design.sections s ON s.bid_id=d.bid_id AND s.draft_id=d.id AND s.id=%s
               JOIN design.draft_snapshot_sections link
                 ON link.bid_id=d.bid_id AND link.draft_id=d.id AND link.snapshot_id=snap.id
               JOIN design.section_revisions r
                 ON r.id=link.section_revision_id AND r.bid_id=d.bid_id AND r.draft_id=d.id
                 AND r.section_id=s.id AND r.revision=s.head_revision
               WHERE d.bid_id=%s AND d.id=%s""",
            (section, bid, draft),
        )
        available = package_input_repository.available(c)
        rows = (
            c.execute(
                """SELECT d.id AS template_id,v.id AS template_version_id,
                          v.revision AS template_revision,v.digest AS template_digest,v.config,
                          d.paused,i.id AS input_id,i.digest AS input_digest,i.manifest AS input_manifest
                   FROM design.task_definitions d
                   JOIN design.task_definition_versions v
                     ON v.bid_id=d.bid_id AND v.definition_id=d.id AND v.revision=d.revision
                   JOIN design.authoring_package_inputs i ON i.bid_id=v.bid_id
                     AND i.id::text=v.config#>>'{definition,source_selection,input,authoring_input_id}'
                   WHERE d.bid_id=%s
                     AND v.config#>>'{definition,task_kind}'='chapter_suggestion'
                     AND v.config#>>'{definition,source_selection,mode}'='exact_package_authoring'
                     AND v.config#>>'{definition,section_id}'=%s
                     AND i.manifest#>>'{selection,target_section,draft_id}'=%s
                     AND i.manifest#>>'{selection,target_section,section_id}'=%s
                   ORDER BY i.manifest->>'saved_at' DESC,d.id DESC LIMIT %s""",
                (bid, str(section), str(draft), str(section), MAX_TEMPLATES + 1),
            ).fetchall()
            if available
            else []
        )
    except QueryCanceled as error:
        raise DomainError(
            "TECHNICAL_CHAPTER_TEMPLATE_READ_TIMEOUT",
            "读取固定编写模板超时，未返回不完整的记录。",
            503,
        ) from error
    items = [checked_item(row, head, bid, draft, section) for row in rows[:MAX_TEMPLATES]]
    return TechnicalChapterTemplatePage(
        bid_id=bid,
        draft_id=draft,
        section_id=section,
        observed_snapshot_id=head["snapshot_id"],
        observed_draft_revision=head["draft_revision"],
        observed_section_revision=head["section_revision"],
        available=available,
        items=items,
        has_more=len(rows) > MAX_TEMPLATES,
    )
