import type {
  PackageExecutionInputView,
  PackageReviewExecutionContext,
  PackageReviewFrozenInputView,
  SavePackageExecutionInput,
} from "./contracts";
import type { FreezeScope } from "./packageFrozenInput";
import { frozenManifestDigest } from "./packageFrozenInput";
import { matchesExecutionContext } from "./packageReviewContext";
import {
  eligibilityMessages,
  matchesEligibility,
} from "./packageEligibilityObservation";

export const recordObject = (v: unknown): v is Record<string, unknown> =>
  v !== null && typeof v === "object" && !Array.isArray(v);
export const exactKeys = (v: Record<string, unknown>, keys: string[]) =>
  Object.keys(v).sort().join(",") === [...keys].sort().join(",");
export const executionId = (v: unknown): v is string =>
  typeof v === "string" &&
  v.length === 36 &&
  /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(v);
export const executionSha = (v: unknown): v is string =>
  typeof v === "string" && v.length === 64 && /^[a-f0-9]{64}$/.test(v);
export function validExecutionRerun(
  value: unknown,
): value is SavePackageExecutionInput["rerun"] {
  return (
    value === null ||
    (recordObject(value) &&
      exactKeys(value, ["nonce", "reason"]) &&
      executionId(value.nonce) &&
      typeof value.reason === "string" &&
      value.reason.trim() === value.reason &&
      !!value.reason &&
      Array.from(value.reason).length <= 2000)
  );
}
export type ExecutionExpectation = {
  body: SavePackageExecutionInput;
  context: PackageReviewExecutionContext;
};
export const contextKeys = [
  "version",
  "kind",
  "input_digest",
  "semantic_digest",
  "snapshot_digest",
  "as_of",
  "purpose",
  "method_digest",
  "policy_digest",
  "facts_digest",
  "sources_digest",
  "fact_set_id",
  "fact_count",
  "confirmed_fact_count",
  "facts_binding",
  "executor_available",
  "formal_scoring_eligible",
];
export function contextEqual(
  a: PackageReviewExecutionContext,
  b: PackageReviewExecutionContext,
) {
  return contextKeys
    .filter((k) => k !== "as_of" && k !== "snapshot_digest")
    .every((k) => a[k as keyof typeof a] === b[k as keyof typeof b]);
}
function micros(v: unknown): bigint | null {
  if (typeof v !== "string") return null;
  const match = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.(\d{1,6}))?Z$/.exec(
    v,
  );
  const ms = Date.parse(v);
  if (
    !match ||
    !Number.isFinite(ms) ||
    new Date(ms).toISOString().slice(0, 19) !== v.slice(0, 19)
  )
    return null;
  return (
    BigInt(ms) * 1000n + BigInt((match[1] ?? "").padEnd(6, "0").slice(3) || "0")
  );
}
export async function validateExecutionInput(
  value: PackageExecutionInputView,
  scope: FreezeScope,
  frozen: PackageReviewFrozenInputView,
  expected: ExecutionExpectation | string,
) {
  // The prepared snapshot and context snapshot cover different private payloads.
  // Their digests are opaque here; the server verifies the retained bytes.
  const fail = () => {
    throw new Error(
      "执行准备输入响应身份、摘要或边界不符，未确认保存成功；原请求仍保留。",
    );
  };
  const m = value?.manifest;
  if (
    !recordObject(value) ||
    !exactKeys(value, ["manifest", "digest"]) ||
    !recordObject(m) ||
    !exactKeys(m, [
      "version",
      "kind",
      "id",
      "bid_id",
      "package_id",
      "revision_id",
      "inventory_id",
      "frozen_input_id",
      "actor_id",
      "command_id",
      "identity",
      "execution_context",
      "snapshot_digest",
      "originals_verified_at",
      "saved_at",
      "blockers",
      "review_ready",
      "launch_available",
      "publication_authorized",
    ])
  )
    return fail();
  const writing = typeof expected !== "string";
  const identity = m.identity,
    b = identity?.binding,
    c = m.execution_context;
  if (
    m.version !== "package-review-execution-input/1" ||
    m.kind !== "prepared_input" ||
    ![m.id, m.actor_id, m.command_id].every(executionId) ||
    m.bid_id !== scope.bidId ||
    m.package_id !== scope.packageId ||
    m.revision_id !== scope.revisionId ||
    m.inventory_id !== scope.inventoryId ||
    m.frozen_input_id !== frozen.manifest.id ||
    (writing ? m.actor_id !== scope.memberId : m.id !== expected) ||
    ![m.snapshot_digest, value.digest].every(executionSha) ||
    m.review_ready !== false ||
    m.launch_available !== false ||
    m.publication_authorized !== false ||
    !recordObject(identity) ||
    !exactKeys(identity, [
      "version",
      "kind",
      "binding",
      "rerun",
      "content_digest",
      "execution_digest",
    ]) ||
    identity.version !== "package-review-execution/1" ||
    identity.kind !== "identity" ||
    !recordObject(b) ||
    !exactKeys(b, [
      "bid_id",
      "package_id",
      "revision_id",
      "inventory_id",
      "identity_digest",
      "frozen_input_id",
      "frozen_digest",
      "input_digest",
      "evidence_digest",
      "context_digest",
      "method_digest",
      "policy_digest",
      "purpose",
    ]) ||
    b.bid_id !== scope.bidId ||
    b.package_id !== scope.packageId ||
    b.revision_id !== scope.revisionId ||
    b.inventory_id !== scope.inventoryId ||
    b.frozen_input_id !== frozen.manifest.id ||
    b.frozen_digest !== frozen.digest ||
    b.input_digest !== frozen.manifest.input_digest ||
    b.evidence_digest !== frozen.manifest.evidence_digest ||
    b.purpose !== "prebid_compliance" ||
    ![
      b.identity_digest,
      b.frozen_digest,
      b.input_digest,
      b.evidence_digest,
      b.context_digest,
      b.method_digest,
      b.policy_digest,
      identity.content_digest,
      identity.execution_digest,
    ].every(executionSha) ||
    !recordObject(c) ||
    !exactKeys(c, contextKeys) ||
    !matchesExecutionContext(c, b.input_digest, m.originals_verified_at) ||
    c.as_of !== m.originals_verified_at ||
    c.semantic_digest !== b.context_digest ||
    c.method_digest !== b.method_digest ||
    c.policy_digest !== b.policy_digest ||
    !Array.isArray(m.blockers) ||
    !m.blockers.includes("PACKAGE_REVIEW_EXECUTOR_NOT_READY") ||
    !m.blockers.includes("PACKAGE_REVIEW_FACTS_UNPROVEN") ||
    new Set(m.blockers).size !== m.blockers.length ||
    !m.blockers.every((k) =>
      Object.prototype.hasOwnProperty.call(eligibilityMessages, k),
    )
  )
    return fail();
  const rerun = identity.rerun;
  if (
    !matchesEligibility(
      {
        kind: "eligibility_observation",
        frozen_input_id: m.frozen_input_id,
        frozen_digest: b.frozen_digest,
        input_digest: b.input_digest,
        checked_at: m.originals_verified_at,
        current_context: c,
        parse_evidence_status: "matched",
        original_verification: "not_performed",
        review_ready: false,
        launch_available: false,
        publication_authorized: false,
        blockers: m.blockers,
      },
      frozen,
    )
  )
    return fail();
  if (!validExecutionRerun(rerun)) return fail();
  const verified = micros(m.originals_verified_at),
    saved = micros(m.saved_at),
    frozenAt = micros(frozen.manifest.frozen_at);
  if (
    verified === null ||
    saved === null ||
    frozenAt === null ||
    saved < verified ||
    verified < frozenAt
  )
    return fail();
  if (
    writing &&
    (expected.body.frozen_digest !== frozen.digest ||
      expected.body.context_digest !== b.context_digest ||
      !contextEqual(c, expected.context) ||
      JSON.stringify(rerun) !== JSON.stringify(expected.body.rerun) ||
      micros(expected.context.as_of) === null ||
      verified < micros(expected.context.as_of)!)
  )
    return fail();
  if (
    (await frozenManifestDigest({
      version: "package-review-content/1",
      binding: b,
    })) !== identity.content_digest ||
    (await frozenManifestDigest({
      version: "package-review-execution/1",
      content_digest: identity.content_digest,
      rerun,
    })) !== identity.execution_digest ||
    (await frozenManifestDigest(m)) !== value.digest
  )
    return fail();
}
