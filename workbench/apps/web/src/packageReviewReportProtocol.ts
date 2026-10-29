import type {
  Operation,
  PackageReviewReportContext,
  PackageReviewReportPage,
  PackageReviewReportView,
  PackageReviewRunView,
  StartPackageReviewReport,
} from "./contracts";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
import type { DependencyProps } from "./inputDependencyProtocol";
import {
  packageReviewEnded,
  packageReviewPath,
  packageReviewStates,
} from "./packageReviewProtocol";

export type PendingPackageReviewReport = {
  key: string;
  body: StartPackageReviewReport;
};
export const packageReviewReportPath = (
  p: DependencyProps,
  run: PackageReviewRunView,
) => `${packageReviewPath(p)}/${run.id}/report-exports`;
export const packageReviewReportMedia = {
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  pdf: "application/pdf",
} as const;
const bindingKeys = [
  "scope",
  "frozen_input_id",
  "execution_input_id",
  "run_id",
  "input_digest",
  "result_digest",
];
const scopeKeys = ["bid_id", "package_id", "revision_id", "inventory_id"];
const text = (value: unknown, max: number): value is string =>
  typeof value === "string" &&
  !!value.trim() &&
  Array.from(value).length <= max;
const time = (value: unknown): value is string =>
  typeof value === "string" &&
  /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z$/.test(value) &&
  Number.isFinite(Date.parse(value)) &&
  new Date(value).toISOString().slice(0, 19) === value.slice(0, 19);
function fail(): never {
  throw new Error(
    "报告副本的原运行、结果、格式或任务身份无法核验，未采用其他报告。",
  );
}
function binding(value: Record<string, unknown>, run: PackageReviewRunView) {
  return (
    run.operation.state === "succeeded" &&
    !!run.result &&
    recordObject(value.scope) &&
    exactKeys(value.scope, scopeKeys) &&
    scopeKeys.every(
      (key) =>
        (value.scope as Record<string, unknown>)[key] ===
        run.scope[key as keyof typeof run.scope],
    ) &&
    value.frozen_input_id === run.frozen_input_id &&
    value.execution_input_id === run.execution_input_id &&
    value.run_id === run.id &&
    value.input_digest === run.input_digest &&
    value.result_digest === run.result.digest
  );
}
export function validatePackageReviewReportContext(
  value: unknown,
  run: PackageReviewRunView,
): PackageReviewReportContext {
  if (
    !recordObject(value) ||
    !exactKeys(value, [
      ...bindingKeys,
      "human_decisions_digest",
      "method_digest",
      "context_digest",
      "formats",
      "pdf_unavailable_code",
      "formal_scoring_eligible",
      "submission_eligible",
    ]) ||
    !binding(value, run) ||
    ![
      value.human_decisions_digest,
      value.method_digest,
      value.context_digest,
    ].every(executionSha) ||
    !Array.isArray(value.formats) ||
    !value.formats.includes("docx") ||
    value.formats.some((format) => !["docx", "pdf"].includes(String(format))) ||
    new Set(value.formats).size !== value.formats.length ||
    (value.formats.includes("pdf")
      ? value.pdf_unavailable_code !== null
      : !text(value.pdf_unavailable_code, 200)) ||
    value.formal_scoring_eligible !== false ||
    value.submission_eligible !== false
  )
    return fail();
  return value as PackageReviewReportContext;
}
export function validPendingPackageReviewReport(
  value: unknown,
): value is PendingPackageReviewReport {
  return (
    recordObject(value) &&
    exactKeys(value, ["key", "body"]) &&
    executionId(value.key) &&
    recordObject(value.body) &&
    exactKeys(value.body, ["context_digest", "format"]) &&
    executionSha(value.body.context_digest) &&
    ["docx", "pdf"].includes(String(value.body.format))
  );
}
export function validatePackageReviewReport(
  value: unknown,
  run: PackageReviewRunView,
  expected?: string | PendingPackageReviewReport,
): PackageReviewReportView {
  if (
    !recordObject(value) ||
    !exactKeys(value, [
      ...bindingKeys,
      "id",
      "actor_id",
      "created_at",
      "context_digest",
      "report_input_digest",
      "format",
      "artifact_kind",
      "operation",
      "result",
      "formal_scoring_eligible",
      "submission_eligible",
    ]) ||
    !binding(value, run) ||
    ![value.id, value.actor_id].every(executionId) ||
    !time(value.created_at) ||
    ![value.context_digest, value.report_input_digest].every(executionSha) ||
    !["docx", "pdf"].includes(String(value.format)) ||
    value.artifact_kind !== "review_report" ||
    value.formal_scoring_eligible !== false ||
    value.submission_eligible !== false ||
    !recordObject(value.operation) ||
    !exactKeys(value.operation, [
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
  const op = value.operation;
  if (
    !executionId(op.id) ||
    op.kind !== "package-scope-report" ||
    !packageReviewStates.includes(
      op.state as (typeof packageReviewStates)[number],
    ) ||
    op.input_digest !== value.report_input_digest ||
    op.handler_version !== "package-report/1" ||
    !time(op.created_at) ||
    !(op.error_code === null || text(op.error_code, 200)) ||
    (packageReviewEnded(String(op.state))
      ? !time(op.finished_at)
      : op.finished_at !== null) ||
    (op.state === "succeeded") !== (value.result !== null)
  )
    return fail();
  const report = value as unknown as PackageReviewReportView,
    result = report.result;
  if (
    result !== null &&
    (!recordObject(result) ||
      !exactKeys(result, [
        "document_version_id",
        "blob_digest",
        "byte_size",
        "media_type",
        "filename",
        "gaps",
      ]) ||
      !executionId(result.document_version_id) ||
      !executionSha(result.blob_digest) ||
      !Number.isSafeInteger(result.byte_size) ||
      result.byte_size < 1 ||
      result.media_type !== packageReviewReportMedia[report.format] ||
      !text(result.filename, 200) ||
      !Array.isArray(result.gaps) ||
      result.gaps.length > 100 ||
      !result.gaps.every((gap) => text(gap, 200)))
  )
    return fail();
  if (
    typeof expected === "string"
      ? report.id !== expected
      : expected &&
        (report.context_digest !== expected.body.context_digest ||
          report.format !== expected.body.format)
  )
    return fail();
  return report;
}
export function validatePackageReviewReportPage(
  value: unknown,
  run: PackageReviewRunView,
  limit = 10,
): PackageReviewReportPage {
  if (
    !recordObject(value) ||
    !exactKeys(value, [...bindingKeys, "items", "has_more", "next_cursor"]) ||
    !binding(value, run) ||
    !Array.isArray(value.items) ||
    value.items.length > limit ||
    typeof value.has_more !== "boolean" ||
    (value.has_more
      ? !value.items.length || !text(value.next_cursor, 4096)
      : value.next_cursor !== null)
  )
    return fail();
  const page = value as PackageReviewReportPage;
  if (new Set(page.items.map((item) => item.id)).size !== page.items.length)
    return fail();
  page.items.forEach((item) => validatePackageReviewReport(item, run));
  return page;
}
export function samePackageReviewReport(
  before: PackageReviewReportView,
  after: PackageReviewReportView,
) {
  const fields = [
    "id",
    "actor_id",
    "created_at",
    "context_digest",
    "report_input_digest",
    "format",
    "artifact_kind",
    "run_id",
    "input_digest",
    "result_digest",
    "frozen_input_id",
    "execution_input_id",
  ] as const;
  return (
    fields.every((key) => before[key] === after[key]) &&
    scopeKeys.every(
      (key) =>
        before.scope[key as keyof typeof before.scope] ===
        after.scope[key as keyof typeof after.scope],
    ) &&
    before.operation.id === after.operation.id &&
    before.operation.created_at === after.operation.created_at
  );
}
export function samePackageReviewReportArtifact(
  before: NonNullable<PackageReviewReportView["result"]>,
  after: PackageReviewReportView["result"],
) {
  const fields = [
    "document_version_id",
    "blob_digest",
    "byte_size",
    "media_type",
    "filename",
  ] as const;
  return (
    !!after &&
    fields.every((key) => before[key] === after[key]) &&
    before.gaps.length === after.gaps.length &&
    before.gaps.every((gap, index) => gap === after.gaps[index])
  );
}
export function validPackageReviewReportOperation(
  value: unknown,
  report: PackageReviewReportView,
): value is Operation {
  return (
    recordObject(value) &&
    value.id === report.operation.id &&
    value.bid_id === report.scope.bid_id &&
    value.kind === "package-scope-report" &&
    value.handler_version === "package-report/1" &&
    value.input_digest === report.report_input_digest &&
    packageReviewStates.includes(
      value.state as (typeof packageReviewStates)[number],
    )
  );
}
