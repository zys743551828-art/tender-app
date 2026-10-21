"""Strict template configuration; instructions remain data and do not grant tools."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.tasks.scheduling import Schedule


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Trigger(StrictModel):
    mode: Literal["manual", "material_updated", "schedule"] = "manual"
    cron: str | None = None
    timezone: str = "Asia/Shanghai"

    @model_validator(mode="after")
    def valid_schedule(self):
        if self.mode == "schedule":
            parsed = Schedule.parse(self.cron, self.timezone)
            self.cron = parsed.cron
        elif self.cron is not None:
            raise ValueError("只有显式定时触发可设置cron")
        else:
            # Validate the timezone even before a template gains a schedule.
            Schedule.parse("0 0 * * *", self.timezone)
        return self


class SourceSelection(StrictModel):
    mode: Literal["current_project", "selected_versions"] = "current_project"
    version_ids: list[UUID] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def exact_selection(self):
        if len(set(self.version_ids)) != len(self.version_ids):
            raise ValueError("来源版本不可重复")
        if (self.mode == "selected_versions") != bool(self.version_ids):
            raise ValueError("指定来源须提供实际版本；当前项目不接受额外版本列表")
        return self


class PackageReviewSelection(StrictModel):
    package_id: UUID
    revision_id: UUID
    inventory_id: UUID
    frozen_input_id: UUID
    frozen_input_digest: str = Field(pattern="^[0-9a-f]{64}$")
    execution_input_id: UUID
    execution_input_digest: str = Field(pattern="^[0-9a-f]{64}$")
    dependency_plan_id: UUID
    dependency_plan_digest: str = Field(pattern="^[0-9a-f]{64}$")
    method_digest: str = Field(pattern="^[0-9a-f]{64}$")


class ExactPackageReviewSelection(StrictModel):
    mode: Literal["exact_package_review"]
    input: PackageReviewSelection


class ExactPackageTriggerSelection(StrictModel):
    mode: Literal["exact_package_trigger"]
    input: PackageReviewSelection


def legacy_source_default(value):
    """Keep the original omitted-mode request semantics before union dispatch."""
    if isinstance(value, dict) and isinstance(value.get("source_selection"), dict):
        source = value["source_selection"]
        if "mode" not in source:
            return {**value, "source_selection": {"mode": "current_project", **source}}
    return value


class TemplateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=200, pattern=r"\S")
    task_kind: Literal["denial_check", "scoring_review", "supplement_impact", "chapter_suggestion"]
    instructions: str = Field(min_length=1, max_length=8000, pattern=r"\S")
    section_id: UUID | None = None
    source_selection: (
        SourceSelection | ExactPackageReviewSelection | ExactPackageTriggerSelection
    ) = Field(default_factory=SourceSelection, discriminator="mode")
    trigger: Trigger = Field(default_factory=Trigger)

    @model_validator(mode="before")
    @classmethod
    def legacy_source(cls, value):
        return legacy_source_default(value)

    @model_validator(mode="after")
    def exact_target(self):
        if (self.task_kind == "chapter_suggestion") != (self.section_id is not None):
            raise ValueError("章节建议须指定真实章节；其他任务以项目当前正文为目标")
        if isinstance(self.source_selection, ExactPackageReviewSelection) and (
            self.task_kind != "denial_check" or self.trigger.mode != "manual"
        ):
            raise ValueError("精确整包输入仅用于手动否决及强制项范围核查，不自动触发或用于其他任务")
        if isinstance(self.source_selection, ExactPackageTriggerSelection) and (
            self.task_kind != "denial_check" or self.trigger.mode == "manual"
        ):
            raise ValueError("整包自动触发须显式选择事件或定时，只唤醒已保存的确切否决核查输入")
        return self


class PauseRequest(StrictModel):
    paused: bool = Field(strict=True)


class TemplateView(StrictModel):
    id: UUID
    bid_id: UUID
    revision: int = Field(ge=1)
    version_id: UUID
    digest: str = Field(pattern="^[0-9a-f]{64}$")
    purpose: Literal["assist", "compliance"]
    paused: bool
    configuration: TemplateRequest
    next_run_at: datetime | None
    run_created: Literal[False]
    active_runs_cancelled: Literal[False]


class TemplatePage(StrictModel):
    items: list[TemplateView]
    next_cursor: str | None
    has_more: bool


class TemplateSnapshotConfig(StrictModel):
    schema_version: Literal["task-template/1"] = Field(alias="schema")
    definition: TemplateRequest
    paused: bool
    formal_decisions_allowed: Literal[False]


class TemplateVersionView(StrictModel):
    id: UUID
    bid_id: UUID
    definition_id: UUID
    revision: int = Field(ge=1)
    instructions: str
    config: TemplateSnapshotConfig
    digest: str = Field(pattern="^[0-9a-f]{64}$")


class RunRequest(StrictModel):
    rerun: bool = Field(default=False, strict=True)


class TaskAuthoringResult(StrictModel):
    schema_version: Literal["task-authoring-result/1"] = Field(alias="schema")
    job_id: UUID
    job_input_digest: str = Field(pattern="^[0-9a-f]{64}$")
    writing_plan_id: UUID
    operation_id: UUID
    job_ref: str
    section_id: UUID
    base_section_revision: int = Field(ge=1)
    publication_state: Literal["pending", "published", "stale", "failed"]
    candidate_digest: str | None = Field(pattern="^[0-9a-f]{64}$")
    action_id: UUID | None
    action_ref: str | None
    source_scope: Literal["legacy_section_and_source_versions"]
    automatic_apply: Literal[False]


class RunView(StrictModel):
    id: UUID
    bid_id: UUID
    definition_version_id: UUID
    root_operation_id: UUID
    final_operation_id: UUID | None
    state: Literal[
        "queued",
        "running",
        "cancel_requested",
        "succeeded",
        "failed",
        "cancelled",
        "awaiting_review",
        "awaiting_publication",
        "blocked",
        "superseded",
        "unknown",
        "reconciliation_required",
    ]
    stage: Literal["preparation", "review", "execution"]
    frozen_manifest: dict
    result: TaskAuthoringResult | dict | None
    error_code: str | None
    formal_decisions_created: Literal[False]
    coverage: Literal["registered_effectivity_only_semantic_unknown", "not_formal_score"]


class RunPage(StrictModel):
    items: list[RunView]
    next_after: UUID | None


class PackageTaskManualCapabilities(StrictModel):
    available: bool
    reason: str | None
    input_mode: Literal["exact_package_review"]
    method_digest: str = Field(pattern="^[0-9a-f]{64}$")
    trigger: Literal["manual"]
    overall_coverage: Literal["partial"]
    formal_scoring_eligible: Literal[False]
    submission_eligible: Literal[False]
    automatic_input_selection: Literal[False]


class PackageTaskTriggerCapabilities(StrictModel):
    available: bool
    reason: str | None
    input_mode: Literal["exact_package_trigger"]
    triggers: list[Literal["material_updated", "schedule"]]
    requires_independent_runner: Literal[True]
    automatic_input_selection: Literal[False]
    automatic_catchup_runs: Literal[0]


class TaskKindView(StrictModel):
    task_kind: Literal["denial_check", "scoring_review", "supplement_impact", "chapter_suggestion"]
    name: str
    purpose: Literal["compliance", "assist"]
    execution: Literal[
        "unavailable",
        "partial",
        "existing_review_control_plane",
        "existing_authoring_proposal_queue",
    ]
    reason: str | None = None
    formal_scoring_eligible: Literal[False] | None = None
    coverage: Literal["registered_effectivity_only"] | None = None
    semantic_impact_coverage: Literal["unknown"] | None = None
    formal_decisions_allowed: Literal[False] | None = None
    automatic_apply: Literal[False] | None = None
    exact_package_manual: PackageTaskManualCapabilities | None = None
    exact_package_triggers: PackageTaskTriggerCapabilities | None = None


class TaskKindPage(StrictModel):
    items: list[TaskKindView]
    default_trigger: Literal["manual"]
    saving_preset_creates_run: Literal[False]


class TaskNotificationPayload(StrictModel):
    key: str
    run_id: UUID
    state: str
    error_code: str | None
    run_ref: str


class TaskNotification(StrictModel):
    id: UUID
    payload: TaskNotificationPayload
    created_at: datetime


class TaskNotificationPage(StrictModel):
    items: list[TaskNotification]
    next_after: UUID | None


class MissedTaskSchedule(StrictModel):
    from_at: datetime = Field(alias="from")
    through: datetime
    count: None
    count_status: Literal["not_enumerated"]
    resolution: Literal["skipped_run_current_once_available", "skipped_reconfirm_exact_input"]


class TaskScheduleRecoveryPayload(StrictModel):
    schedule_id: UUID
    definition_id: UUID
    run_current_once_ref: str | None
    reconfirm_template_ref: str | None = None
    definition_version_id: UUID
    next_fire_at: datetime
    missed: MissedTaskSchedule | None
    automatic_catchup_runs: Literal[0]


class TaskScheduleRecovery(StrictModel):
    id: UUID
    payload: TaskScheduleRecoveryPayload
    created_at: datetime


class TaskScheduleRecoveryPage(StrictModel):
    items: list[TaskScheduleRecovery]
    next_after: UUID | None
    run_current_once_supported: Literal[True]


class PackageTriggerIntentView(StrictModel):
    id: UUID
    bid_id: UUID
    definition_id: UUID
    definition_version_id: UUID
    trigger: Literal["material_updated", "schedule"]
    trigger_event_id: UUID | None
    scheduled_at: datetime | None
    created_at: datetime
    selection: PackageReviewSelection
    input_digest: str = Field(pattern="^[0-9a-f]{64}$")
    state: Literal["pending", "accepted", "blocked", "cancelled"]
    error_code: str | None
    run_id: UUID | None
    run_ref: str | None
    reused: bool
    automatic_input_selection: Literal[False]


class PackageTriggerIntentPage(StrictModel):
    items: list[PackageTriggerIntentView]
    next_after: UUID | None


class CancelPackageTriggerIntent(StrictModel):
    reason: str = Field(min_length=1, max_length=1000, pattern=r"\S")
