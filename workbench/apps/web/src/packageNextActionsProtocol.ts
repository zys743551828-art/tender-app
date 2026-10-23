import type {
  PackageNextActions,
  PackageWorkContext,
  PackageReviewRunView,
} from "./contracts";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
import { contextTime } from "./workContextProtocol";

export type NextActionSource = PackageWorkContext | PackageReviewRunView;

/** Inputs have passed their respective exact-identity validator before use. */
export function nextActionSelection(source: NextActionSource) {
  if ("selection" in source)
    return source.selection.kind === "package_review_run"
      ? source.selection
      : null;
  return {
    ...source.scope,
    run_id: source.id,
    input_digest: source.input_digest,
    result_digest: source.result?.digest ?? null,
    frozen_input_id: source.frozen_input_id,
    frozen_input_digest: source.frozen_input_digest,
    execution_input_id: source.execution_input_id,
    execution_input_digest: source.execution_input_digest,
    dependency_plan_id: source.dependency_plan_id,
    dependency_plan_digest: source.dependency_plan_digest,
    method_digest: source.method_digest,
  };
}

const count = (value: unknown): value is number =>
  Number.isSafeInteger(value) && Number(value) >= 0 && Number(value) <= 400;
const levels: Record<string, number> = {
  inspect_changed_basis: 1,
  inspect_unknown_basis: 1,
  view_archived_run: 1,
  inspect_failed_run: 2,
  observe_run: 2,
  inspect_coverage_gaps: 2,
  inspect_critical_risks: 3,
  confirm_critical_rules: 4,
  inspect_scoring_scope: 5,
  inspect_advisories: 6,
  inspect_package_limitations: 6,
};

export function checkedPackageNextActions(
  raw: unknown,
  source: NextActionSource,
): PackageNextActions {
  const invalid = () =>
    new Error("下一步与明确选择的核查身份、计数或依据不一致，请重读同一记录。");
  const selected = nextActionSelection(source);
  if (!selected) throw invalid();
  const expected = {
    run_id: selected.run_id,
    input_digest: selected.input_digest,
    result_digest: selected.result_digest,
    frozen_input_id: selected.frozen_input_id,
    frozen_input_digest: selected.frozen_input_digest,
    execution_input_id: selected.execution_input_id,
    execution_input_digest: selected.execution_input_digest,
    dependency_plan_id: selected.dependency_plan_id,
    dependency_plan_digest: selected.dependency_plan_digest,
    method_digest: selected.method_digest,
  };
  if (
    !recordObject(raw) ||
    raw.version !== "package-next-actions/1" ||
    !recordObject(raw.binding) ||
    !exactKeys(raw.binding, ["scope", ...Object.keys(expected)]) ||
    !recordObject(raw.binding.scope) ||
    !exactKeys(raw.binding.scope, [
      "bid_id",
      "package_id",
      "revision_id",
      "inventory_id",
    ]) ||
    !Object.entries(expected).every(
      ([key, value]) => (raw.binding as Record<string, unknown>)[key] === value,
    ) ||
    !["bid_id", "package_id", "revision_id", "inventory_id"].every(
      (key) =>
        (raw.binding as { scope: Record<string, unknown> }).scope[key] ===
        selected[
          key as "bid_id" | "package_id" | "revision_id" | "inventory_id"
        ],
    ) ||
    !executionSha(raw.method_digest) ||
    !executionSha(raw.confirmation_digest) ||
    !executionSha(raw.basis_digest) ||
    !executionSha(raw.observation_digest) ||
    !contextTime(raw.observed_at) ||
    !["matched", "changed", "unknown", "archived"].includes(
      String(raw.basis_status),
    ) ||
    raw.action_mode !== "navigation_only" ||
    raw.perspective !== "selected_declared_scope" ||
    ![
      "original_bytes_reverified",
      "inventory_complete",
      "formal_scoring_eligible",
      "submission_eligible",
    ].every((key) => raw[key] === false) ||
    !Array.isArray(raw.other_actions) ||
    raw.other_actions.length > 5 ||
    !Array.isArray(raw.basis_issues) ||
    raw.basis_issues.length > 12
  )
    throw invalid();
  const seen = new Set<string>();
  let previous = 0;
  for (const action of [raw.primary, ...raw.other_actions]) {
    if (
      !recordObject(action) ||
      typeof action.key !== "string" ||
      typeof action.level !== "number" ||
      levels[action.key] !== action.level ||
      action.level <= previous ||
      typeof action.title !== "string" ||
      !action.title.trim() ||
      action.title.length > 200 ||
      !Array.isArray(action.requirement_ids) ||
      action.requirement_ids.length > 400 ||
      !action.requirement_ids.every((id) => executionId(id) && !seen.has(id)) ||
      new Set(action.requirement_ids).size !== action.requirement_ids.length ||
      action.item_count !==
        (action.requirement_ids.length ? action.requirement_ids.length : null)
    )
      throw invalid();
    action.requirement_ids.forEach((id) => seen.add(String(id)));
    previous = action.level;
  }
  const historical = raw.historical_scope_counts;
  const original =
    "selection" in source
      ? source.summary.review
      : source.result && {
          requirement_count: source.result.manifest.requirement_count,
          machine_counts: source.result.manifest.counts,
        };
  if (
    !("selection" in source) &&
    source.result &&
    [...seen].some(
      (id) =>
        !source.result!.manifest.matrix.some(
          (row) => row.requirement_id === id,
        ),
    )
  )
    throw invalid();
  if (!recordObject(raw.primary)) throw invalid();
  const basisAction = {
    changed: "inspect_changed_basis",
    unknown: "inspect_unknown_basis",
    archived: "view_archived_run",
  };
  if (
    raw.basis_status !== "matched" &&
    (raw.primary.key !==
      basisAction[raw.basis_status as keyof typeof basisAction] ||
      raw.other_actions.length)
  )
    throw invalid();
  if (
    selected.result_digest === null
      ? historical !== null
      : !recordObject(historical) ||
        !count(historical.critical) ||
        !count(historical.suggestions)
  )
    throw invalid();
  if (!("selection" in source) && source.result) {
    const negative = source.result.manifest.matrix.filter((row) =>
      ["violated", "not_found", "unable_to_judge"].includes(row.verdict),
    );
    const critical = negative.filter((row) =>
      ["disqualification", "mandatory"].includes(row.rule_kind),
    ).length;
    if (
      !recordObject(historical) ||
      historical.critical !== critical ||
      historical.suggestions !== negative.length - critical
    )
      throw invalid();
  }
  if (
    selected.result_digest !== null &&
    (!original ||
      !recordObject(historical) ||
      Number(historical.critical) + Number(historical.suggestions) !==
        original.machine_counts.violated +
          original.machine_counts.not_found +
          original.machine_counts.unable_to_judge ||
      seen.size > original.requirement_count)
  )
    throw invalid();
  if (raw.basis_status === "matched" && selected.result_digest !== null) {
    const current = raw.current_scope_counts;
    if (
      !recordObject(current) ||
      !count(current.critical) ||
      !count(current.suggestions) ||
      !count(current.pending_critical_rules) ||
      (current.critical > 0 && Number(raw.primary.level) > 3) ||
      (current.pending_critical_rules > 0 && Number(raw.primary.level) > 4) ||
      (original &&
        current.pending_critical_rules > original.requirement_count) ||
      !recordObject(historical) ||
      current.critical !== historical.critical ||
      current.suggestions !== historical.suggestions ||
      !count(raw.remaining_critical_count) ||
      (original && raw.remaining_critical_count > original.requirement_count) ||
      !count(raw.remaining_suggestion_count) ||
      raw.remaining_suggestion_count > current.suggestions ||
      raw.basis_issues.length
    )
      throw invalid();
  } else if (
    raw.current_scope_counts !== null ||
    raw.remaining_critical_count !== null ||
    raw.remaining_suggestion_count !== null
  )
    throw invalid();
  if (
    !raw.basis_issues.every(
      (issue) =>
        recordObject(issue) &&
        typeof issue.dimension === "string" &&
        ["changed", "unknown"].includes(String(issue.status)) &&
        typeof issue.message === "string" &&
        !!issue.message.trim() &&
        issue.message.length <= 200,
    )
  )
    throw invalid();
  return raw as unknown as PackageNextActions;
}
