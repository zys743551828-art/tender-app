import type {
  PackageDependencyPlanView,
  PackageTaskManualCapabilities,
  TaskKindPage,
  TemplateRequest,
} from "./contracts";
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
