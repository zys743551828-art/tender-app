import type {
  AssistantAction,
  RunView,
  TaskAuthoringResult,
} from "./contracts";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";

export const taskAuthoringScope =
  "本次沿用章节与来源版本输入；来源在受理时由现有编制流程解析，尚未绑定固定整包、需求清单与执行输入。";

export function claimsTaskAuthoring(run: RunView) {
  const frozen = run.frozen_manifest;
  return (
    frozen.task_kind === "chapter_suggestion" ||
    (recordObject(frozen.configuration) &&
      frozen.configuration.task_kind === "chapter_suggestion") ||
    "authoring_binding" in frozen ||
    (recordObject(run.result) &&
      run.result.schema === "task-authoring-result/1")
  );
}

/** Check the returned identities; the server verifies retained native bytes. */
export function readTaskAuthoringResult(
  run: RunView,
  bidId: string,
  runId: string,
): TaskAuthoringResult {
  const fail = () => {
    throw new Error(
      "章节任务与原生输入、发布结果的关联未通过核验，暂不显示提案。请刷新任务状态。",
    );
  };
  const frozen = run.frozen_manifest;
  const context = frozen.context;
  const config = frozen.configuration;
  const result = run.result;
  if (
    run.id !== runId ||
    run.bid_id !== bidId ||
    !executionId(run.id) ||
    !executionId(run.bid_id) ||
    frozen.schema !== "task-run/1" ||
    frozen.task_kind !== "chapter_suggestion" ||
    frozen.purpose !== "assist" ||
    frozen.formal_decisions_allowed !== false ||
    run.formal_decisions_created !== false ||
    run.definition_version_id !== frozen.definition_version_id ||
    !recordObject(config) ||
    config.task_kind !== "chapter_suggestion" ||
    !recordObject(config.source_selection) ||
    !["current_project", "selected_versions"].includes(
      String(config.source_selection.mode),
    ) ||
    !recordObject(context) ||
    !recordObject(context.section) ||
    !recordObject(result) ||
    !exactKeys(result, [
      "schema",
      "job_id",
      "job_input_digest",
      "writing_plan_id",
      "operation_id",
      "job_ref",
      "section_id",
      "base_section_revision",
      "publication_state",
      "candidate_digest",
      "action_id",
      "action_ref",
      "source_scope",
      "automatic_apply",
    ]) ||
    result.schema !== "task-authoring-result/1" ||
    result.source_scope !== "legacy_section_and_source_versions" ||
    result.automatic_apply !== false ||
    ![
      result.job_id,
      result.writing_plan_id,
      result.operation_id,
      result.section_id,
    ].every(executionId) ||
    !executionSha(result.job_input_digest) ||
    result.job_id !== frozen.assistant_job_id ||
    result.job_ref !== `/api/v1/assistant/jobs/${result.job_id}` ||
    result.operation_id !== run.root_operation_id ||
    run.final_operation_id !== null ||
    result.section_id !== context.section.id ||
    result.section_id !== config.section_id ||
    result.base_section_revision !== context.section.head_revision ||
    !Number.isSafeInteger(result.base_section_revision) ||
    Number(result.base_section_revision) < 1 ||
    (result.candidate_digest !== null && !executionSha(result.candidate_digest))
  )
    return fail();

  const binding = frozen.authoring_binding;
  if (
    binding !== undefined &&
    (!recordObject(binding) ||
      binding.schema !== "task-authoring-binding/1" ||
      binding.job_id !== result.job_id ||
      binding.job_input_digest !== result.job_input_digest ||
      binding.writing_plan_id !== result.writing_plan_id ||
      binding.operation_id !== result.operation_id ||
      !executionSha(binding.writing_plan_digest) ||
      !executionId(binding.native_command_id) ||
      !executionId(binding.native_actor_id))
  )
    return fail();

  const states: Record<
    TaskAuthoringResult["publication_state"],
    RunView["state"][]
  > = {
    pending: [
      "queued",
      "running",
      "cancel_requested",
      "cancelled",
      "failed",
      "reconciliation_required",
      "awaiting_publication",
    ],
    published: ["succeeded", "reconciliation_required"],
    stale: ["superseded", "reconciliation_required"],
    failed: ["failed", "reconciliation_required"],
  };
  const publication = result.publication_state;
  if (
    typeof publication !== "string" ||
    !Object.hasOwn(states, publication) ||
    !states[publication as TaskAuthoringResult["publication_state"]].includes(
      run.state,
    )
  )
    return fail();
  if (
    (publication !== "pending" || run.state === "awaiting_publication") &&
    !executionSha(result.candidate_digest)
  )
    return fail();
  if (publication === "published") {
    if (
      !executionId(result.action_id) ||
      result.action_ref !== `/api/v1/assistant/actions/${result.action_id}`
    )
      return fail();
  } else if (result.action_id !== null || result.action_ref !== null)
    return fail();
  return result as TaskAuthoringResult;
}

export type TaskAuthoringProposal = AssistantAction & {
  preview: Extract<AssistantAction["preview"], { kind: "authoring_patch" }>;
};

/** A fixed action link is displayed only for the task's actual project/job/section. */
export function readTaskAuthoringProposal(
  value: AssistantAction,
  result: TaskAuthoringResult,
  bidId: string,
): TaskAuthoringProposal {
  if (
    !value ||
    result.publication_state !== "published" ||
    value.action_id !== result.action_id ||
    value.job_id !== result.job_id ||
    value.target_bid_id !== bidId ||
    value.tool !== "authoring.apply_patch" ||
    value.formal_scoring_input !== false ||
    !executionSha(value.request_digest) ||
    !Number.isSafeInteger(value.revision) ||
    value.revision < 1 ||
    !["pending", "executed", "rejected", "expired", "stale", "failed"].includes(
      value.state,
    ) ||
    !value.preview ||
    value.preview.kind !== "authoring_patch" ||
    value.preview.section_id !== result.section_id ||
    value.preview.base_section_revision !== result.base_section_revision ||
    !recordObject(value.preview.before) ||
    !recordObject(value.preview.after)
  )
    throw new Error(
      "原生提案与本任务的项目、章节或原始 job 不一致，未展示其他提案。",
    );
  return value as TaskAuthoringProposal;
}

export function taskAuthoringProjection(
  run: RunView | undefined,
  bidId: string,
  id: string,
) {
  if (!run || !claimsTaskAuthoring(run)) return null;
  try {
    return { result: readTaskAuthoringResult(run, bidId, id), error: null };
  } catch (error) {
    return { result: null, error };
  }
}
