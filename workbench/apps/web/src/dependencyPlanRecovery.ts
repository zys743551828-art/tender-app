import type { DependencyProps } from "./inputDependencyProtocol";
import type {
  DependencyPlanScope,
  PendingDependencyPlan,
} from "./dependencyPlanProtocol";
import {
  dependencyPlanScope,
  validPendingPlan,
} from "./dependencyPlanProtocol";
import {
  exactKeys,
  executionId,
  recordObject,
} from "./executionInputValidation";

export type DependencyPlanRecord = {
  version: 1;
  scope: DependencyPlanScope;
  pending: PendingDependencyPlan | null;
  lastId: string | null;
};
export const dependencyPlanStorageKey = (s: DependencyPlanScope) =>
  `tender:command-record:dependency-plan:${s.memberId}:${s.bidId}:${s.packageId}:${s.revisionId}:${s.inventoryId}:${s.frozenId}:${s.frozenDigest}:${s.preparedId}:${s.preparedDigest}`;
export function loadDependencyPlanRecord(
  p: DependencyProps,
): DependencyPlanRecord {
  const s = dependencyPlanScope(p);
  const raw = sessionStorage.getItem(dependencyPlanStorageKey(s));
  if (raw === null)
    return { version: 1, scope: s, pending: null, lastId: null };
  const bad = () => {
    throw new Error(
      "计划恢复记录损坏或原输入不符，未发送请求；请保留记录核对。",
    );
  };
  let v: unknown;
  try {
    v = JSON.parse(raw);
  } catch {
    return bad();
  }
  if (
    !recordObject(v) ||
    !exactKeys(v, ["version", "scope", "pending", "lastId"]) ||
    v.version !== 1 ||
    !recordObject(v.scope) ||
    !exactKeys(v.scope, Object.keys(s))
  )
    return bad();
  const saved = v.scope;
  if (
    Object.entries(s).some(([k, x]) => saved[k] !== x) ||
    (v.lastId !== null && !executionId(v.lastId)) ||
    (v.pending !== null && !validPendingPlan(v.pending, p))
  )
    return bad();
  return v as DependencyPlanRecord;
}
export function storeDependencyPlanRecord(record: DependencyPlanRecord) {
  sessionStorage.setItem(
    dependencyPlanStorageKey(record.scope),
    JSON.stringify(record),
  );
}
