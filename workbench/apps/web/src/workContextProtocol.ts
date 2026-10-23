import type { PackageWorkContext, WorkContextSelection } from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
import type { WorkContextTarget } from "./workContextNavigation";

export type WorkContextRunSelection = Extract<
  WorkContextSelection,
  { kind: "package_review_run" }
>;

const nullable = (value: unknown, test: (v: unknown) => boolean) =>
  value === null || test(value);
const text = (value: unknown): value is string => typeof value === "string";
const count = (value: unknown, maximum = 400): value is number =>
  Number.isSafeInteger(value) && Number(value) >= 0 && Number(value) <= maximum;
const positive = (value: unknown, maximum = Number.MAX_SAFE_INTEGER) =>
  count(value, maximum) && Number(value) > 0;
export const contextTime = (value: unknown): value is string =>
  typeof value === "string" &&
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(
    value,
  ) &&
  Number.isFinite(Date.parse(value));
const member = (value: unknown, choices: readonly string[]) =>
  typeof value === "string" && choices.includes(value);
const keys = (
  value: unknown,
  names: string[],
): value is Record<string, unknown> =>
  recordObject(value) && exactKeys(value, names);
const selectedIds = ["bid_id", "package_id", "revision_id"];
const runIds = [
  "inventory_id",
  "frozen_input_id",
  "execution_input_id",
  "dependency_plan_id",
  "run_id",
];
const runDigests = [
  "package_digest",
  "inventory_digest",
  "frozen_input_digest",
  "execution_input_digest",
  "dependency_plan_digest",
  "input_digest",
  "method_digest",
];
const packageIdentity = (value: Record<string, unknown>, bidId: string) =>
  value.bid_id === bidId &&
  selectedIds.every((key) => executionId(value[key])) &&
  executionSha(value.package_digest);

export function validWorkContextRunSelection(
  value: unknown,
  bidId: string,
): value is WorkContextRunSelection {
  return (
    keys(value, [
      "kind",
      ...selectedIds,
      ...runIds,
      ...runDigests,
      "result_digest",
    ]) &&
    value.kind === "package_review_run" &&
    packageIdentity(value, bidId) &&
    runIds.every((key) => executionId(value[key])) &&
    runDigests.every((key) => executionSha(value[key])) &&
    nullable(value.result_digest, executionSha)
  );
}

export function validWorkContextSelection(
  value: unknown,
  bidId: string,
): value is WorkContextSelection {
  if (validWorkContextRunSelection(value, bidId)) return true;
  if (
    !keys(value, [
      "kind",
      ...selectedIds,
      "package_digest",
      "submission_id",
      "package_binding_digest",
      "inventory",
      "review_run",
    ]) ||
    value.kind !== "package_submission" ||
    !packageIdentity(value, bidId) ||
    !executionId(value.submission_id) ||
    !executionSha(value.package_binding_digest) ||
    !nullable(
      value.inventory,
      (v) =>
        keys(v, ["id", "digest"]) &&
        executionId(v.id) &&
        executionSha(v.digest),
    )
  )
    return false;
  if (value.review_run === null) return true;
  return (
    validWorkContextRunSelection(value.review_run, bidId) &&
    ["package_id", "revision_id", "package_digest"].every(
      (field) =>
        (value.review_run as unknown as Record<string, unknown>)[field] ===
        value[field],
    ) &&
    recordObject(value.inventory) &&
    value.review_run.inventory_id === value.inventory.id &&
    value.review_run.inventory_digest === value.inventory.digest
  );
}

function validIdentity(value: unknown) {
  if (!recordObject(value)) return false;
  const v2 = value.identity_version === "bid-identity/2";
  const names = [
    "bidder_id",
    "bidder_name",
    "round_id",
    "engineering_project_id",
    "engineering_title",
    "region",
    "engineering_type",
    "lot",
    "round_no",
    "binding_status",
    "authority_id",
    "digest",
  ];
  if ("identity_version" in value) names.push("identity_version");
  if (v2) names.push("lot_id");
  return (
    exactKeys(value, names) &&
    ["bidder_id", "round_id", "engineering_project_id"].every((field) =>
      executionId(value[field]),
    ) &&
    ["bidder_name", "engineering_title"].every((field) => text(value[field])) &&
    ["region", "engineering_type", "lot"].every((field) =>
      nullable(value[field], text),
    ) &&
    positive(value.round_no) &&
    member(value.binding_status, ["confirmed", "pending"]) &&
    nullable(value.authority_id, executionId) &&
    executionSha(value.digest) &&
    (!Object.hasOwn(value, "identity_version") ||
      member(value.identity_version, ["bid-identity/1", "bid-identity/2"])) &&
    (!v2 ||
      (nullable(value.lot_id, executionId) &&
        (value.binding_status !== "confirmed" ||
          (executionId(value.lot_id) && executionId(value.authority_id)))))
  );
}

export const workContextDimensions = [
  "identity",
  "package_head",
  "authority_head",
  "inventory_head",
  "rule_set_head",
  "sources",
  "selected_facts",
  "executor_method",
  "submission_head",
  "review_run_head",
  "bound_run_state",
] as const;
export function validContextDimension(value: unknown) {
  return (
    keys(value, ["status", "selected_digest", "observed_digest", "reason"]) &&
    member(value.status, ["matched", "changed", "unknown", "not_applicable"]) &&
    nullable(value.selected_digest, executionSha) &&
    nullable(value.observed_digest, executionSha) &&
    text(value.reason) &&
    value.reason.length > 0 &&
    value.reason.length <= 100
  );
}
const machineStates = [
  "satisfied",
  "violated",
  "not_found",
  "unable_to_judge",
  "not_applicable",
];
const humanStates = ["unreviewed", "confirmed", "rejected", "needs_review"];
function validSummary(value: unknown, selection: WorkContextSelection) {
  if (
    !keys(value, [
      "perspective",
      "review_status",
      "review",
      "whole_package_blocking_risk_count",
      "whole_package_passed",
      "formal_scoring",
      "official_labels_read",
      "primary_action",
      "action_mode",
    ]) ||
    value.perspective !==
      (selection.kind === "package_submission"
        ? "submission_history"
        : "declared_scope_history") ||
    value.whole_package_blocking_risk_count !== null ||
    value.whole_package_passed !== null ||
    value.official_labels_read !== false ||
    value.action_mode !== "navigation_only" ||
    !member(value.primary_action, [
      "open_selected_review",
      "view_selected_operation",
      "inspect_changed_basis",
      "open_selected_submission",
    ]) ||
    !keys(value.formal_scoring, ["status", "scope_id", "numeric_prediction"]) ||
    value.formal_scoring.status !== "scope_not_selected" ||
    value.formal_scoring.scope_id !== null ||
    value.formal_scoring.numeric_prediction !== null
  )
    return false;
  const run =
    selection.kind === "package_review_run" ? selection : selection.review_run;
  if (value.review === null)
    return (
      value.review_status ===
        (selection.kind === "package_review_run"
          ? "run_unfinished"
          : run
            ? "bound_result_missing"
            : "not_selected") &&
      (run === null || run.result_digest === null)
    );
  const review = value.review;
  if (
    !run ||
    !keys(review, [
      "run_id",
      "input_digest",
      "result_digest",
      "requirement_count",
      "machine_counts",
      "human_counts",
      "human_heads_digest",
      "human_basis",
      "matrix_coverage",
      "overall_coverage",
      "inventory_complete",
      "quality_status",
      "risk_resolution_assessed",
    ]) ||
    value.review_status !== "result_available" ||
    review.run_id !== run.run_id ||
    review.input_digest !== run.input_digest ||
    review.result_digest !== run.result_digest ||
    !executionSha(review.result_digest) ||
    !positive(review.requirement_count, 400) ||
    !keys(review.machine_counts, machineStates) ||
    !keys(review.human_counts, humanStates) ||
    !executionSha(review.human_heads_digest) ||
    review.human_basis !== "current_heads_for_exact_result" ||
    !member(review.matrix_coverage, ["partial", "complete"]) ||
    review.overall_coverage !== "partial" ||
    review.inventory_complete !== false ||
    review.quality_status !== "not_measured" ||
    review.risk_resolution_assessed !== false
  )
    return false;
  return [review.machine_counts, review.human_counts].every(
    (values) =>
      Object.values(values).every((n) => count(n)) &&
      Object.values(values).reduce<number>((sum, n) => sum + Number(n), 0) ===
        review.requirement_count,
  );
}
function validTargets(value: unknown, selection: WorkContextSelection) {
  if (
    !keys(value, [
      "package_revision",
      "authority_revision",
      "package_review_run",
      "package_submission",
    ])
  )
    return false;
  const packageTarget = (v: unknown) =>
    keys(v, ["kind", ...selectedIds, "package_digest"]) &&
    v.kind === "package_revision" &&
    packageIdentity(v, selection.bid_id);
  if (
    !packageTarget(value.package_revision) ||
    !nullable(value.authority_revision, packageTarget)
  )
    return false;
  const pkg = value.package_revision as Record<string, unknown>;
  if (
    ![...selectedIds, "package_digest"].every(
      (field) => pkg[field] === selection[field as keyof WorkContextSelection],
    )
  )
    return false;
  const run =
    selection.kind === "package_review_run" ? selection : selection.review_run;
  const target = value.package_review_run;
  if (
    run === null
      ? target !== null
      : !keys(target, [
          "kind",
          ...selectedIds,
          "inventory_id",
          "frozen_input_id",
          "execution_input_id",
          "run_id",
          "input_digest",
          "result_digest",
        ]) ||
        Object.entries(target).some(
          ([field, entry]) =>
            entry !== run[field as keyof WorkContextRunSelection],
        )
  )
    return false;
  return selection.kind === "package_review_run"
    ? value.package_submission === null
    : keys(value.package_submission, [
        "kind",
        "bid_id",
        "submission_id",
        "package_binding_digest",
      ]) &&
        value.package_submission.kind === selection.kind &&
        value.package_submission.bid_id === selection.bid_id &&
        value.package_submission.submission_id === selection.submission_id &&
        value.package_submission.package_binding_digest ===
          selection.package_binding_digest;
}

export async function validatePackageWorkContext(
  value: unknown,
  bidId: string,
  target: WorkContextTarget,
): Promise<PackageWorkContext> {
  const fail = () => {
    throw new Error(
      "所选阶段记录的身份、范围摘要或只读状态不能一致核验，请重新读取原选择。",
    );
  };
  if (
    !keys(value, [
      "version",
      "selection",
      "selection_digest",
      "observed_at",
      "observation_digest",
      "identity",
      "state",
      "current_observation",
      "summary",
      "native_targets",
      "original_bytes_reverified",
      "limitations",
    ]) ||
    value.version !== "package-work-context/1" ||
    !validWorkContextSelection(value.selection, bidId) ||
    value.selection.kind !== target.kind ||
    value.selection_digest !== target.selectionDigest ||
    !executionSha(value.selection_digest) ||
    !contextTime(value.observed_at) ||
    !executionSha(value.observation_digest) ||
    !validIdentity(value.identity) ||
    value.original_bytes_reverified !== false ||
    !Array.isArray(value.limitations) ||
    value.limitations.length > 30 ||
    new Set(value.limitations).size !== value.limitations.length ||
    !value.limitations.every(
      (v) => text(v) && v.length > 0 && v.length <= 100,
    ) ||
    !keys(value.current_observation, [...workContextDimensions]) ||
    !Object.values(value.current_observation).every(validContextDimension)
  )
    return fail();
  const selection = value.selection,
    state = value.state;
  if (
    (selection.kind === "package_review_run"
      ? selection.run_id
      : selection.submission_id) !== target.id ||
    !validSummary(value.summary, selection) ||
    !validTargets(value.native_targets, selection)
  )
    return fail();
  if (selection.kind === "package_review_run") {
    if (
      !keys(state, [
        "kind",
        "operation_id",
        "operation_state",
        "result_available",
      ]) ||
      state.kind !== selection.kind ||
      !executionId(state.operation_id) ||
      !member(state.operation_state, [
        "queued",
        "running",
        "cancel_requested",
        "succeeded",
        "failed",
        "cancelled",
      ]) ||
      state.result_available !== (selection.result_digest !== null) ||
      (state.operation_state === "succeeded") !== state.result_available
    )
      return fail();
  } else if (
    !keys(state, [
      "kind",
      "registration_kind",
      "submitted_at",
      "recorded_at",
      "supersedes_id",
      "gate_checked_at_registration",
      "platform_submission_verified",
      "pre_submission_system_check_verified",
    ]) ||
    state.kind !== selection.kind ||
    !member(state.registration_kind, ["standard", "offline_fact"]) ||
    !contextTime(state.submitted_at) ||
    !contextTime(state.recorded_at) ||
    !nullable(state.supersedes_id, executionId) ||
    typeof state.gate_checked_at_registration !== "boolean" ||
    state.platform_submission_verified !== false ||
    state.pre_submission_system_check_verified !== false
  )
    return fail();
  if ((await jsonDigest(selection)) !== value.selection_digest) return fail();
  const basis = { ...value };
  delete basis.observed_at;
  delete basis.observation_digest;
  if ((await jsonDigest(basis)) !== value.observation_digest) return fail();
  return value as unknown as PackageWorkContext;
}
