"""Status of exact saved runs for one version of a chapter template; never a launch."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from psycopg.errors import QueryCanceled
from pydantic import BaseModel, ConfigDict, Field

from packages.authoring import package_input_repository
from packages.authoring.package_job_authority import available as jobs_available
from packages.authoring.technical_chapter_templates import checked_item, observed_chapter_head
from packages.domain.runtime import DomainError, fetch
from packages.tasks import package_authoring_result

MAX_RUNS = 3

RunStage = Literal[
    "queued",
    "running",
    "cancel_requested",
    "awaiting_publication",
    "candidate_published",
    "failed",
    "cancelled",
    "superseded",
    "reconciliation_required",
    "unverified",
]


class TechnicalChapterRunItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    recorded_at: datetime
    stage: RunStage


class TechnicalChapterRunPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bid_id: UUID
    draft_id: UUID
    section_id: UUID
    template_id: UUID
    template_version_id: UUID
    template_digest: str = Field(pattern="^[a-f0-9]{64}$")
    input_id: UUID
    input_digest: str = Field(pattern="^[a-f0-9]{64}$")
    available: bool
    has_more: bool
    items: list[TechnicalChapterRunItem] = Field(max_length=MAX_RUNS)


def read(c, bid, draft, section, version_id):
    c.execute("SET LOCAL statement_timeout = '5s'")
    try:
        head = observed_chapter_head(c, bid, draft, section)
        package_input_repository.require_schema(c)
        selection = fetch(
            c,
            """SELECT d.id AS template_id,v.id AS template_version_id,
                      v.revision AS template_revision,v.digest AS template_digest,v.config,
                      v.config->'paused' AS paused,i.id AS input_id,i.digest AS input_digest,
                      i.manifest AS input_manifest
               FROM design.task_definition_versions v
               JOIN design.task_definitions d ON d.bid_id=v.bid_id AND d.id=v.definition_id
               JOIN design.authoring_package_inputs i ON i.bid_id=v.bid_id
                 AND i.id::text=v.config#>>'{definition,source_selection,input,authoring_input_id}'
               WHERE v.bid_id=%s AND v.id=%s
                 AND v.config#>>'{definition,task_kind}'='chapter_suggestion'
                 AND v.config#>>'{definition,source_selection,mode}'='exact_package_authoring'
                 AND v.config#>>'{definition,section_id}'=%s
                 AND i.manifest#>>'{selection,target_section,draft_id}'=%s
                 AND i.manifest#>>'{selection,target_section,section_id}'=%s""",
            (bid, version_id, str(section), str(draft), str(section)),
        )
        template = checked_item(selection, head, bid, draft, section)
        available = jobs_available(c)
        rows = (
            c.execute(
                """SELECT run.*,op.created_at AS recorded_at
                   FROM design.authoring_package_job_bindings b
                   JOIN design.task_runs run ON run.id=b.task_run_id AND run.bid_id=b.bid_id
                       AND run.definition_version_id=b.definition_version_id
                   JOIN design.operations op ON op.id=run.operation_id AND op.bid_id=b.bid_id
                   WHERE b.bid_id=%s AND b.definition_version_id=%s
                       AND b.input_id=%s AND b.input_digest=%s
                   ORDER BY op.created_at DESC,run.id DESC LIMIT %s""",
                (bid, version_id, template.input_id, template.input_digest, MAX_RUNS + 1),
            ).fetchall()
            if available
            else []
        )
        items = [
            TechnicalChapterRunItem(
                run_id=row["id"],
                recorded_at=row["recorded_at"].astimezone(UTC),
                stage=run_stage(c, row, template, section),
            )
            for row in rows[:MAX_RUNS]
        ]
    except QueryCanceled as error:
        raise DomainError(
            "TECHNICAL_CHAPTER_RUNS_READ_TIMEOUT",
            "固定运行目录核对超时，未显示不完整的记录。",
            503,
        ) from error
    return TechnicalChapterRunPage(
        bid_id=bid,
        draft_id=draft,
        section_id=section,
        template_id=template.template_id,
        template_version_id=template.template_version_id,
        template_digest=template.template_digest,
        input_id=template.input_id,
        input_digest=template.input_digest,
        available=available,
        has_more=len(rows) > MAX_RUNS,
        items=items,
    )


def run_stage(c, row, template, section) -> RunStage:
    # This is the same read projection used by the exact run, including its
    # write-plan, model billing, immutable candidate and publication proofs.
    state, _, result = package_authoring_result.project(c, row)
    if (
        result is None
        or result["section_id"] != str(section)
        or result["base_section_revision"] != template.input_section_revision
        or result["authoring_input_id"] != str(template.input_id)
        or result["authoring_input_digest"] != template.input_digest
    ):
        return "unverified"
    if state == "reconciliation_required":
        return "reconciliation_required"
    if state == "succeeded":
        return (
            "candidate_published"
            if result["publication_state"] == "published" and result["action_id"]
            else "unverified"
        )
    if state == "queued":
        return "queued"
    if state == "running":
        return "running"
    if state == "cancel_requested":
        return "cancel_requested"
    if state == "awaiting_publication":
        return "awaiting_publication"
    if state == "failed":
        return "failed"
    if state == "cancelled":
        return "cancelled"
    if state == "superseded":
        return "superseded"
    return "unverified"
