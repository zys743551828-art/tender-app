import { ApiError } from "./api";
import type {
  ApplyPackageRuleCorrection,
  PackageRequirementInventoryView,
  PackageRuleCorrectionRequest,
  PackageRuleCorrection_RuleAddition as RuleAddition,
} from "./contracts";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
import { recordedCommandStorageKey } from "./recordedCommandStorage";

export type CorrectionScope = {
  memberId: string;
  bidId: string;
  packageId: string;
  revisionId: string;
  packageDigest: string;
};
export type CorrectionBase = {
  inventoryId: string;
  inventoryDigest: string;
  inventoryRevision: number;
  ruleCount: number;
  ruleSetId: string;
  ruleSetDigest: string;
  authorityRevisionId: string;
  authorityDigest: string;
  identityDigest: string;
};
export type PendingCorrection = {
  key: string;
  etag: string;
  base: CorrectionBase;
  body: ApplyPackageRuleCorrection;
};
export type CorrectionRecovery = {
  version: 1;
  scope: CorrectionScope;
  pending: PendingCorrection | null;
  last: { inventoryId: string; correctionId: string } | null;
};
export const correctionInventoryPath = (scope: CorrectionScope) =>
  `/bids/${scope.bidId}/packages/${scope.packageId}/revisions/${scope.revisionId}/requirement-inventories`;
export const correctionPath = (scope: CorrectionScope, inventoryId: string) =>
  `${correctionInventoryPath(scope)}/${inventoryId}/rule-corrections`;
export const correctionEvidencePath = (
  scope: CorrectionScope,
  inventoryId: string,
) =>
  `${correctionInventoryPath(scope)}/${inventoryId}/rule-correction-evidence`;
export const correctionStorageKey = (scope: CorrectionScope) =>
  recordedCommandStorageKey(
    "package-rule-correction",
    scope.memberId,
    scope.bidId,
    scope.packageId,
    scope.revisionId,
  );
export const correctionText = (
  value: unknown,
  maximum = 2000,
): value is string =>
  typeof value === "string" &&
  !!value.trim() &&
  Array.from(value).length <= maximum &&
  Array.from(value).every((c) => {
    const point = c.codePointAt(0)!;
    return (
      (point >= 32 || point === 9 || point === 10 || point === 13) &&
      (point < 0xd800 || point > 0xdfff)
    );
  });
export const correctionEtag = (value: unknown): value is string =>
  typeof value === "string" &&
  value.length <= 256 &&
  /^"[^"\r\n]+"$/.test(value);
export const correctionInteger = (
  value: unknown,
  minimum = 0,
  maximum = Number.MAX_SAFE_INTEGER,
): value is number =>
  Number.isSafeInteger(value) &&
  Number(value) >= minimum &&
  Number(value) <= maximum;
export const correctionDecimal = (value: unknown): value is string =>
  typeof value === "string" &&
  value.length <= 100 &&
  /^[0-9]+(?:\.[0-9]+)?$/.test(value);
function texts(
  value: unknown,
  limit: number,
  length: number,
): value is string[] {
  return (
    Array.isArray(value) &&
    value.length <= limit &&
    value.every((item) => correctionText(item, length))
  );
}
function ids(value: unknown, minimum = 0, maximum = 50): value is string[] {
  return (
    Array.isArray(value) &&
    value.length >= minimum &&
    value.length <= maximum &&
    value.every(executionId) &&
    new Set(value).size === value.length
  );
}
export function validCorrectionQuotes(
  value: unknown,
): value is RuleAddition["evidence_quotes"] {
  return (
    Array.isArray(value) &&
    value.length >= 1 &&
    value.length <= 50 &&
    value.every(
      (item) =>
        recordObject(item) &&
        exactKeys(item, ["evidence_id", "quote"]) &&
        executionId(item.evidence_id) &&
        correctionText(item.quote, 8000),
    ) &&
    new Set(value.map((item) => JSON.stringify([item.evidence_id, item.quote])))
      .size === value.length
  );
}
export function validCorrectionRule(
  value: unknown,
  bidId: string,
): value is RuleAddition {
  return (
    recordObject(value) &&
    exactKeys(value, [
      "kind",
      "statement",
      "conditions",
      "exceptions",
      "scope",
      "maximum",
      "bands",
      "evidence_quotes",
    ]) &&
    ["disqualification", "mandatory", "scoring", "advisory"].includes(
      String(value.kind),
    ) &&
    correctionText(value.statement, 16000) &&
    texts(value.conditions, 50, 8000) &&
    texts(value.exceptions, 50, 8000) &&
    recordObject(value.scope) &&
    exactKeys(value.scope, ["bid_id", "description"]) &&
    value.scope.bid_id === bidId &&
    correctionText(value.scope.description) &&
    (value.maximum === null || correctionDecimal(value.maximum)) &&
    validCorrectionQuotes(value.evidence_quotes) &&
    Array.isArray(value.bands) &&
    value.bands.length <= 100 &&
    value.bands.every(
      (band) =>
        recordObject(band) &&
        exactKeys(band, ["label", "description", "points", "evidence_ids"]) &&
        correctionText(band.label, 8000) &&
        correctionText(band.description, 8000) &&
        correctionDecimal(band.points) &&
        ids(band.evidence_ids, 1) &&
        band.evidence_ids.every((id) =>
          (value.evidence_quotes as RuleAddition["evidence_quotes"]).some(
            (quote) => quote.evidence_id === id,
          ),
        ),
    )
  );
}
export function validCorrectionRequest(
  value: unknown,
  bidId: string,
): value is PackageRuleCorrectionRequest {
  if (
    !recordObject(value) ||
    !exactKeys(value, [
      "base_inventory_digest",
      "base_rule_set_digest",
      "reason",
      "changes",
    ]) ||
    !executionSha(value.base_inventory_digest) ||
    !executionSha(value.base_rule_set_digest) ||
    !correctionText(value.reason) ||
    !Array.isArray(value.changes) ||
    value.changes.length < 1 ||
    value.changes.length > 100
  )
    return false;
  const changed = new Set<string>();
  if (
    !value.changes.every((change) => {
      if (!recordObject(change)) return false;
      if (change.op === "add")
        return (
          exactKeys(change, ["op", "rule"]) &&
          validCorrectionRule(change.rule, bidId)
        );
      if (
        !["replace", "withdraw"].includes(String(change.op)) ||
        !executionId(change.rule_id) ||
        !executionSha(change.rule_digest) ||
        changed.has(change.rule_id)
      )
        return false;
      changed.add(change.rule_id);
      return change.op === "replace"
        ? exactKeys(change, ["op", "rule_id", "rule_digest", "rule"]) &&
            validCorrectionRule(change.rule, bidId)
        : exactKeys(change, [
            "op",
            "rule_id",
            "rule_digest",
            "evidence_quotes",
          ]) && validCorrectionQuotes(change.evidence_quotes);
    })
  )
    return false;
  return (
    new TextEncoder().encode(JSON.stringify(value)).byteLength <= 1024 * 1024
  );
}
export function correctionBase(
  inventory: PackageRequirementInventoryView,
): CorrectionBase {
  const m = inventory.manifest;
  return {
    inventoryId: m.id,
    inventoryDigest: inventory.digest,
    inventoryRevision: m.revision,
    ruleCount: m.requirements.length,
    ruleSetId: m.rule_set_id,
    ruleSetDigest: m.rule_set_digest,
    authorityRevisionId: m.authority_revision_id,
    authorityDigest: m.authority_digest,
    identityDigest: m.identity_digest,
  };
}
export function validCorrectionBase(value: unknown): value is CorrectionBase {
  return (
    recordObject(value) &&
    exactKeys(value, [
      "inventoryId",
      "inventoryDigest",
      "inventoryRevision",
      "ruleCount",
      "ruleSetId",
      "ruleSetDigest",
      "authorityRevisionId",
      "authorityDigest",
      "identityDigest",
    ]) &&
    executionId(value.inventoryId) &&
    executionSha(value.inventoryDigest) &&
    correctionInteger(value.inventoryRevision, 1) &&
    correctionInteger(value.ruleCount, 0, 10000) &&
    executionId(value.ruleSetId) &&
    executionSha(value.ruleSetDigest) &&
    executionId(value.authorityRevisionId) &&
    executionSha(value.authorityDigest) &&
    executionSha(value.identityDigest)
  );
}
export function readCorrectionRecovery(
  scope: CorrectionScope,
): CorrectionRecovery {
  const raw = sessionStorage.getItem(correctionStorageKey(scope));
  if (raw === null) return { version: 1, scope, pending: null, last: null };
  const value: unknown = JSON.parse(raw);
  if (
    !recordObject(value) ||
    !exactKeys(value, ["version", "scope", "pending", "last"]) ||
    value.version !== 1 ||
    !recordObject(value.scope) ||
    !exactKeys(value.scope, Object.keys(scope)) ||
    Object.entries(scope).some(
      ([key, item]) => (value.scope as Record<string, unknown>)[key] !== item,
    )
  )
    throw new Error(
      "本地规则修订记录损坏或不属于当前成员与资料包。请保留记录核对，不能另发新操作。",
    );
  const pending = value.pending;
  if (
    pending !== null &&
    (!recordObject(pending) ||
      !exactKeys(pending, ["key", "etag", "base", "body"]) ||
      !executionId(pending.key) ||
      !correctionEtag(pending.etag) ||
      !validCorrectionBase(pending.base) ||
      !recordObject(pending.body) ||
      !exactKeys(pending.body, ["request", "preview_digest"]) ||
      !executionSha(pending.body.preview_digest) ||
      !validCorrectionRequest(pending.body.request, scope.bidId) ||
      pending.body.request.base_inventory_digest !==
        pending.base.inventoryDigest ||
      pending.body.request.base_rule_set_digest !== pending.base.ruleSetDigest)
  )
    throw new Error(
      "本地规则修订原请求无法核对。请保留页面与记录，不能用新幂等键替代。",
    );
  if (
    value.last !== null &&
    (!recordObject(value.last) ||
      !exactKeys(value.last, ["inventoryId", "correctionId"]) ||
      !executionId(value.last.inventoryId) ||
      !executionId(value.last.correctionId))
  )
    throw new Error("本地规则修订历史身份无法核对，请保留记录。");
  return value as CorrectionRecovery;
}
export function writeCorrectionRecovery(value: CorrectionRecovery) {
  try {
    sessionStorage.setItem(
      correctionStorageKey(value.scope),
      JSON.stringify(value),
    );
  } catch {
    throw new Error(
      "浏览器未能保存规则修订恢复记录。请保留页面并释放此站点存储空间；尚未确认的请求必须继续使用原操作身份。",
    );
  }
}
/** Only the service's proven pre-commit business failures release an original request. */
export function definitiveCorrectionFailure(error: unknown) {
  const rejected = [
    "BASE_CHANGED",
    "CONTEXT_CHANGED",
    "DECISION_CHANGED",
    "SOURCE_CHANGED",
    "SOURCE_UNPROVEN",
    "EXACT_EXTRACTION_REQUIRED",
    "PREVIEW_CHANGED",
    "PROJECT_CLOSED",
    "AUTHORITY_CHANGED",
    "STORAGE_REJECTED",
    "REASON_REQUIRED",
    "RULE_CHANGED",
    "RULE_NOT_EFFECTIVE",
    "QUOTE_INVALID",
    "EVIDENCE_INVALID",
    "EVIDENCE_OUTSIDE_AUTHORITY",
    "NO_CHANGE",
    "DUPLICATE_RULE",
    "CAPACITY_EXCEEDED",
  ].map((code) => `PACKAGE_RULE_CORRECTION_${code}`);
  rejected.push(
    "REVISION_CONFLICT",
    "PROJECT_WORK_CLOSED",
    "ORIGINAL_BYTES_CORRUPTED",
    "ORIGINAL_NOT_AVAILABLE",
  );
  return (
    error instanceof ApiError &&
    !error.retryable &&
    [409, 412, 422].includes(error.status) &&
    rejected.includes(error.code)
  );
}
