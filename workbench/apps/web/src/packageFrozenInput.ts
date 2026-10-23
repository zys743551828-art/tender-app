import type {
  FreezePackageReviewInput,
  PackageReviewFrozenInputView,
} from "./contracts";
import { matchesExecutionContext } from "./packageReviewContext";
import { recordedCommandStorageKey } from "./recordedCommandStorage";

export type FreezeScope = {
  memberId: string;
  bidId: string;
  packageId: string;
  revisionId: string;
  inventoryId: string;
};
export type PendingFreeze = { key: string; body: FreezePackageReviewInput };
export type FreezeRecord = {
  version: 1;
  scope: FreezeScope;
  pending: PendingFreeze | null;
  lastId: string | null;
};
const uuid = (v: unknown): v is string =>
  typeof v === "string" &&
  /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(v);
const sha = (v: unknown): v is string =>
  typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const object = (v: unknown): v is Record<string, unknown> =>
  v !== null && typeof v === "object" && !Array.isArray(v);
export const validFrozenInputId = uuid;
export const freezePath = (s: FreezeScope) =>
  `/bids/${s.bidId}/packages/${s.packageId}/revisions/${s.revisionId}/requirement-inventories/${s.inventoryId}/frozen-review-inputs`;
export const freezeStorageKey = (s: FreezeScope) =>
  recordedCommandStorageKey(
    "package-freeze",
    s.memberId,
    s.bidId,
    s.packageId,
    s.revisionId,
    s.inventoryId,
  );

export function validFreezeBody(v: unknown): v is FreezePackageReviewInput {
  if (
    !object(v) ||
    Object.keys(v).sort().join(",") !==
      "context_digest,coverage_attempt_id,coverage_digest,input_digest,inventory_digest,package_digest"
  )
    return false;
  return (
    [
      v.package_digest,
      v.inventory_digest,
      v.input_digest,
      v.context_digest,
    ].every(sha) &&
    (v.coverage_attempt_id === null
      ? v.coverage_digest === null
      : uuid(v.coverage_attempt_id) && sha(v.coverage_digest))
  );
}

/** Never silently discard a damaged recovery record or infer a new request from current heads. */
export function loadFreezeRecord(scope: FreezeScope): FreezeRecord {
  const raw = sessionStorage.getItem(freezeStorageKey(scope));
  if (raw === null) return { version: 1, scope, pending: null, lastId: null };
  const v: unknown = JSON.parse(raw);
  if (
    !object(v) ||
    v.version !== 1 ||
    !object(v.scope) ||
    Object.keys(v.scope).length !== Object.keys(scope).length ||
    Object.entries(scope).some(
      ([k, value]) => (v.scope as Record<string, unknown>)[k] !== value,
    ) ||
    !(v.lastId === null || uuid(v.lastId)) ||
    !(
      v.pending === null ||
      (object(v.pending) &&
        uuid(v.pending.key) &&
        validFreezeBody(v.pending.body))
    )
  )
    throw new Error(
      "冻结请求恢复记录损坏或身份不符。已阻止新保存，请保留本页并核对服务端记录。",
    );
  return v as FreezeRecord;
}

export function storeFreezeRecord(record: FreezeRecord) {
  try {
    sessionStorage.setItem(
      freezeStorageKey(record.scope),
      JSON.stringify(record),
    );
  } catch {
    throw new Error(
      "浏览器无法保存恢复记录。请释放此站点存储空间后重试，尚未确认的请求仍需核对。",
    );
  }
}

// Same restricted canonical JSON as review_identity.py (only integer counts and ASCII keys here).
function canonical(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(canonical).join(",")}]`;
  if (object(v))
    return `{${Object.keys(v)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${canonical(v[k])}`)
      .join(",")}}`;
  return JSON.stringify(v);
}
export async function frozenManifestDigest(manifest: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(canonical(manifest));
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
}

const blockers = new Set([
  "PROJECT_WORK_CLOSED",
  "PACKAGE_BIDDER_UNCONFIRMED",
  "PACKAGE_REVIEW_IDENTITY_STALE",
  "PACKAGE_REVIEW_PACKAGE_STALE",
  "PACKAGE_REVIEW_INVENTORY_STALE",
  "PACKAGE_REVIEW_RULE_SET_STALE",
  "PACKAGE_REVIEW_SOURCE_UNPROVEN",
  "PACKAGE_REVIEW_SOURCE_CHANGED",
  "PACKAGE_REVIEW_SOURCE_NOT_EFFECTIVE",
  "PACKAGE_REVIEW_MEMBERS_UNPROVEN",
  "PACKAGE_REVIEW_EVIDENCE_CHANGED",
  "PACKAGE_REVIEW_PHYSICAL_RANGE_GAP",
  "PACKAGE_REVIEW_EXTRACTION_UNPROVEN",
  "PACKAGE_REVIEW_REQUIREMENT_COMPLETENESS_UNPROVEN",
  "PACKAGE_REVIEW_EXECUTOR_NOT_READY",
]);

/** Validate server identity before marking an uncertain write complete; history may have another actor. */
export async function validateFrozenInput(
  value: PackageReviewFrozenInputView,
  scope: FreezeScope,
  expected: PendingFreeze | string,
): Promise<void> {
  const m = value?.manifest;
  const save = typeof expected !== "string";
  if (
    !m ||
    m.version !== "package-review-frozen-input/1" ||
    m.kind !== "frozen_input" ||
    !uuid(m.id) ||
    !uuid(m.actor_id) ||
    !uuid(m.command_id) ||
    m.bid_id !== scope.bidId ||
    m.package_id !== scope.packageId ||
    m.revision_id !== scope.revisionId ||
    m.inventory_id !== scope.inventoryId ||
    (save
      ? m.actor_id !== scope.memberId ||
        m.input_digest !== expected.body.input_digest ||
        m.context_digest !== expected.body.context_digest
      : m.id !== expected) ||
    ![m.input_digest, m.context_digest, m.evidence_digest, value.digest].every(
      sha,
    ) ||
    !matchesExecutionContext(m.execution_context, m.input_digest, m.as_of) ||
    m.execution_context.as_of !== m.as_of ||
    m.execution_context.semantic_digest !== m.context_digest ||
    !Number.isFinite(Date.parse(m.frozen_at)) ||
    Date.parse(m.frozen_at) < Date.parse(m.as_of) ||
    m.review_ready !== false ||
    m.launch_available !== false ||
    !Array.isArray(m.blockers) ||
    !m.blockers.includes("PACKAGE_REVIEW_EXECUTOR_NOT_READY") ||
    m.blockers.some((code) => !blockers.has(code)) ||
    new Set(m.blockers).size !== m.blockers.length ||
    (await frozenManifestDigest(m)) !== value.digest
  )
    throw new Error(
      "冻结输入响应身份或摘要不符，未确认保存成功；未决请求仍保留。",
    );
}
