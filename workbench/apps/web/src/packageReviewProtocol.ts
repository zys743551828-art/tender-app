import type {
  Operation,
  PackageReviewResult,
  StartPackageReviewRun,
  PackageReviewRunPage,
  PackageReviewRunView,
  PackageReviewRunSummary,
} from "./contracts";
import type { DependencyProps } from "./inputDependencyProtocol";
import { dependencyPath } from "./inputDependencyProtocol";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
import { frozenManifestDigest } from "./packageFrozenInput";

export type PendingPackageReviewRun = {
  key: string;
  body: StartPackageReviewRun;
};
export type PackageReviewQuote =
  PackageReviewResult["matrix"][number]["target_quotes"][number];
export type PackageReviewDocument =
  PackageReviewResult["submitted_documents"][number];
export type PackageReviewRow = PackageReviewResult["matrix"][number];
export const packageReviewPath = (p: DependencyProps) =>
  dependencyPath(p).replace(/\/dependency-check$/, "/review-runs");
export const packageReviewScope = (p: DependencyProps) => ({
  bid_id: p.scope.bidId,
  package_id: p.scope.packageId,
  revision_id: p.scope.revisionId,
  inventory_id: p.scope.inventoryId,
});
export const packageReviewVerdicts = [
  "satisfied",
  "violated",
  "not_found",
  "unable_to_judge",
  "not_applicable",
] as const;
export const packageReviewStates = [
  "queued",
  "running",
  "cancel_requested",
  "succeeded",
  "failed",
  "cancelled",
] as const;
export const packageReviewEnded = (state: string) =>
  ["succeeded", "failed", "cancelled"].includes(state);
const count = (v: unknown): v is number =>
  Number.isSafeInteger(v) && Number(v) >= 0;
const positive = (v: unknown): v is number => count(v) && v > 0;
const text = (v: unknown, max = Infinity): v is string =>
  typeof v === "string" && !!v.trim() && Array.from(v).length <= max;
const texts = (v: unknown, max = 200): v is string[] =>
  Array.isArray(v) &&
  v.every((s) => text(s, max)) &&
  new Set(v).size === v.length;
const time = (v: unknown): v is string =>
  typeof v === "string" &&
  /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z$/.test(v) &&
  Number.isFinite(Date.parse(v)) &&
  new Date(v).toISOString().slice(0, 19) === v.slice(0, 19);
const same = (a: unknown, b: Record<string, unknown>) =>
  recordObject(a) &&
  exactKeys(a, Object.keys(b)) &&
  Object.entries(b).every(([k, v]) => a[k] === v);

export function validPackageReviewInput(
  v: unknown,
  p: DependencyProps,
): v is StartPackageReviewRun {
  return (
    recordObject(v) &&
    exactKeys(v, [
      "execution_input_digest",
      "dependency_plan_id",
      "dependency_plan_digest",
    ]) &&
    v.execution_input_digest === p.prepared.digest &&
    executionId(v.dependency_plan_id) &&
    executionSha(v.dependency_plan_digest)
  );
}
export function validPendingPackageReview(
  v: unknown,
  p: DependencyProps,
): v is PendingPackageReviewRun {
  return (
    recordObject(v) &&
    exactKeys(v, ["key", "body"]) &&
    executionId(v.key) &&
    validPackageReviewInput(v.body, p)
  );
}

const partKeys = [
  "part_id",
  "category",
  "first_page",
  "last_page",
  "shared_attachment",
  "heading_path",
];
function validPart(v: unknown, pageCount: number) {
  return (
    recordObject(v) &&
    exactKeys(v, partKeys) &&
    text(v.part_id, 200) &&
    text(v.category, 200) &&
    positive(v.first_page) &&
    positive(v.last_page) &&
    v.first_page <= v.last_page &&
    v.last_page <= pageCount &&
    typeof v.shared_attachment === "boolean" &&
    Array.isArray(v.heading_path) &&
    v.heading_path.every(positive)
  );
}
function validDocument(v: unknown): v is PackageReviewDocument {
  if (
    !recordObject(v) ||
    !exactKeys(v, [
      "package_role",
      "member_id",
      "document_version_id",
      "parse_run_id",
      "file_digest",
      "page_count",
      "parts",
      "evidence_count",
    ]) ||
    !["target", "authority"].includes(String(v.package_role)) ||
    !text(v.member_id, 200) ||
    !executionId(v.document_version_id) ||
    !executionId(v.parse_run_id) ||
    !executionSha(v.file_digest) ||
    !positive(v.page_count) ||
    !count(v.evidence_count) ||
    !Array.isArray(v.parts) ||
    !v.parts.length
  )
    return false;
  const ids = new Set<string>();
  return v.parts.every((part) => {
    if (!validPart(part, v.page_count as number) || ids.has(part.part_id))
      return false;
    ids.add(part.part_id);
    return true;
  });
}
function validQuote(
  q: unknown,
  role: "target" | "authority",
  docs: PackageReviewDocument[],
  row: PackageReviewRow,
) {
  if (
    !recordObject(q) ||
    !exactKeys(q, [
      "member_id",
      "evidence_id",
      "quote",
      "package_role",
      "document_version_id",
      "parse_run_id",
      "physical_page",
      "part_ids",
      "evidence_digest",
    ]) ||
    q.package_role !== role ||
    !executionId(q.evidence_id) ||
    !executionSha(q.evidence_digest) ||
    !text(q.quote, 2000) ||
    !positive(q.physical_page) ||
    !texts(q.part_ids) ||
    !q.part_ids.length
  )
    return false;
  const doc = docs.find(
    (d) =>
      d.package_role === role &&
      d.member_id === q.member_id &&
      d.document_version_id === q.document_version_id &&
      d.parse_run_id === q.parse_run_id,
  );
  if (!doc || q.physical_page > doc.page_count) return false;
  const physicalPage = q.physical_page;
  const parts = doc.parts.filter(
    (part) => part.first_page <= physicalPage && part.last_page >= physicalPage,
  );
  return (
    parts.length === q.part_ids.length &&
    parts.every((part) => (q.part_ids as string[]).includes(part.part_id)) &&
    (role === "authority" ||
      parts.some((part) => row.target_part_ids.includes(part.part_id)))
  );
}
function validRow(
  value: unknown,
  docs: PackageReviewDocument[],
): value is PackageReviewRow {
  if (
    !recordObject(value) ||
    !exactKeys(value, [
      "requirement_id",
      "requirement_digest",
      "rule_digest",
      "rule_kind",
      "requirement_statement",
      "applicability",
      "target_part_ids",
      "inspected_ranges",
      "verdict",
      "statement",
      "target_quotes",
      "authority_quotes",
      "used_fact_ids",
      "limitations",
      "human_review_state",
    ]) ||
    !executionId(value.requirement_id) ||
    !executionSha(value.requirement_digest) ||
    !executionSha(value.rule_digest) ||
    !["disqualification", "mandatory", "scoring", "advisory"].includes(
      String(value.rule_kind),
    ) ||
    !text(value.requirement_statement) ||
    !["applicable", "unknown", "not_applicable"].includes(
      String(value.applicability),
    ) ||
    !texts(value.target_part_ids) ||
    !Array.isArray(value.inspected_ranges) ||
    !packageReviewVerdicts.includes(
      value.verdict as (typeof packageReviewVerdicts)[number],
    ) ||
    !text(value.statement, 4000) ||
    !Array.isArray(value.target_quotes) ||
    value.target_quotes.length > 20 ||
    !Array.isArray(value.authority_quotes) ||
    value.authority_quotes.length > 20 ||
    !Array.isArray(value.used_fact_ids) ||
    !value.used_fact_ids.every(executionId) ||
    new Set(value.used_fact_ids).size !== value.used_fact_ids.length ||
    !texts(value.limitations) ||
    value.human_review_state !== "unreviewed"
  )
    return false;
  const row = value as unknown as PackageReviewRow;
  const expectedRanges = docs
    .filter((d) => d.package_role === "target")
    .flatMap((doc) =>
      doc.parts
        .filter((part) => row.target_part_ids.includes(part.part_id))
        .map((part) => ({
          member_id: doc.member_id,
          document_version_id: doc.document_version_id,
          parse_run_id: doc.parse_run_id,
          ...part,
        })),
    );
  if (
    expectedRanges.length !== row.inspected_ranges.length ||
    !expectedRanges.every((part) =>
      row.inspected_ranges.some(
        (range) =>
          recordObject(range) &&
          exactKeys(range, Object.keys(part)) &&
          Object.entries(part).every(([k, v]) =>
            k === "heading_path"
              ? JSON.stringify(range[k]) === JSON.stringify(v)
              : range[k as keyof typeof range] === v,
          ),
      ),
    ) ||
    !row.target_quotes.every((q) => validQuote(q, "target", docs, row)) ||
    !row.authority_quotes.every((q) => validQuote(q, "authority", docs, row))
  )
    return false;
  if (
    (row.limitations.length > 0 ||
      row.applicability === "unknown" ||
      (row.applicability !== "not_applicable" && !row.target_part_ids.length) ||
      row.rule_kind === "scoring") &&
    row.verdict !== "unable_to_judge"
  )
    return false;
  if (row.verdict !== "unable_to_judge" && !row.authority_quotes.length)
    return false;
  if (
    ["satisfied", "violated"].includes(row.verdict) &&
    !row.target_quotes.length
  )
    return false;
  return (
    (row.verdict !== "not_applicable" ||
      row.applicability === "not_applicable") &&
    (row.applicability !== "not_applicable" ||
      ["not_applicable", "unable_to_judge"].includes(row.verdict))
  );
}
async function validResult(
  value: unknown,
  run: PackageReviewRunView,
): Promise<boolean> {
  if (
    !recordObject(value) ||
    !exactKeys(value, ["manifest", "digest"]) ||
    !executionSha(value.digest) ||
    !recordObject(value.manifest)
  )
    return false;
  const m = value.manifest;
  if (
    !exactKeys(m, [
      "version",
      "kind",
      "purpose",
      "run_id",
      "bid_id",
      "input_digest",
      "execution_input_id",
      "execution_input_digest",
      "execution_digest",
      "dependency_plan_id",
      "dependency_plan_digest",
      "method_digest",
      "scope",
      "submitted_documents",
      "requirement_count",
      "matrix_coverage",
      "overall_coverage",
      "quality_status",
      "inventory_complete",
      "formal_scoring_eligible",
      "submission_eligible",
      "limitations",
      "counts",
      "matrix",
    ]) ||
    m.version !== "package-scope-review-result/1" ||
    m.kind !== "declared_package_scope_review" ||
    m.purpose !== "prebid_compliance" ||
    m.run_id !== run.id ||
    m.bid_id !== run.scope.bid_id ||
    !same(m.scope, run.scope) ||
    [
      "input_digest",
      "execution_input_id",
      "execution_input_digest",
      "execution_digest",
      "dependency_plan_id",
      "dependency_plan_digest",
      "method_digest",
    ].some((k) => m[k] !== run[k as keyof PackageReviewRunView]) ||
    m.overall_coverage !== "partial" ||
    m.quality_status !== "not_measured" ||
    m.inventory_complete !== false ||
    m.formal_scoring_eligible !== false ||
    m.submission_eligible !== false ||
    !texts(m.limitations) ||
    !m.limitations.includes("INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED") ||
    !Array.isArray(m.submitted_documents) ||
    m.submitted_documents.length < 2 ||
    m.submitted_documents.length > 1000 ||
    !m.submitted_documents.every(validDocument) ||
    !positive(m.requirement_count) ||
    m.requirement_count > 400 ||
    !Array.isArray(m.matrix) ||
    m.matrix.length !== m.requirement_count ||
    !recordObject(m.counts) ||
    !exactKeys(m.counts, [...packageReviewVerdicts])
  )
    return false;
  const docs = m.submitted_documents;
  if (
    new Set(docs.map((d) => `${d.package_role}:${d.member_id}`)).size !==
      docs.length ||
    !["target", "authority"].every((role) =>
      docs.some((d) => d.package_role === role),
    ) ||
    !m.matrix.every((row) => validRow(row, docs)) ||
    new Set(m.matrix.map((r) => r.requirement_id)).size !== m.matrix.length
  )
    return false;
  const counts = m.counts,
    matrix = m.matrix as PackageReviewRow[];
  if (
    !packageReviewVerdicts.every(
      (verdict) =>
        count(counts[verdict]) &&
        counts[verdict] ===
          matrix.filter((row) => row.verdict === verdict).length,
    )
  )
    return false;
  if (m.matrix_coverage !== (counts.unable_to_judge ? "partial" : "complete"))
    return false;
  return (await frozenManifestDigest(m)) === value.digest;
}

/** Read status only after its complete retained input and result identity have been checked. */
export async function validatePackageReviewRun(
  value: unknown,
  p: DependencyProps,
  expected?: string | PendingPackageReviewRun,
): Promise<PackageReviewRunView> {
  const fail = () => {
    throw new Error(
      "核查回执的输入、计划、执行身份或结果边界不符，未采用其他记录；未确认的原请求仍保留。",
    );
  };
  if (
    !recordObject(value) ||
    !exactKeys(value, [
      "kind",
      "id",
      "actor_id",
      "created_at",
      "scope",
      "frozen_input_id",
      "frozen_input_digest",
      "execution_input_id",
      "execution_input_digest",
      "execution_digest",
      "dependency_plan_id",
      "dependency_plan_digest",
      "input_digest",
      "method_digest",
      "operation",
      "result",
    ])
  )
    return fail();
  const run = value as unknown as PackageReviewRunView;
  if (
    run.kind !== "package_review_run" ||
    !executionId(run.id) ||
    !executionId(run.actor_id) ||
    !time(run.created_at) ||
    !same(run.scope, packageReviewScope(p)) ||
    run.frozen_input_id !== p.frozen.manifest.id ||
    run.frozen_input_digest !== p.frozen.digest ||
    run.execution_input_id !== p.prepared.manifest.id ||
    run.execution_input_digest !== p.prepared.digest ||
    run.execution_digest !== p.prepared.manifest.identity.execution_digest ||
    !executionId(run.dependency_plan_id) ||
    ![run.dependency_plan_digest, run.input_digest, run.method_digest].every(
      executionSha,
    ) ||
    !recordObject(run.operation) ||
    !exactKeys(run.operation, [
      "id",
      "kind",
      "state",
      "input_digest",
      "handler_version",
      "error_code",
      "created_at",
      "finished_at",
    ])
  )
    return fail();
  const op = run.operation;
  if (
    !executionId(op.id) ||
    op.kind !== "package-scope-review" ||
    !packageReviewStates.includes(op.state) ||
    op.input_digest !== run.input_digest ||
    op.handler_version !== "package-review/1" ||
    !(op.error_code === null || text(op.error_code, 200)) ||
    !time(op.created_at) ||
    !(op.finished_at === null || time(op.finished_at)) ||
    (op.finished_at !== null &&
      Date.parse(op.finished_at) < Date.parse(op.created_at)) ||
    (typeof expected === "string" && run.id !== expected) ||
    (expected !== undefined &&
      typeof expected !== "string" &&
      (!validPendingPackageReview(expected, p) ||
        run.dependency_plan_id !== expected.body.dependency_plan_id ||
        run.dependency_plan_digest !== expected.body.dependency_plan_digest))
  )
    return fail();
  if (
    run.result !== null &&
    (op.state !== "succeeded" || !(await validResult(run.result, run)))
  )
    return fail();
  return run;
}
export async function validatePackageReviewSummary(
  value: unknown,
  p: DependencyProps,
): Promise<PackageReviewRunSummary> {
  const fail = () => {
    throw new Error("核查历史摘要的输入或结果范围不符，未采用其他记录。");
  };
  if (!recordObject(value) || !("result" in value)) return fail();
  // The directory carries the same identity and operation metadata, never a full matrix.
  const metadata = await validatePackageReviewRun(
    { ...value, result: null },
    p,
  );
  const result = value.result;
  if ((metadata.operation.state === "succeeded") !== (result !== null))
    return fail();
  if (
    result !== null &&
    (!recordObject(result) ||
      !exactKeys(result, [
        "digest",
        "requirement_count",
        "matrix_coverage",
        "overall_coverage",
      ]) ||
      !executionSha(result.digest) ||
      !positive(result.requirement_count) ||
      result.requirement_count > 400 ||
      !["complete", "partial"].includes(String(result.matrix_coverage)) ||
      result.overall_coverage !== "partial")
  )
    return fail();
  return value as unknown as PackageReviewRunSummary;
}
export async function validatePackageReviewPage(
  value: unknown,
  p: DependencyProps,
  limit: number,
): Promise<PackageReviewRunPage> {
  const fail = () => {
    throw new Error("核查目录与当前准备输入不符，未采用其他历史。");
  };
  if (
    !recordObject(value) ||
    !exactKeys(value, [
      "scope",
      "frozen_input_id",
      "execution_input_id",
      "execution_input_digest",
      "items",
      "has_more",
      "next_cursor",
    ]) ||
    !same(value.scope, packageReviewScope(p)) ||
    value.frozen_input_id !== p.frozen.manifest.id ||
    value.execution_input_id !== p.prepared.manifest.id ||
    value.execution_input_digest !== p.prepared.digest ||
    !Array.isArray(value.items) ||
    value.items.length > limit ||
    typeof value.has_more !== "boolean" ||
    (value.has_more
      ? !value.items.length || !text(value.next_cursor, 2000)
      : value.next_cursor !== null)
  )
    return fail();
  const page = value as unknown as PackageReviewRunPage;
  if (new Set(page.items.map((run) => run.id)).size !== page.items.length)
    return fail();
  await Promise.all(
    page.items.map((run) => validatePackageReviewSummary(run, p)),
  );
  return page;
}

export function validPackageReviewOperation(
  value: unknown,
  run: PackageReviewRunView,
): value is Operation {
  return (
    recordObject(value) &&
    value.id === run.operation.id &&
    value.bid_id === run.scope.bid_id &&
    value.kind === "package-scope-review" &&
    value.handler_version === "package-review/1" &&
    value.input_digest === run.input_digest &&
    packageReviewStates.includes(
      value.state as (typeof packageReviewStates)[number],
    )
  );
}
