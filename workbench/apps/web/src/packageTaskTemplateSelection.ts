import type {
  PackageDependencyPlanView,
  PackageTaskManualCapabilities,
} from "./contracts";
import type {
  PackageTaskTriggerCapabilities,
  TaskKindPage,
  TemplateRequest,
} from "./taskTriggerContracts";
import { validatePlan } from "./dependencyPlanProtocol";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
  validateExecutionInput,
} from "./executionInputValidation";
import type { DependencyProps } from "./inputDependencyProtocol";
import { validateFrozenInput } from "./packageFrozenInput";

export type PackageTaskSelectionProps = DependencyProps & {
  plan: PackageDependencyPlanView;
};

export function packageTaskCapability(
  value: TaskKindPage,
): PackageTaskManualCapabilities {
  const matches = Array.isArray(value?.items)
    ? value.items.filter(
        (item) => recordObject(item) && item.task_kind === "denial_check",
      )
    : [];
  const capability = matches?.[0]?.exact_package_manual;
  if (
    value?.default_trigger !== "manual" ||
    value.saving_preset_creates_run !== false ||
    matches?.length !== 1 ||
    !recordObject(capability) ||
    !exactKeys(capability, [
      "available",
      "reason",
      "input_mode",
      "method_digest",
      "trigger",
      "overall_coverage",
      "formal_scoring_eligible",
      "submission_eligible",
      "automatic_input_selection",
    ]) ||
    typeof capability.available !== "boolean" ||
    !(capability.reason === null || typeof capability.reason === "string") ||
    capability.input_mode !== "exact_package_review" ||
    !executionSha(capability.method_digest) ||
    capability.trigger !== "manual" ||
    capability.overall_coverage !== "partial" ||
    capability.formal_scoring_eligible !== false ||
    capability.submission_eligible !== false ||
    capability.automatic_input_selection !== false
  )
    throw new Error(
      "整包手动任务的方法或能力边界无法核验，请重新读取任务能力。",
    );
  return capability;
}

export function packageTaskTriggerCapability(
  value: TaskKindPage,
): PackageTaskTriggerCapabilities | null {
  const matches = Array.isArray(value?.items)
    ? value.items.filter((item) => item.task_kind === "denial_check")
    : [];
  const capability = matches[0]?.exact_package_triggers;
  if (capability == null) return null;
  if (
    matches.length !== 1 ||
    value.default_trigger !== "manual" ||
    value.saving_preset_creates_run !== false ||
    !recordObject(capability) ||
    !exactKeys(capability, [
      "available",
      "reason",
      "input_mode",
      "triggers",
      "requires_independent_runner",
      "automatic_input_selection",
      "automatic_catchup_runs",
    ]) ||
    typeof capability.available !== "boolean" ||
    (capability.available
      ? capability.reason !== null
      : typeof capability.reason !== "string" || !capability.reason) ||
    capability.input_mode !== "exact_package_trigger" ||
    !Array.isArray(capability.triggers) ||
    capability.triggers.length !== 2 ||
    new Set(capability.triggers).size !== 2 ||
    !capability.triggers.every(
      (mode) => mode === "material_updated" || mode === "schedule",
    ) ||
    capability.requires_independent_runner !== true ||
    capability.automatic_input_selection !== false ||
    capability.automatic_catchup_runs !== 0
  )
    throw new Error(
      "整包触发能力的输入、独立调度或漏时边界不一致，不能启用自动触发。",
    );
  return capability;
}

export function taskPackageTriggerMissing(
  input: TemplateRequest,
  capability: PackageTaskTriggerCapabilities | null,
) {
  const automatic = input.source_selection?.mode === "exact_package_trigger";
  const trigger = input.trigger;
  if (automatic && !capability?.available) return "服务器明确的整包触发能力";
  if (
    automatic
      ? !["material_updated", "schedule"].includes(trigger?.mode ?? "")
      : trigger?.mode !== "manual"
  )
    return "与固定输入模式一致的明确触发方式";
  if (trigger?.mode === "schedule" && !trigger.cron?.trim())
    return "明确的计划时间";
  if (trigger?.mode !== "schedule" && trigger?.cron != null)
    return "仅定时模式可填写计划时间";
  return null;
}

/** The caller selected these saved records explicitly; never resolve a current/latest input. */
export async function packageTaskConfiguration(
  props: PackageTaskSelectionProps,
  capability: PackageTaskManualCapabilities,
): Promise<TemplateRequest> {
  const { scope, frozen, prepared, plan } = props;
  if (
    !Object.values(scope).every(executionId) ||
    ![frozen.manifest.id, prepared.manifest.id, plan.manifest.id].every(
      executionId,
    ) ||
    ![
      frozen.digest,
      prepared.digest,
      plan.digest,
      capability.method_digest,
    ].every(executionSha) ||
    frozen.manifest.bid_id !== scope.bidId ||
    frozen.manifest.package_id !== scope.packageId ||
    frozen.manifest.revision_id !== scope.revisionId ||
    frozen.manifest.inventory_id !== scope.inventoryId
  )
    throw new Error(
      "所选冻结输入或执行准备的身份、摘要不一致，未创建任务表单。",
    );
  await validateFrozenInput(frozen, scope, frozen.manifest.id);
  await validateExecutionInput(prepared, scope, frozen, prepared.manifest.id);
  await validatePlan(plan, props);
  return {
    name: "整包范围核查",
    task_kind: "denial_check",
    instructions:
      "核对明确选定的整包、冻结要求和依赖计划，逐条保留原文依据与无法判断项。",
    section_id: null,
    source_selection: {
      mode: "exact_package_review",
      input: {
        package_id: scope.packageId,
        revision_id: scope.revisionId,
        inventory_id: scope.inventoryId,
        frozen_input_id: frozen.manifest.id,
        frozen_input_digest: frozen.digest,
        execution_input_id: prepared.manifest.id,
        execution_input_digest: prepared.digest,
        dependency_plan_id: plan.manifest.id,
        dependency_plan_digest: plan.digest,
        method_digest: capability.method_digest,
      },
    },
    trigger: { mode: "manual", cron: null, timezone: "Asia/Shanghai" },
  };
}
