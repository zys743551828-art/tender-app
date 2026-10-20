import type {
  PackageReviewExecutionContext,
  PackageReviewFrozenInputView,
} from "./contracts";
import type { FreezeScope } from "./packageFrozenInput";
import type { ExecutionExpectation } from "./executionInputValidation";
import {
  exactKeys,
  executionId,
  executionSha,
  contextKeys,
  recordObject,
} from "./executionInputValidation";
import { freezePath } from "./packageFrozenInput";
import { matchesExecutionContext } from "./packageReviewContext";

export type ExecutionScope = FreezeScope & {
  frozenId: string;
  frozenDigest: string;
  inputDigest: string;
  evidenceDigest: string;
};
export type PendingExecution = ExecutionExpectation & { key: string };
export type ExecutionRecord = {
  version: 1;
  scope: ExecutionScope;
  pending: PendingExecution | null;
  lastId: string | null;
};
export const executionScope = (
  scope: FreezeScope,
  frozen: PackageReviewFrozenInputView,
): ExecutionScope => ({
  ...scope,
  frozenId: frozen.manifest.id,
  frozenDigest: frozen.digest,
  inputDigest: frozen.manifest.input_digest,
  evidenceDigest: frozen.manifest.evidence_digest,
});
export const executionPath = (scope: FreezeScope, frozenId: string) =>
  `${freezePath(scope)}/${frozenId}/execution-inputs`;
export const executionStorageKey = (scope: ExecutionScope) =>
  `tender:command-record:package-execution:${scope.memberId}:${scope.bidId}:${scope.packageId}:${scope.revisionId}:${scope.inventoryId}:${scope.frozenId}`;
export function loadExecutionRecord(scope: ExecutionScope): ExecutionRecord {
  const raw = sessionStorage.getItem(executionStorageKey(scope));
  if (raw === null) return { version: 1, scope, pending: null, lastId: null };
  const v: unknown = JSON.parse(raw);
  const bad = () => {
    throw new Error(
      "执行准备输入恢复记录损坏或身份不符，未发送请求；请保留记录核对。",
    );
  };
  if (
    !recordObject(v) ||
    !exactKeys(v, ["version", "scope", "pending", "lastId"]) ||
    v.version !== 1 ||
    !recordObject(v.scope) ||
    !exactKeys(v.scope, Object.keys(scope)) ||
    (v.lastId !== null && !executionId(v.lastId))
  )
    return bad();
  const storedScope = v.scope;
  if (
    Object.keys(scope).some(
      (k) => scope[k as keyof ExecutionScope] !== storedScope[k],
    )
  )
    return bad();
  if (v.pending !== null) {
    const p = v.pending;
    if (
      !recordObject(p) ||
      !exactKeys(p, ["key", "body", "context"]) ||
      !executionId(p.key) ||
      !recordObject(p.body) ||
      !exactKeys(p.body, ["frozen_digest", "context_digest", "rerun"]) ||
      p.body.frozen_digest !== scope.frozenDigest ||
      !executionSha(p.body.context_digest) ||
      p.body.rerun !== null ||
      !recordObject(p.context) ||
      !exactKeys(p.context, contextKeys) ||
      !matchesExecutionContext(
        p.context as PackageReviewExecutionContext,
        scope.inputDigest,
        p.context.as_of as string,
      ) ||
      p.context.semantic_digest !== p.body.context_digest
    )
      return bad();
  }
  return v as unknown as ExecutionRecord;
}
export function storeExecutionRecord(record: ExecutionRecord) {
  sessionStorage.setItem(
    executionStorageKey(record.scope),
    JSON.stringify(record),
  );
}
