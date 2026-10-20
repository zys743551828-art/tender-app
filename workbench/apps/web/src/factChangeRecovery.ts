import {
  exactKeys,
  executionId,
  recordObject,
} from "./executionInputValidation";
import { validPendingFactChange } from "./factChangeProtocol";
import type { FactChangeScope, PendingFactChange } from "./factChangeProtocol";
export type FactChangeRecord = {
  version: 1;
  scope: FactChangeScope;
  pending: PendingFactChange | null;
  lastId: string | null;
};
export const factChangeStorageKey = (s: FactChangeScope) =>
  `tender:command-record:fact-change:${s.memberId}:${s.bidId}:${s.packageId}:${s.revisionId}:${s.inventoryId}:${s.frozenId}`;
export function loadFactChangeRecord(s: FactChangeScope): FactChangeRecord {
  const raw = sessionStorage.getItem(factChangeStorageKey(s));
  if (raw === null)
    return { version: 1, scope: s, pending: null, lastId: null };
  const bad = () => {
    throw new Error(
      "事实操作恢复记录损坏或身份不符，未发送请求；请保留记录核对。",
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
    Object.entries(s).some(([key, value]) => saved[key] !== value) ||
    (v.lastId !== null && !executionId(v.lastId)) ||
    (v.pending !== null && !validPendingFactChange(v.pending, s))
  )
    return bad();
  return v as FactChangeRecord;
}
export function storeFactChangeRecord(record: FactChangeRecord) {
  sessionStorage.setItem(
    factChangeStorageKey(record.scope),
    JSON.stringify(record),
  );
}
