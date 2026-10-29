import type { PackageSubmissionView } from "./contracts";
import { exactKeys, recordObject } from "./executionInputValidation";
import { historicalSame } from "./historicalImportProtocol";
import { recordedCommandStorageKey } from "./recordedCommandStorage";
import {
  validPendingOutcome,
  type PackageOutcomeScope,
  type PendingPackageOutcome,
} from "./packageOutcomeProtocol";

export const packageOutcomeStorageKey = (scope: PackageOutcomeScope) =>
  recordedCommandStorageKey(
    "package-official-outcome",
    scope.memberId,
    scope.submissionId,
  );
export function readOutcomeRecovery(
  scope: PackageOutcomeScope,
  submission: PackageSubmissionView,
): PendingPackageOutcome | null {
  const raw = sessionStorage.getItem(packageOutcomeStorageKey(scope));
  if (raw === null) return null;
  try {
    const value: unknown = JSON.parse(raw);
    if (
      !recordObject(value) ||
      !exactKeys(value, ["version", "scope", "pending"]) ||
      value.version !== 1 ||
      !historicalSame(value.scope, scope) ||
      !validPendingOutcome(value.pending, scope, submission)
    )
      throw new Error();
    return value.pending;
  } catch {
    throw new Error(
      "成绩操作恢复记录损坏或实交身份不符，已暂停新保存；请保留原记录，仍可核对服务器历史。",
    );
  }
}
export function writeOutcomeRecovery(
  scope: PackageOutcomeScope,
  pending: PendingPackageOutcome | null,
) {
  try {
    if (pending)
      sessionStorage.setItem(
        packageOutcomeStorageKey(scope),
        JSON.stringify({ version: 1, scope, pending }),
      );
    else sessionStorage.removeItem(packageOutcomeStorageKey(scope));
  } catch {
    throw new Error(
      "浏览器无法更新成绩操作恢复记录；请保留原请求并释放此站点存储空间，未取得确认的操作可以按原请求恢复。",
    );
  }
}
