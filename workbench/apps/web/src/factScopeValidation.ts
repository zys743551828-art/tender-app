import type {
  ChangePackageFactScope,
  PackageExecutionInputView,
  PackageFactScopeObservation,
  PackageFactScopeView,
} from "./contracts";
import type { FreezeScope } from "./packageFrozenInput";
import { frozenManifestDigest } from "./packageFrozenInput";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";

export const scopeKinds = [
  "engineering_project",
  "lot",
  "round",
  "bidder",
] as const;
export const scopeLabels = {
  engineering_project: "工程",
  lot: "标段",
  round: "轮次",
  bidder: "投标主体",
};
const flags = [
  "facts_qualified",
  "review_ready",
  "launch_available",
  "publication_authorized",
];
export const validScopeTime = (value: unknown): value is string => {
  if (
    typeof value !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/.test(value)
  )
    return false;
  const ms = Date.parse(value);
  return (
    Number.isFinite(ms) &&
    new Date(ms).toISOString().slice(0, 19) === value.slice(0, 19)
  );
};
export const validSubject = (v: unknown) =>
  recordObject(v) &&
  exactKeys(v, ["kind", "id"]) &&
  scopeKinds.includes(v.kind as (typeof scopeKinds)[number]) &&
  executionId(v.id);
export function validScopeChange(
  v: unknown,
  preparedDigest: string,
): v is ChangePackageFactScope {
  if (
    !recordObject(v) ||
    !exactKeys(v, [
      "execution_input_digest",
      "fact_id",
      "action",
      "subject",
      "reason",
      "previous_digest",
    ])
  )
    return false;
  return (
    v.execution_input_digest === preparedDigest &&
    executionId(v.fact_id) &&
    typeof v.reason === "string" &&
    v.reason.length > 0 &&
    v.reason.length <= 2000 &&
    v.reason === v.reason.trim() &&
    (v.previous_digest === null || executionSha(v.previous_digest)) &&
    ((v.action === "bind" && validSubject(v.subject)) ||
      (v.action === "withdraw" &&
        v.subject === null &&
        executionSha(v.previous_digest)))
  );
}
export async function validateScopeRecord(
  v: PackageFactScopeView,
  prepared: PackageExecutionInputView,
  factId?: string,
  pending?: ChangePackageFactScope,
  actor?: string,
) {
  const bad = () => {
    throw new Error("事实范围记录身份、摘要或资格边界不符；原请求仍保留。");
  };
  if (
    !recordObject(v) ||
    !exactKeys(v, ["manifest", "digest"]) ||
    !executionSha(v.digest) ||
    !recordObject(v.manifest)
  )
    return bad();
  const m = v.manifest,
    b = m.binding,
    expected = prepared.manifest.identity.binding;
  if (
    !exactKeys(m, [
      "version",
      "kind",
      "id",
      "actor_id",
      "command_id",
      "recorded_at",
      "reason",
      "action",
      "previous_digest",
      "binding",
      "subject",
      ...flags,
    ]) ||
    m.version !== "package-fact-scope/1" ||
    m.kind !== "fact_scope_declaration" ||
    ![m.id, m.actor_id, m.command_id].every(executionId) ||
    !validScopeTime(m.recorded_at) ||
    typeof m.reason !== "string" ||
    !m.reason.trim() ||
    m.reason !== m.reason.trim() ||
    m.reason.length > 2000 ||
    !validSubject(m.subject) ||
    flags.some((k) => m[k as keyof typeof m] !== false) ||
    !recordObject(b)
  )
    return bad();
  const extra = [
    "execution_input_id",
    "execution_input_digest",
    "facts_digest",
    "fact_set_id",
    "fact_id",
    "fact_item_digest",
    "proof_digest",
  ];
  if (
    !exactKeys(b, [...Object.keys(expected), ...extra]) ||
    Object.entries(expected).some(
      ([k, value]) => b[k as keyof typeof b] !== value,
    ) ||
    b.execution_input_id !== prepared.manifest.id ||
    b.execution_input_digest !== prepared.digest ||
    b.facts_digest !== prepared.manifest.execution_context.facts_digest ||
    b.fact_set_id !== prepared.manifest.execution_context.fact_set_id ||
    !executionId(b.fact_id) ||
    (factId !== undefined && b.fact_id !== factId) ||
    ![b.fact_item_digest, b.proof_digest].every(executionSha)
  )
    return bad();
  if (
    (m.previous_digest !== null && !executionSha(m.previous_digest)) ||
    !["bind", "withdraw"].includes(m.action) ||
    (m.action === "withdraw" && m.previous_digest === null)
  )
    return bad();
  if (
    pending &&
    (b.fact_id !== pending.fact_id ||
      m.action !== pending.action ||
      m.reason !== pending.reason ||
      m.previous_digest !== pending.previous_digest ||
      (pending.action === "bind" &&
        (pending.subject?.kind !== m.subject.kind ||
          pending.subject?.id !== m.subject.id)) ||
      m.actor_id !== actor)
  )
    return bad();
  if ((await frozenManifestDigest(m)) !== v.digest) return bad();
}
export async function validateScopeObservation(
  v: PackageFactScopeObservation,
  scope: FreezeScope,
  frozenId: string,
  prepared: PackageExecutionInputView,
  factId: string,
) {
  const bad = () => {
    throw new Error("事实范围观察身份或状态不符，未采纳。");
  };
  if (
    !recordObject(v) ||
    !exactKeys(v, [
      "kind",
      "bid_id",
      "package_id",
      "revision_id",
      "inventory_id",
      "frozen_input_id",
      "execution_input_id",
      "execution_input_digest",
      "fact_id",
      "prepared_context_digest",
      "observed_context_digest",
      "matches_prepared_input",
      "provenance_status",
      "subject_choices",
      "head",
      "binding_status",
      "observation_gap",
      "checked_at",
      ...flags,
    ])
  )
    return bad();
  if (
    v.kind !== "fact_scope_observation" ||
    v.bid_id !== scope.bidId ||
    v.package_id !== scope.packageId ||
    v.revision_id !== scope.revisionId ||
    v.inventory_id !== scope.inventoryId ||
    v.frozen_input_id !== frozenId ||
    v.execution_input_id !== prepared.manifest.id ||
    v.execution_input_digest !== prepared.digest ||
    v.fact_id !== factId ||
    v.prepared_context_digest !==
      prepared.manifest.identity.binding.context_digest ||
    typeof v.matches_prepared_input !== "boolean" ||
    !["verified", "unproven"].includes(v.provenance_status) ||
    !["unproven", "matches_current_input", "withdrawn"].includes(
      v.binding_status,
    ) ||
    !validScopeTime(v.checked_at) ||
    flags.some((k) => v[k as keyof typeof v] !== false)
  )
    return bad();
  if (
    v.observation_gap !== null &&
    (typeof v.observation_gap !== "string" ||
      !/^[A-Z][A-Z0-9_]{0,199}$/.test(v.observation_gap))
  )
    return bad();
  if (
    v.observation_gap === null
      ? !executionSha(v.observed_context_digest)
      : v.observed_context_digest !== null ||
        v.matches_prepared_input ||
        v.provenance_status !== "unproven"
  )
    return bad();
  if (
    v.matches_prepared_input &&
    v.observed_context_digest !== v.prepared_context_digest
  )
    return bad();
  if (
    !Array.isArray(v.subject_choices) ||
    ![0, 4].includes(v.subject_choices.length) ||
    v.subject_choices.some(
      (x) =>
        !recordObject(x) ||
        !exactKeys(x, ["kind", "id", "label"]) ||
        !validSubject({ kind: x.kind, id: x.id }) ||
        typeof x.label !== "string" ||
        x.label.length > 1000,
    )
  )
    return bad();
  if (
    new Set(v.subject_choices.map((x) => x.kind)).size !==
    v.subject_choices.length
  )
    return bad();
  if (v.head !== null) {
    await validateScopeRecord(v.head, prepared, factId);
    if (
      !v.subject_choices.some(
        (x) =>
          x.kind === v.head!.manifest.subject.kind &&
          x.id === v.head!.manifest.subject.id,
      )
    )
      return bad();
  }
  if (
    v.binding_status === "matches_current_input" &&
    (!v.head ||
      v.head.manifest.action !== "bind" ||
      !v.matches_prepared_input ||
      v.provenance_status !== "verified")
  )
    return bad();
  if (
    (v.binding_status === "withdrawn") !==
    (v.head?.manifest.action === "withdraw")
  )
    return bad();
}
