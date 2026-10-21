import type {
  PackageReviewComparisonPage,
  PackageReviewComparisonRow,
  PackageReviewComparisonRowSide,
  PackageReviewComparisonRun,
} from "./contracts";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
import { frozenManifestDigest } from "./packageFrozenInput";
import { packageReviewVerdicts } from "./packageReviewProtocol";

export type PackageReviewComparisonRequest = {
  bidId: string;
  leftId: string;
  rightId: string;
};
export const packageReviewComparisonPath = (
  request: PackageReviewComparisonRequest,
  cursor?: string | null,
) =>
  `/bids/${request.bidId}/package-review-comparisons?left_run_id=${request.leftId}&right_run_id=${request.rightId}&limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`;
export const packageReviewComparisonChanges = [
  "run_input",
  "scope",
  "frozen_input",
  "prepared_input",
  "rerun_intent",
  "requirements",
  "submitted_documents",
  "selected_facts",
  "fact_admission",
  "dependency_plan",
  "inventory_proof",
  "method",
] as const;
export const packageReviewComparisonCounts = [
  "added",
  "removed",
  "changed",
  "unchanged",
  "machine_row_changed",
  "verdict_changed",
] as const;
const methodFields = [
  "engine",
  "purpose",
  "assessment",
  "input_scope",
  "model_json_encoding",
  "model",
  "endpoint",
  "source_digest",
  "batch_rule_limit",
  "batch_limit",
  "output_tokens_per_batch",
  "input_character_limit",
  "semantic_quality",
  "formal_scoring_eligible",
  "submission_eligible",
];
const scopeKeys = ["bid_id", "package_id", "revision_id", "inventory_id"];
const text = (v: unknown, max = Infinity): v is string =>
  typeof v === "string" && !!v.trim() && Array.from(v).length <= max;
const texts = (v: unknown, max = 200): v is string[] =>
  Array.isArray(v) &&
  v.every((item) => text(item, max)) &&
  new Set(v).size === v.length;
const count = (v: unknown, max: number): v is number =>
  Number.isSafeInteger(v) && Number(v) >= 0 && Number(v) <= max;
const time = (v: unknown): v is string =>
  typeof v === "string" &&
  /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z$/.test(v) &&
  Number.isFinite(Date.parse(v)) &&
  new Date(v).toISOString().slice(0, 19) === v.slice(0, 19);
const sameScope = (
  left: PackageReviewComparisonRun["scope"],
  right: PackageReviewComparisonRun["scope"],
) =>
  scopeKeys.every(
    (key) =>
      left[key as keyof typeof left] === right[key as keyof typeof right],
  );
function validRun(
  value: unknown,
  bidId: string,
  expectedId: string,
): value is PackageReviewComparisonRun {
  if (
    !recordObject(value) ||
    !exactKeys(value, [
      "id",
      "actor_id",
      "created_at",
      "scope",
      "frozen_input_id",
      "frozen_input_digest",
      "execution_input_id",
      "execution_input_digest",
      "execution_digest",
      "input_digest",
      "method_digest",
      "dependency_plan_id",
      "dependency_plan_digest",
      "result_digest",
      "requirement_count",
      "matrix_coverage",
      "overall_coverage",
      "human_heads_digest",
    ]) ||
    value.id !== expectedId ||
    ![
      value.id,
      value.actor_id,
      value.frozen_input_id,
      value.execution_input_id,
      value.dependency_plan_id,
    ].every(executionId) ||
    !time(value.created_at) ||
    !recordObject(value.scope) ||
    !exactKeys(value.scope, scopeKeys) ||
    value.scope.bid_id !== bidId ||
    !Object.values(value.scope).every(executionId) ||
    ![
      value.frozen_input_digest,
      value.execution_input_digest,
      value.execution_digest,
      value.input_digest,
      value.method_digest,
      value.dependency_plan_digest,
      value.result_digest,
      value.human_heads_digest,
    ].every(executionSha) ||
    !count(value.requirement_count, 400) ||
    value.requirement_count < 1 ||
    !["partial", "complete"].includes(String(value.matrix_coverage)) ||
    value.overall_coverage !== "partial"
  )
    return false;
  return true;
}
function validRowSide(value: unknown): value is PackageReviewComparisonRowSide {
  if (
    !recordObject(value) ||
    !exactKeys(value, [
      "row_digest",
      "requirement_digest",
      "rule_digest",
      "rule_kind",
      "requirement_statement",
      "applicability",
      "target_part_ids",
      "verdict",
      "statement",
      "limitations",
    ]) ||
    ![value.row_digest, value.requirement_digest, value.rule_digest].every(
      executionSha,
    ) ||
    !["disqualification", "mandatory", "scoring", "advisory"].includes(
      String(value.rule_kind),
    ) ||
    !text(value.requirement_statement) ||
    !["applicable", "unknown", "not_applicable"].includes(
      String(value.applicability),
    ) ||
    !texts(value.target_part_ids) ||
    !packageReviewVerdicts.includes(
      value.verdict as (typeof packageReviewVerdicts)[number],
    ) ||
    !text(value.statement, 4000) ||
    !texts(value.limitations)
  )
    return false;
  if (
    (value.rule_kind === "scoring" ||
      value.applicability === "unknown" ||
      (value.applicability !== "not_applicable" &&
        !value.target_part_ids.length) ||
      value.limitations.length) &&
    value.verdict !== "unable_to_judge"
  )
    return false;
  return (
    (value.verdict !== "not_applicable" ||
      value.applicability === "not_applicable") &&
    (value.applicability !== "not_applicable" ||
      ["not_applicable", "unable_to_judge"].includes(value.verdict as string))
  );
}
function validHuman(value: unknown) {
  return (
    value === null ||
    (recordObject(value) &&
      exactKeys(value, [
        "id",
        "digest",
        "sequence_no",
        "actor_id",
        "created_at",
        "state",
        "reason",
      ]) &&
      [value.id, value.actor_id].every(executionId) &&
      executionSha(value.digest) &&
      time(value.created_at) &&
      count(value.sequence_no, Number.MAX_SAFE_INTEGER) &&
      value.sequence_no > 0 &&
      ["confirmed", "rejected", "needs_review"].includes(String(value.state)) &&
      text(value.reason, 2000))
  );
}
function validRow(value: unknown): value is PackageReviewComparisonRow {
  if (
    !recordObject(value) ||
    !exactKeys(value, [
      "requirement_id",
      "definition_change",
      "machine_row_changed",
      "verdict_transition",
      "left",
      "right",
      "left_human",
      "right_human",
    ]) ||
    !executionId(value.requirement_id) ||
    (value.left === null && value.right === null) ||
    (value.left !== null && !validRowSide(value.left)) ||
    (value.right !== null && !validRowSide(value.right)) ||
    !validHuman(value.left_human) ||
    !validHuman(value.right_human) ||
    (value.left === null && value.left_human !== null) ||
    (value.right === null && value.right_human !== null)
  )
    return false;
  const row = value as unknown as PackageReviewComparisonRow,
    a = row.left,
    b = row.right;
  const change =
    a === null
      ? "added"
      : b === null
        ? "removed"
        : a.requirement_digest === b.requirement_digest &&
            a.rule_digest === b.rule_digest
          ? "unchanged"
          : "changed";
  if (row.definition_change !== change) return false;
  if (!a || !b)
    return row.machine_row_changed === null && row.verdict_transition === null;
  const transition = row.verdict_transition;
  return (
    row.machine_row_changed === (a.row_digest !== b.row_digest) &&
    (change !== "changed" || row.machine_row_changed === true) &&
    recordObject(transition) &&
    exactKeys(transition, ["from", "to", "changed"]) &&
    transition.from === a.verdict &&
    transition.to === b.verdict &&
    transition.changed === (a.verdict !== b.verdict) &&
    (!transition.changed || row.machine_row_changed === true)
  );
}
function fail(): never {
  throw new Error(
    "两轮对比的原运行、要求身份、变化分类或资格边界不符，未采用其他对比。",
  );
}
export const packageReviewComparisonTotal = (
  page: PackageReviewComparisonPage,
) =>
  page.counts.added +
  page.counts.removed +
  page.counts.changed +
  page.counts.unchanged;
export function packageReviewComparisonHeader(
  page: PackageReviewComparisonPage,
) {
  const value: Record<string, unknown> = { ...page };
  delete value.items;
  delete value.has_more;
  delete value.next_cursor;
  delete value.comparison_digest;
  return value;
}
export async function validatePackageReviewComparisonPage(
  value: unknown,
  request: PackageReviewComparisonRequest,
  limit = 20,
  previous?: PackageReviewComparisonPage,
): Promise<PackageReviewComparisonPage> {
  if (
    !executionId(request.bidId) ||
    !executionId(request.leftId) ||
    !executionId(request.rightId) ||
    request.leftId === request.rightId ||
    !recordObject(value) ||
    !exactKeys(value, [
      "version",
      "kind",
      "bid_id",
      "match_policy",
      "left",
      "right",
      "input_changes",
      "counts",
      "overall_coverage",
      "risk_resolution_assessed",
      "inventory_complete",
      "formal_scoring_eligible",
      "submission_eligible",
      "comparison_digest",
      "items",
      "has_more",
      "next_cursor",
    ]) ||
    value.version !== "package-review-comparison/1" ||
    value.kind !== "declared_scope_review_comparison" ||
    value.bid_id !== request.bidId ||
    value.match_policy !== "exact_requirement_id_and_definition_digests/1" ||
    !validRun(value.left, request.bidId, request.leftId) ||
    !validRun(value.right, request.bidId, request.rightId) ||
    value.overall_coverage !== "partial" ||
    value.risk_resolution_assessed !== false ||
    value.inventory_complete !== false ||
    value.formal_scoring_eligible !== false ||
    value.submission_eligible !== false ||
    !executionSha(value.comparison_digest) ||
    !recordObject(value.input_changes) ||
    !exactKeys(value.input_changes, [
      ...packageReviewComparisonChanges,
      "method_fields",
    ]) ||
    !recordObject(value.counts) ||
    !exactKeys(value.counts, [...packageReviewComparisonCounts])
  )
    return fail();
  const changes = value.input_changes,
    counts = value.counts;
  if (
    packageReviewComparisonChanges.some(
      (key) => typeof changes[key] !== "boolean",
    ) ||
    !Array.isArray(changes.method_fields) ||
    changes.method_fields.some((key) => !methodFields.includes(String(key))) ||
    new Set(changes.method_fields).size !== changes.method_fields.length ||
    packageReviewComparisonCounts.some((key) => !count(counts[key], 800))
  )
    return fail();
  const page = value as unknown as PackageReviewComparisonPage,
    a = page.left,
    b = page.right,
    c = page.counts,
    total = packageReviewComparisonTotal(page);
  if (
    c.removed + c.changed + c.unchanged !== a.requirement_count ||
    c.added + c.changed + c.unchanged !== b.requirement_count ||
    total < 1 ||
    total > 800 ||
    c.machine_row_changed > c.changed + c.unchanged ||
    c.machine_row_changed < c.changed ||
    c.verdict_changed > c.machine_row_changed ||
    changes.run_input !== (a.input_digest !== b.input_digest) ||
    changes.scope !== !sameScope(a.scope, b.scope) ||
    changes.frozen_input !==
      (a.frozen_input_id !== b.frozen_input_id ||
        a.frozen_input_digest !== b.frozen_input_digest) ||
    changes.prepared_input !==
      (a.execution_input_id !== b.execution_input_id ||
        a.execution_input_digest !== b.execution_input_digest) ||
    changes.dependency_plan !==
      (a.dependency_plan_id !== b.dependency_plan_id ||
        a.dependency_plan_digest !== b.dependency_plan_digest) ||
    changes.requirements !== c.added + c.removed + c.changed > 0 ||
    changes.method !== (a.method_digest !== b.method_digest) ||
    changes.method !== changes.method_fields.length > 0 ||
    !Array.isArray(page.items) ||
    !page.items.length ||
    page.items.length > limit ||
    page.items.length > total ||
    !page.items.every(validRow) ||
    page.items.some(
      (row, index) =>
        index > 0 && page.items[index - 1].requirement_id >= row.requirement_id,
    ) ||
    typeof page.has_more !== "boolean" ||
    (page.has_more ? !text(page.next_cursor, 4096) : page.next_cursor !== null)
  )
    return fail();
  const observed = tally(page.items);
  if (packageReviewComparisonCounts.some((key) => observed[key] > c[key]))
    return fail();
  if (
    previous &&
    (previous.comparison_digest !== page.comparison_digest ||
      (await frozenManifestDigest(packageReviewComparisonHeader(previous))) !==
        (await frozenManifestDigest(packageReviewComparisonHeader(page))))
  )
    throw new Error("对比所用的运行或人工状态快照已变化，请重新读取两轮对比。");
  return page;
}
function tally(
  items: PackageReviewComparisonRow[],
): PackageReviewComparisonPage["counts"] {
  const counts = {
    added: 0,
    removed: 0,
    changed: 0,
    unchanged: 0,
    machine_row_changed: 0,
    verdict_changed: 0,
  };
  items.forEach((row) => {
    counts[row.definition_change]++;
    counts.machine_row_changed += Number(row.machine_row_changed === true);
    counts.verdict_changed += Number(row.verdict_transition?.changed === true);
  });
  return counts;
}
export async function validateCompletePackageReviewComparison(
  page: PackageReviewComparisonPage,
  items: PackageReviewComparisonRow[],
) {
  if (
    items.length !== packageReviewComparisonTotal(page) ||
    new Set(items.map((row) => row.requirement_id)).size !== items.length
  )
    return fail();
  const counts = tally(items);
  if (
    packageReviewComparisonCounts.some(
      (key) => counts[key] !== page.counts[key],
    )
  )
    return fail();
  const sorted = [...items].sort((a, b) =>
    a.requirement_id < b.requirement_id
      ? -1
      : a.requirement_id > b.requirement_id
        ? 1
        : 0,
  );
  if (
    (await frozenManifestDigest({
      ...packageReviewComparisonHeader(page),
      items: sorted,
    })) !== page.comparison_digest
  )
    return fail();
}
