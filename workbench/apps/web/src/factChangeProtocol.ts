import type {
  ConfirmPackageFact,
  WithdrawPackageFact,
  PackageFactChangeView,
  PackageCurrentFactPage,
  PackageCurrentFactDetail,
  PackageCurrentFactSummary,
  PackageEditableFact,
  PackageFactChange_Head,
} from "./contracts";
import type { FreezeScope } from "./packageFrozenInput";
import { freezePath, frozenManifestDigest } from "./packageFrozenInput";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
import { validScopeTime } from "./factScopeValidation";

export type FactChangeScope = FreezeScope & {
  frozenId: string;
  frozenDigest: string;
};
export type PendingFactChange =
  | { kind: "confirm"; key: string; body: ConfirmPackageFact }
  | { kind: "withdraw"; key: string; body: WithdrawPackageFact };
export const factChangeBase = (s: FactChangeScope) =>
  `${freezePath(s)}/${s.frozenId}`;
const flagKeys = [
  "original_bytes_verified",
  "facts_qualified",
  "review_ready",
  "launch_available",
  "publication_authorized",
];
const fields = ["subject", "scope", "name", "value", "unit", "evidence_ids"];
const length = (v: string) => Array.from(v).length;
const text = (v: unknown, max: number): v is string =>
  typeof v === "string" && length(v) <= max;
const reason = (v: unknown): v is string =>
  text(v, 2000) && v.length > 0 && v === v.trim();
export const validFactHead = (v: unknown): v is PackageFactChange_Head =>
  recordObject(v) &&
  exactKeys(v, ["id", "revision"]) &&
  Number.isSafeInteger(v.revision) &&
  Number(v.revision) >= 0 &&
  Number(v.revision) <= 2147483647 &&
  ((v.id === null && v.revision === 0) ||
    (executionId(v.id) && Number(v.revision) > 0));
export const sameFactHead = (
  a: PackageFactChange_Head,
  b: PackageFactChange_Head,
) => a.id === b.id && a.revision === b.revision;
export function validEditableFact(v: unknown): v is PackageEditableFact {
  return (
    recordObject(v) &&
    exactKeys(v, fields) &&
    ["subject", "scope", "name"].every(
      (k) => text(v[k], 5000) && String(v[k]).trim().length > 0,
    ) &&
    (v.value === null ||
      typeof v.value === "boolean" ||
      text(v.value, 20000)) &&
    (v.unit === null || typeof v.unit === "string") &&
    Array.isArray(v.evidence_ids) &&
    v.evidence_ids.length > 0 &&
    v.evidence_ids.length <= 100 &&
    v.evidence_ids.every(executionId) &&
    new Set(v.evidence_ids).size === v.evidence_ids.length
  );
}
export function validPendingFactChange(
  v: unknown,
  s: FactChangeScope,
): v is PendingFactChange {
  if (
    !recordObject(v) ||
    !exactKeys(v, ["kind", "key", "body"]) ||
    !executionId(v.key) ||
    !recordObject(v.body)
  )
    return false;
  const b = v.body;
  if (b.frozen_digest !== s.frozenDigest || !validFactHead(b.expected_head))
    return false;
  if (v.kind === "confirm") {
    if (
      !exactKeys(b, [
        "frozen_digest",
        "expected_head",
        "replaces_fact_id",
        "fact",
        "confirmation",
      ]) ||
      b.confirmation !== "confirmed" ||
      (b.replaces_fact_id !== null && !executionId(b.replaces_fact_id)) ||
      !recordObject(b.fact) ||
      !exactKeys(b.fact, [...fields, "reason"])
    )
      return false;
    const { reason: why, ...value } = b.fact;
    return reason(why) && validEditableFact(value);
  }
  return (
    v.kind === "withdraw" &&
    exactKeys(b, ["frozen_digest", "expected_head", "fact_id", "reason"]) &&
    executionId(b.fact_id) &&
    reason(b.reason)
  );
}
function binding(v: unknown, s: FactChangeScope) {
  return (
    recordObject(v) &&
    exactKeys(v, [
      "bid_id",
      "package_id",
      "revision_id",
      "inventory_id",
      "frozen_input_id",
      "frozen_digest",
    ]) &&
    v.bid_id === s.bidId &&
    v.package_id === s.packageId &&
    v.revision_id === s.revisionId &&
    v.inventory_id === s.inventoryId &&
    v.frozen_input_id === s.frozenId &&
    v.frozen_digest === s.frozenDigest
  );
}
function flags(v: Record<string, unknown>) {
  return flagKeys.every((k) => v[k] === false);
}
function summary(v: unknown): v is PackageCurrentFactSummary {
  return (
    recordObject(v) &&
    exactKeys(v, [
      "fact_id",
      "fact_item_digest",
      "name",
      "subject",
      "scope",
      "value_preview",
      "unit",
      "preview_truncated",
      "confirmation_recorded",
      "decision_id",
      "frozen_evidence_status",
    ]) &&
    executionId(v.fact_id) &&
    executionSha(v.fact_item_digest) &&
    ["name", "subject", "scope", "value_preview"].every((k) =>
      text(v[k], 240),
    ) &&
    (v.unit === null || text(v.unit, 240)) &&
    typeof v.preview_truncated === "boolean" &&
    ["pending", "confirmed", "rejected"].includes(
      String(v.confirmation_recorded),
    ) &&
    (v.decision_id === null || executionId(v.decision_id)) &&
    ["selected_parse", "unproven"].includes(String(v.frozen_evidence_status))
  );
}
export function validCurrentFactPage(
  v: unknown,
  s: FactChangeScope,
): v is PackageCurrentFactPage {
  if (
    !recordObject(v) ||
    !exactKeys(v, [
      "version",
      "kind",
      "binding",
      "head",
      "checked_at",
      "fact_count",
      "items",
      "has_more",
      "next_cursor",
      "source_packages",
      ...flagKeys,
      "required_facts_assessment",
    ]) ||
    v.version !== "package-current-facts/1" ||
    v.kind !== "current_package_facts" ||
    !binding(v.binding, s) ||
    !validFactHead(v.head) ||
    !validScopeTime(v.checked_at) ||
    !flags(v) ||
    v.required_facts_assessment !== "not_performed" ||
    !Array.isArray(v.items) ||
    v.items.length > 100 ||
    !v.items.every(summary) ||
    !Number.isSafeInteger(v.fact_count) ||
    Number(v.fact_count) < v.items.length ||
    typeof v.has_more !== "boolean"
  )
    return false;
  const ids = v.items.map((x) => x.fact_id);
  if (
    new Set(ids).size !== ids.length ||
    ids.some((id, n) => n > 0 && ids[n - 1] >= id)
  )
    return false;
  if (
    v.has_more
      ? !(
          v.items.length > 0 &&
          text(v.next_cursor, 4096) &&
          v.next_cursor.length > 0 &&
          Number(v.fact_count) > v.items.length
        )
      : v.next_cursor !== null
  )
    return false;
  if (!Array.isArray(v.source_packages) || v.source_packages.length !== 2)
    return false;
  const roles = new Set<string>();
  for (const ref of v.source_packages) {
    if (
      !recordObject(ref) ||
      !exactKeys(ref, ["role", "package_id", "revision_id", "digest"]) ||
      !["target", "authority"].includes(String(ref.role)) ||
      !executionId(ref.package_id) ||
      !executionId(ref.revision_id) ||
      !executionSha(ref.digest)
    )
      return false;
    roles.add(String(ref.role));
    if (
      ref.role === "target" &&
      (ref.package_id !== s.packageId || ref.revision_id !== s.revisionId)
    )
      return false;
  }
  return roles.size === 2 && (v.head.id !== null || v.fact_count === 0);
}
export function validCurrentFactDetail(
  v: unknown,
  s: FactChangeScope,
  id: string,
  expected?: PackageCurrentFactSummary,
): v is PackageCurrentFactDetail {
  if (
    !recordObject(v) ||
    !exactKeys(v, [
      "version",
      "kind",
      "binding",
      "head",
      "checked_at",
      "summary",
      "editability",
      "editable_fact",
      "evidence_references",
      "evidence_truncated",
      ...flagKeys,
      "required_facts_assessment",
    ]) ||
    v.version !== "package-current-fact/1" ||
    v.kind !== "current_package_fact" ||
    !binding(v.binding, s) ||
    !validFactHead(v.head) ||
    v.head.id === null ||
    !validScopeTime(v.checked_at) ||
    !summary(v.summary) ||
    v.summary.fact_id !== id ||
    (expected && v.summary.fact_item_digest !== expected.fact_item_digest) ||
    !flags(v) ||
    v.required_facts_assessment !== "not_performed"
  )
    return false;
  if (
    v.editability === "editable"
      ? !validEditableFact(v.editable_fact)
      : v.editability !== "unsupported_or_oversized" || v.editable_fact !== null
  )
    return false;
  if (
    !Array.isArray(v.evidence_references) ||
    v.evidence_references.length > 100 ||
    typeof v.evidence_truncated !== "boolean"
  )
    return false;
  const ids = new Set<string>();
  for (const ref of v.evidence_references) {
    if (
      !recordObject(ref) ||
      !exactKeys(ref, [
        "id",
        "parse_id",
        "document_version_id",
        "physical_page",
        "digest",
        "frozen_parse_member",
      ]) ||
      ![ref.id, ref.parse_id, ref.document_version_id].every(executionId) ||
      !executionSha(ref.digest) ||
      !Number.isSafeInteger(ref.physical_page) ||
      Number(ref.physical_page) < 1 ||
      typeof ref.frozen_parse_member !== "boolean" ||
      ids.has(String(ref.id))
    )
      return false;
    ids.add(String(ref.id));
  }
  return true;
}
export async function validateFactChange(
  v: PackageFactChangeView,
  s: FactChangeScope,
  pending?: PendingFactChange,
) {
  const bad = () => {
    throw new Error("事实回执的身份、请求摘要或资格边界不符，原请求仍保留。");
  };
  if (
    !recordObject(v) ||
    !exactKeys(v, ["manifest", "digest"]) ||
    !executionSha(v.digest) ||
    !recordObject(v.manifest)
  )
    return bad();
  const m = v.manifest;
  if (
    !["package-fact-change/1", "package-fact-change/2"].includes(m.version) ||
    !exactKeys(m, [
      "version",
      "kind",
      "command_id",
      "actor_id",
      "action",
      "recorded_at",
      "reason",
      "binding",
      "previous_head",
      "head",
      "fact_id",
      "replaces_fact_id",
      "decision_id",
      "evidence_selection_digest",
      "evidence_basis_digest",
      ...flagKeys,
      ...(m.version === "package-fact-change/2" ? ["request_digest"] : []),
    ]) ||
    m.kind !== "package_fact_change" ||
    ![m.command_id, m.actor_id, m.fact_id].every(executionId) ||
    !binding(m.binding, s) ||
    !validFactHead(m.previous_head) ||
    !validFactHead(m.head) ||
    m.head.id === null ||
    m.head.id === m.previous_head.id ||
    m.head.revision !== m.previous_head.revision + 1 ||
    !validScopeTime(m.recorded_at) ||
    !reason(m.reason) ||
    !flags(m)
  )
    return bad();
  if (m.version === "package-fact-change/2" && !executionSha(m.request_digest))
    return bad();
  if (m.action === "confirmed") {
    if (
      !executionId(m.decision_id) ||
      !executionSha(m.evidence_selection_digest) ||
      !executionSha(m.evidence_basis_digest) ||
      (m.replaces_fact_id !== null &&
        (!executionId(m.replaces_fact_id) ||
          m.previous_head.id === null ||
          m.replaces_fact_id === m.fact_id))
    )
      return bad();
  } else if (
    m.action !== "withdrawn" ||
    m.previous_head.id === null ||
    m.replaces_fact_id !== null ||
    m.decision_id !== null ||
    m.evidence_selection_digest !== null ||
    m.evidence_basis_digest !== null
  )
    return bad();
  if (pending) {
    if (
      m.version !== "package-fact-change/2" ||
      m.actor_id !== s.memberId ||
      !sameFactHead(m.previous_head, pending.body.expected_head) ||
      m.request_digest !==
        (await frozenManifestDigest({ body: pending.body, if_match: null }))
    )
      return bad();
    if (
      pending.kind === "confirm"
        ? m.action !== "confirmed" ||
          m.reason !== pending.body.fact.reason ||
          m.replaces_fact_id !== pending.body.replaces_fact_id
        : m.action !== "withdrawn" ||
          m.reason !== pending.body.reason ||
          m.fact_id !== pending.body.fact_id
    )
      return bad();
  }
  if ((await frozenManifestDigest(m)) !== v.digest) return bad();
}
