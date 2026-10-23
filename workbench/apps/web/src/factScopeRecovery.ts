import type { ChangePackageFactScope } from "./contracts";
import {
  exactKeys,
  executionId,
  recordObject,
} from "./executionInputValidation";
import { validScopeChange } from "./factScopeValidation";
import type { FreezeScope } from "./packageFrozenInput";
import { recordedCommandStorageKey } from "./recordedCommandStorage";
export type FactScopeKey = FreezeScope & {
  frozenId: string;
  preparedId: string;
  preparedDigest: string;
};
export type PendingFactScope = { key: string; body: ChangePackageFactScope };
export type FactScopeRecord = {
  version: 1;
  scope: FactScopeKey;
  pending: PendingFactScope | null;
  lastId: string | null;
  lastFactId: string | null;
};
export const factScopeStorageKey = (s: FactScopeKey) =>
  recordedCommandStorageKey(
    "fact-scope",
    s.memberId,
    s.bidId,
    s.packageId,
    s.revisionId,
    s.inventoryId,
    s.frozenId,
    s.preparedId,
  );
export function loadFactScopeRecord(scope: FactScopeKey): FactScopeRecord {
  const raw = sessionStorage.getItem(factScopeStorageKey(scope));
  if (raw === null)
    return { version: 1, scope, pending: null, lastId: null, lastFactId: null };
  const v: unknown = JSON.parse(raw);
  const bad = () => {
    throw new Error(
      "事实范围恢复记录损坏或身份不符，未发送请求；请保留记录核对。",
    );
  };
  if (
    !recordObject(v) ||
    !exactKeys(v, ["version", "scope", "pending", "lastId", "lastFactId"]) ||
    v.version !== 1 ||
    !recordObject(v.scope) ||
    !exactKeys(v.scope, Object.keys(scope))
  )
    return bad();
  const saved = v.scope;
  if (
    Object.entries(scope).some(([k, value]) => saved[k] !== value) ||
    (v.lastId !== null && !executionId(v.lastId)) ||
    (v.lastFactId !== null && !executionId(v.lastFactId))
  )
    return bad();
  if (
    v.pending !== null &&
    (!recordObject(v.pending) ||
      !exactKeys(v.pending, ["key", "body"]) ||
      !executionId(v.pending.key) ||
      !validScopeChange(v.pending.body, scope.preparedDigest))
  )
    return bad();
  return v as FactScopeRecord;
}
export function storeFactScopeRecord(record: FactScopeRecord) {
  sessionStorage.setItem(
    factScopeStorageKey(record.scope),
    JSON.stringify(record),
  );
}
