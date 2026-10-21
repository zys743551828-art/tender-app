import type { ExactPackageReviewSelection, RunView } from "./contracts";
import type {
  ExactPackageTriggerSelection,
  TemplateRequest,
} from "./taskTriggerContracts";
import { recordObject } from "./executionInputValidation";
export function isExactPackageTask(
  configuration: TemplateRequest,
): configuration is TemplateRequest & {
  source_selection: ExactPackageReviewSelection | ExactPackageTriggerSelection;
} {
  return (
    configuration.source_selection?.mode === "exact_package_review" ||
    configuration.source_selection?.mode === "exact_package_trigger"
  );
}
export const exactPackageTaskScope =
  "只核查明确选择的整包修订、需求清单、冻结输入和依赖计划；范围覆盖仍为部分，不授予正式评分或提交资格。";
/** Equality for the read-only form scope, never an authorization decision. */
export function sameTaskPackageSource(a: TemplateRequest, b: TemplateRequest) {
  if (!isExactPackageTask(a) || !isExactPackageTask(b)) return false;
  const left = a.source_selection.input;
  const right = b.source_selection.input;
  return (
    left != null &&
    right != null &&
    Object.keys(left).length === Object.keys(right).length &&
    Object.entries(left).every(
      ([key, value]) =>
        Object.prototype.hasOwnProperty.call(right, key) &&
        right[key as keyof typeof right] === value,
    )
  );
}
/** A claimed package subject must pass package validation; it cannot fall back to single-body UI. */
export function claimsExactPackageRun(value: RunView) {
  const manifest = value.frozen_manifest;
  if (!recordObject(manifest)) return false;
  const context = manifest.context;
  const config = manifest.configuration;
  return (
    manifest.schema === "task-package-run/1" ||
    manifest.schema === "task-package-trigger-run/1" ||
    (recordObject(context) &&
      recordObject(context.subject) &&
      context.subject.kind === "bid_package") ||
    (recordObject(config) &&
      recordObject(config.source_selection) &&
      ["exact_package_review", "exact_package_trigger"].includes(
        String(config.source_selection.mode),
      )) ||
    (recordObject(value.result) &&
      value.result.kind === "declared_package_scope_review")
  );
}
export const taskNames: Record<TemplateRequest["task_kind"], string> = {
  denial_check: "否决核对",
  scoring_review: "评分核对",
  supplement_impact: "已登记补遗关系核对",
  chapter_suggestion: "章节修改建议",
};
export const taskScopes: Record<TemplateRequest["task_kind"], string> = {
  denial_check:
    "须由统一输入守卫与评审控制面实际接受；未就绪保持未完成，不生成假通过。",
  scoring_review:
    "正式评分资格尚未就绪时拒绝运行，不以聊天片段代替完整输入与三次判断。",
  supplement_impact:
    "仅核对已登记效力关系，不进行语义影响检查；运行后仍须分别核对实际处理结果。",
  chapter_suggestion:
    "只产出章节修改提案，须原文差异预览后明确采纳，不自动改稿。",
};
export const taskRunNames: Record<RunView["state"], string> = {
  queued: "等待处理",
  running: "正在处理",
  cancel_requested: "正在取消",
  succeeded: "已记录处理结果",
  failed: "执行失败",
  cancelled: "已取消",
  awaiting_review: "等待后续核对",
  blocked: "受阻，尚未完成",
  superseded: "原输入已过期",
  unknown: "结果或费用未知",
  reconciliation_required: "需核对调用账本",
};
export function newTaskConfiguration(): TemplateRequest {
  return {
    name: "",
    task_kind: "supplement_impact",
    instructions: "",
    section_id: null,
    source_selection: { mode: "current_project", version_ids: [] },
    trigger: { mode: "manual", cron: null, timezone: "Asia/Shanghai" },
  };
}
export function triggerDescription(trigger: TemplateRequest["trigger"]) {
  if (!trigger || trigger.mode === "manual") return "仅手动运行";
  if (trigger.mode === "material_updated") return "资料实际入库更新后触发";
  return `明确定时：${trigger.cron ?? "尚未设置"} · ${trigger.timezone ?? "Asia/Shanghai"}`;
}
