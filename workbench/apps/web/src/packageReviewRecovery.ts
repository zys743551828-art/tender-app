import type { PackageReviewRunView } from "./contracts";
import { ApiError } from "./api";
import type { DependencyProps } from "./inputDependencyProtocol";
import { dependencyPlanScope } from "./dependencyPlanProtocol";
import type { DependencyPlanScope } from "./dependencyPlanProtocol";
import {
  exactKeys,
  executionId,
  recordObject,
} from "./executionInputValidation";
import { recordedCommandStorageKey } from "./recordedCommandStorage";
import { validPendingPackageReview } from "./packageReviewProtocol";
import type { PendingPackageReviewRun } from "./packageReviewProtocol";

export type PackageReviewRecord = {
  version: 1;
  scope: DependencyPlanScope;
  pending: PendingPackageReviewRun | null;
  lastId: string | null;
};
export type PendingPackageReviewCancel = {
  key: string;
  etag: string;
  body: { reason: string; cancel_pending_same_input: false };
};
// Both endpoints replay an accepted command before checking current business state.
// An unauthenticated, malformed or transient response cannot resolve an old command.
export function definitelyRejectedPackageReview(error: unknown) {
  return (
    error instanceof ApiError &&
    !error.retryable &&
    error.status >= 400 &&
    error.status < 500 &&
    ![401, 403, 404, 408, 429].includes(error.status) &&
    ![
      "IDEMPOTENCY_CONFLICT",
      "REQUEST_FAILED",
      "SERVICE_VERSION_NOT_READY",
    ].includes(error.code)
  );
}
export const packageReviewStorageKey = (s: DependencyPlanScope) =>
  recordedCommandStorageKey(
    "package-review-run",
    s.memberId,
    s.bidId,
    s.packageId,
    s.revisionId,
    s.inventoryId,
    s.frozenId,
    s.frozenDigest,
    s.preparedId,
    s.preparedDigest,
  );
export const packageReviewCancelStorageKey = (
  p: DependencyProps,
  run: PackageReviewRunView,
) =>
  `${packageReviewStorageKey(dependencyPlanScope(p))}:cancel:${run.id}:${run.operation.id}`;

function savedScope(value: unknown, scope: Record<string, unknown>) {
  return (
    recordObject(value) &&
    exactKeys(value, Object.keys(scope)) &&
    Object.entries(scope).every(([k, v]) => value[k] === v)
  );
}
export function loadPackageReviewRecord(
  p: DependencyProps,
): PackageReviewRecord {
  const scope = dependencyPlanScope(p);
  const raw = sessionStorage.getItem(packageReviewStorageKey(scope));
  if (raw === null) return { version: 1, scope, pending: null, lastId: null };
  const bad = () => {
    throw new Error(
      "核查恢复记录损坏或原输入不符，已阻止新启动；请保留记录核对，仍可只读查阅服务器历史。",
    );
  };
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return bad();
  }
  if (
    !recordObject(value) ||
    !exactKeys(value, ["version", "scope", "pending", "lastId"]) ||
    value.version !== 1 ||
    !savedScope(value.scope, scope) ||
    (value.lastId !== null && !executionId(value.lastId)) ||
    (value.pending !== null && !validPendingPackageReview(value.pending, p))
  )
    return bad();
  return value as PackageReviewRecord;
}
function write(key: string, value: unknown) {
  try {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    throw new Error(
      "浏览器未能更新核查恢复记录。请释放此站点存储空间后重试；原请求可能已经受理，须按原幂等键或服务器历史核对。",
    );
  }
}
export function storePackageReviewRecord(record: PackageReviewRecord) {
  write(packageReviewStorageKey(record.scope), record);
}
export function loadPackageReviewCancel(
  p: DependencyProps,
  run: PackageReviewRunView,
): PendingPackageReviewCancel | null {
  const raw = sessionStorage.getItem(packageReviewCancelStorageKey(p, run));
  if (raw === null) return null;
  const bad = () => {
    throw new Error(
      "取消请求的恢复记录损坏或任务身份不符，未发送新取消；请保留记录核对。",
    );
  };
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return bad();
  }
  const scope = {
    ...dependencyPlanScope(p),
    runId: run.id,
    operationId: run.operation.id,
    inputDigest: run.input_digest,
  };
  if (
    !recordObject(value) ||
    !exactKeys(value, ["version", "scope", "pending"]) ||
    value.version !== 1 ||
    !savedScope(value.scope, scope) ||
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
    !value.pending.body.reason ||
    value.pending.body.reason.trim() !== value.pending.body.reason ||
    Array.from(value.pending.body.reason).length > 2000
  )
    return bad();
  return value.pending as PendingPackageReviewCancel;
}
export function storePackageReviewCancel(
  p: DependencyProps,
  run: PackageReviewRunView,
  pending: PendingPackageReviewCancel | null,
) {
  write(
    packageReviewCancelStorageKey(p, run),
    pending === null
      ? null
      : {
          version: 1,
          scope: {
            ...dependencyPlanScope(p),
            runId: run.id,
            operationId: run.operation.id,
            inputDigest: run.input_digest,
          },
          pending,
        },
  );
}
