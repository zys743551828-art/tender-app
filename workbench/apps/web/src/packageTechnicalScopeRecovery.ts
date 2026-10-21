import { exactKeys, recordObject } from "./executionInputValidation";
import { recordedCommandStorageKey } from "./recordedCommandStorage";
import {
  assertTechnicalScope,
  technicalSame,
  validateTechnicalPending,
  type TechnicalPending,
  type TechnicalScope,
} from "./packageTechnicalScopeProtocol";

export const technicalRecoveryKey = (scope: TechnicalScope) =>
  recordedCommandStorageKey(
    "package-technical-scope",
    scope.memberId,
    scope.bidId,
    scope.packageId,
    scope.revisionId,
    scope.inventoryId,
  );

export function readTechnicalRecovery(
  scope: TechnicalScope,
): TechnicalPending | null {
  assertTechnicalScope(scope);
  const raw = sessionStorage.getItem(technicalRecoveryKey(scope));
  if (raw === null) return null;
  try {
    const value: unknown = JSON.parse(raw);
    if (
      !recordObject(value) ||
      !exactKeys(value, ["version", "scope", "pending"]) ||
      value.version !== 1 ||
      !technicalSame(value.scope, scope)
    )
      throw new Error();
    return validateTechnicalPending(value.pending, scope);
  } catch {
    throw new Error(
      "本地技术范围恢复记录无法核对。请保留记录，当前不能另发新保存请求。",
    );
  }
}

export function writeTechnicalRecovery(
  scope: TechnicalScope,
  pending: TechnicalPending | null,
) {
  assertTechnicalScope(scope);
  if (pending !== null) validateTechnicalPending(pending, scope);
  try {
    if (pending === null)
      sessionStorage.removeItem(technicalRecoveryKey(scope));
    else
      sessionStorage.setItem(
        technicalRecoveryKey(scope),
        JSON.stringify({ version: 1, scope, pending }),
      );
  } catch {
    throw new Error(
      "浏览器未能保存技术范围恢复记录。请保留页面并释放此站点存储空间，再恢复原操作。",
    );
  }
}
