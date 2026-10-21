import {
  exactKeys,
  executionId,
  recordObject,
} from "./executionInputValidation";
import { recordedCommandStorageKey } from "./recordedCommandStorage";
import {
  validPendingPackageSubmission,
  type PackageSubmissionScope,
  type PendingPackageSubmission,
} from "./packageSubmissionProtocol";

export type PackageSubmissionRecovery = {
  version: 1;
  scope: PackageSubmissionScope;
  pending: PendingPackageSubmission | null;
  lastId: string | null;
};
export const packageSubmissionStorageKey = (scope: PackageSubmissionScope) =>
  recordedCommandStorageKey("package-submission", scope.memberId, scope.bidId);
export function readPackageSubmissionRecovery(
  scope: PackageSubmissionScope,
): PackageSubmissionRecovery {
  const raw = sessionStorage.getItem(packageSubmissionStorageKey(scope));
  if (!raw) return { version: 1, scope, pending: null, lastId: null };
  try {
    const v: unknown = JSON.parse(raw);
    if (
      !recordObject(v) ||
      !exactKeys(v, ["version", "scope", "pending", "lastId"]) ||
      v.version !== 1 ||
      !recordObject(v.scope) ||
      !exactKeys(v.scope, ["bidId", "memberId"]) ||
      v.scope.bidId !== scope.bidId ||
      v.scope.memberId !== scope.memberId ||
      !(v.lastId === null || executionId(v.lastId)) ||
      !(
        v.pending === null ||
        validPendingPackageSubmission(v.pending, scope.bidId)
      )
    )
      throw new Error();
    return v as PackageSubmissionRecovery;
  } catch {
    throw new Error(
      "本地整包提交恢复记录损坏或身份不一致，请保留记录；不能另发新的登记替代原操作。",
    );
  }
}
export function writePackageSubmissionRecovery(
  value: PackageSubmissionRecovery,
) {
  try {
    sessionStorage.setItem(
      packageSubmissionStorageKey(value.scope),
      JSON.stringify(value),
    );
  } catch {
    throw new Error(
      "浏览器无法保存整包登记恢复记录，请释放此站点存储空间。本次不会发送未经记录的写入。",
    );
  }
}
