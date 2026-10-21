import type {
  PackageReviewReportView,
  PackageReviewRunView,
} from "./contracts";
import {
  exactKeys,
  executionId,
  recordObject,
} from "./executionInputValidation";
import { recordedCommandStorageKey } from "./recordedCommandStorage";
import { validPendingPackageReviewReport } from "./packageReviewReportProtocol";
import type { PendingPackageReviewReport } from "./packageReviewReportProtocol";
import type { PendingPackageReviewCancel } from "./packageReviewRecovery";
export type PackageReviewReportRecord = {
  version: 1;
  scope: ReturnType<typeof packageReviewReportScope>;
  pending: PendingPackageReviewReport | null;
  lastId: string | null;
};
export const packageReviewReportScope = (
  memberId: string,
  run: PackageReviewRunView,
) => ({
  memberId,
  ...run.scope,
  frozenId: run.frozen_input_id,
  preparedId: run.execution_input_id,
  runId: run.id,
  inputDigest: run.input_digest,
  resultDigest: run.result!.digest,
});
export const packageReviewReportStorageKey = (
  memberId: string,
  run: PackageReviewRunView,
) =>
  recordedCommandStorageKey(
    "package-review-report-export",
    memberId,
    run.scope.bid_id,
    run.scope.package_id,
    run.scope.revision_id,
    run.scope.inventory_id,
    run.frozen_input_id,
    run.execution_input_id,
    run.id,
    run.input_digest,
    run.result!.digest,
  );
const sameScope = (value: unknown, scope: Record<string, unknown>) =>
  recordObject(value) &&
  exactKeys(value, Object.keys(scope)) &&
  Object.entries(scope).every(([key, item]) => value[key] === item);
function parse(key: string) {
  const raw = sessionStorage.getItem(key);
  return raw === null ? undefined : (JSON.parse(raw) as unknown);
}
export function loadPackageReviewReportRecord(
  memberId: string,
  run: PackageReviewRunView,
): PackageReviewReportRecord {
  const scope = packageReviewReportScope(memberId, run);
  try {
    const value = parse(packageReviewReportStorageKey(memberId, run));
    if (value === undefined)
      return { version: 1, scope, pending: null, lastId: null };
    if (
      !recordObject(value) ||
      !exactKeys(value, ["version", "scope", "pending", "lastId"]) ||
      value.version !== 1 ||
      !sameScope(value.scope, scope) ||
      (value.pending !== null &&
        !validPendingPackageReviewReport(value.pending)) ||
      (value.lastId !== null && !executionId(value.lastId))
    )
      throw new Error("invalid stored report request");
    return value as PackageReviewReportRecord;
  } catch {
    throw new Error(
      "报告恢复记录无法核验，新申请已暂停；仍可查阅服务器报告历史。请保留原记录核对。",
    );
  }
}
function write(key: string, value: unknown) {
  try {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    throw new Error(
      "浏览器未能更新报告恢复记录。原申请或取消可能已经受理，请按原请求恢复或核对服务器历史。",
    );
  }
}
export function storePackageReviewReportRecord(
  memberId: string,
  run: PackageReviewRunView,
  record: PackageReviewReportRecord,
) {
  write(packageReviewReportStorageKey(memberId, run), record);
}
export const packageReviewReportCancelStorageKey = (
  memberId: string,
  run: PackageReviewRunView,
  report: PackageReviewReportView,
) =>
  `${packageReviewReportStorageKey(memberId, run)}:cancel:${report.id}:${report.operation.id}:${report.report_input_digest}`;
export function loadPackageReviewReportCancel(
  memberId: string,
  run: PackageReviewRunView,
  report: PackageReviewReportView,
): PendingPackageReviewCancel | null {
  try {
    const value = parse(
      packageReviewReportCancelStorageKey(memberId, run, report),
    );
    if (value === undefined) return null;
    const scope = {
      ...packageReviewReportScope(memberId, run),
      reportId: report.id,
      operationId: report.operation.id,
      reportInputDigest: report.report_input_digest,
    };
    if (
      !recordObject(value) ||
      !exactKeys(value, ["version", "scope", "pending"]) ||
      value.version !== 1 ||
      !sameScope(value.scope, scope) ||
      !recordObject(value.pending) ||
      !exactKeys(value.pending, ["key", "etag", "body"]) ||
      !executionId(value.pending.key) ||
      typeof value.pending.etag !== "string" ||
      !value.pending.etag ||
      value.pending.etag.length > 2000 ||
      !recordObject(value.pending.body) ||
      !exactKeys(value.pending.body, ["reason", "cancel_pending_same_input"]) ||
      value.pending.body.cancel_pending_same_input !== false ||
      typeof value.pending.body.reason !== "string" ||
      !value.pending.body.reason.trim() ||
      value.pending.body.reason.trim() !== value.pending.body.reason ||
      Array.from(value.pending.body.reason).length > 2000
    )
      throw new Error("invalid stored report cancellation");
    return value.pending as PendingPackageReviewCancel;
  } catch {
    throw new Error(
      "报告取消的恢复记录无法核验，未发起新取消；请保留原记录核对。",
    );
  }
}
export function storePackageReviewReportCancel(
  memberId: string,
  run: PackageReviewRunView,
  report: PackageReviewReportView,
  pending: PendingPackageReviewCancel | null,
) {
  write(
    packageReviewReportCancelStorageKey(memberId, run, report),
    pending === null
      ? null
      : {
          version: 1,
          scope: {
            ...packageReviewReportScope(memberId, run),
            reportId: report.id,
            operationId: report.operation.id,
            reportInputDigest: report.report_input_digest,
          },
          pending,
        },
  );
}
