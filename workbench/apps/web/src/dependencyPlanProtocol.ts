import type {
  PackageDependencyPlanPage,
  PackageDependencyPlanView,
  SavePackageDependencyPlan,
} from "./contracts";
import type { DependencyProps } from "./inputDependencyProtocol";
import {
  dependencyPath,
  validDependencyRequest,
} from "./inputDependencyProtocol";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
import { frozenManifestDigest } from "./packageFrozenInput";

export type DependencyPlanScope = DependencyProps["scope"] & {
  frozenId: string;
  frozenDigest: string;
  preparedId: string;
  preparedDigest: string;
};
export type PendingDependencyPlan = {
  key: string;
  body: SavePackageDependencyPlan;
};
export const dependencyPlanScope = (
  p: DependencyProps,
): DependencyPlanScope => ({
  ...p.scope,
  frozenId: p.frozen.manifest.id,
  frozenDigest: p.frozen.digest,
  preparedId: p.prepared.manifest.id,
  preparedDigest: p.prepared.digest,
});
export const dependencyPlanPath = (p: DependencyProps) =>
  dependencyPath(p).replace(/\/dependency-check$/, "/dependency-plans");
const flags = [
  "inventory_complete",
  "facts_qualified",
  "review_ready",
  "launch_available",
  "publication_authorized",
];
const factStates = ["unknown", "missing", "selected_unvalidated", "not_used"];
const text = (v: unknown, max: number): v is string =>
  typeof v === "string" && v.length > 0 && v.length <= max && v.trim() === v;
const ids = (v: unknown): v is string[] =>
  Array.isArray(v) &&
  v.length <= 500 &&
  v.every(executionId) &&
  new Set(v).size === v.length;
const count = (v: unknown): v is number =>
  Number.isSafeInteger(v) && Number(v) >= 0;
const allFalse = (v: Record<string, unknown>) =>
  flags.every((k) => v[k] === false);
const time = (v: unknown): v is string => {
  if (
    typeof v !== "string" ||
    !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$/.test(v) ||
    !Number.isFinite(Date.parse(v))
  )
    return false;
  return new Date(v).toISOString() === v.replace(/(\.\d{3})\d{3}Z$/, "$1Z");
};
const prepared = (s: DependencyPlanScope) => ({
  bid_id: s.bidId,
  package_id: s.packageId,
  revision_id: s.revisionId,
  inventory_id: s.inventoryId,
  frozen_input_id: s.frozenId,
  execution_input_id: s.preparedId,
  execution_input_digest: s.preparedDigest,
});
function binding(v: unknown, s: DependencyPlanScope) {
  const expected = prepared(s);
  return (
    recordObject(v) &&
    exactKeys(v, Object.keys(expected)) &&
    Object.entries(expected).every(([k, x]) => v[k] === x)
  );
}
export function validPlanBody(
  v: unknown,
  p: DependencyProps,
): v is SavePackageDependencyPlan {
  if (
    !recordObject(v) ||
    !exactKeys(v, [
      "execution_input_digest",
      "purpose",
      "fact_ids",
      "dependencies",
      "assessment_digest",
      "reason",
    ]) ||
    !executionSha(v.assessment_digest) ||
    !text(v.reason, 2000)
  )
    return false;
  return validDependencyRequest(
    {
      execution_input_digest: v.execution_input_digest,
      purpose: v.purpose,
      fact_ids: v.fact_ids,
      dependencies: v.dependencies,
    } as SavePackageDependencyPlan,
    p,
  );
}
export function validPendingPlan(
  v: unknown,
  p: DependencyProps,
): v is PendingDependencyPlan {
  return (
    recordObject(v) &&
    exactKeys(v, ["key", "body"]) &&
    executionId(v.key) &&
    validPlanBody(v.body, p)
  );
}
export function validPlanPage(
  v: unknown,
  s: DependencyPlanScope,
): v is PackageDependencyPlanPage {
  if (
    !recordObject(v) ||
    !exactKeys(v, ["prepared", "items", "has_more", "next_cursor", ...flags]) ||
    !binding(v.prepared, s) ||
    !allFalse(v) ||
    !Array.isArray(v.items) ||
    v.items.length > 20 ||
    typeof v.has_more !== "boolean"
  )
    return false;
  let prior = "";
  const seen = new Set<string>();
  for (const item of v.items) {
    if (
      !recordObject(item) ||
      !exactKeys(item, [
        "id",
        "digest",
        "actor_id",
        "saved_at",
        "reason",
        "assessment_digest",
        "required_facts_assessment",
        "dependency_review_status",
        "selected_fact_count",
        "requirement_count",
      ]) ||
      !executionId(item.id) ||
      seen.has(item.id) ||
      !executionId(item.actor_id) ||
      !executionSha(item.digest) ||
      !executionSha(item.assessment_digest) ||
      !time(item.saved_at) ||
      !text(item.reason, 2000) ||
      !factStates.includes(String(item.required_facts_assessment)) ||
      !["incomplete", "declared"].includes(
        String(item.dependency_review_status),
      ) ||
      !count(item.selected_fact_count) ||
      item.selected_fact_count > 500 ||
      !count(item.requirement_count)
    )
      return false;
    const position = `${item.saved_at}/${item.id}`;
    if (prior && position <= prior) return false;
    prior = position;
    seen.add(item.id);
  }
  return v.has_more
    ? v.items.length > 0 && text(v.next_cursor, 4096)
    : v.next_cursor === null;
}

export async function validatePlan(
  v: PackageDependencyPlanView,
  p: DependencyProps,
  pending?: PendingDependencyPlan,
) {
  const bad = () => {
    throw new Error(
      "计划历史或回执的原身份、摘要和资格边界不符，未决原请求仍保留。",
    );
  };
  const s = dependencyPlanScope(p);
  if (
    !recordObject(v) ||
    !exactKeys(v, ["manifest", "digest"]) ||
    !executionSha(v.digest) ||
    !recordObject(v.manifest)
  )
    return bad();
  const m = v.manifest;
  if (
    !exactKeys(m, [
      "version",
      "kind",
      "id",
      "actor_id",
      "command_id",
      "saved_at",
      "reason",
      "request_digest",
      "prepared",
      "assessment",
      "usage",
      ...flags,
    ]) ||
    m.version !== "package-dependency-plan/1" ||
    m.kind !== "human_dependency_plan" ||
    ![m.id, m.actor_id, m.command_id].every(executionId) ||
    !time(m.saved_at) ||
    !text(m.reason, 2000) ||
    !executionSha(m.request_digest) ||
    !binding(m.prepared, s) ||
    !allFalse(m)
  )
    return bad();
  const av = m.assessment,
    uv = m.usage;
  if (
    !recordObject(av) ||
    !exactKeys(av, ["manifest", "digest"]) ||
    !recordObject(av.manifest) ||
    !executionSha(av.digest) ||
    !recordObject(uv) ||
    !exactKeys(uv, ["manifest", "digest"]) ||
    !recordObject(uv.manifest) ||
    !executionSha(uv.digest)
  )
    return bad();
  const a = av.manifest,
    u = uv.manifest;
  if (
    !exactKeys(a, [
      "version",
      "kind",
      "purpose",
      "prepared",
      "frozen_digest",
      "inventory_digest",
      "usage_digest",
      "selected_fact_count",
      "requirement_count",
      "dependency_review_status",
      "required_facts_assessment",
      "requirements",
      "inventory_status",
      "declaration_kind",
      "policy_digest",
      "original_bytes_verified",
      ...flags,
    ]) ||
    a.version !== "package-input-dependencies/1" ||
    a.kind !== "input_dependency_assessment" ||
    a.purpose !== "prebid_compliance" ||
    a.declaration_kind !== "human_dependency_annotation" ||
    !binding(a.prepared, s) ||
    a.frozen_digest !== s.frozenDigest ||
    ![a.inventory_digest, a.policy_digest].every(executionSha) ||
    a.usage_digest !== uv.digest ||
    a.original_bytes_verified !== false ||
    !allFalse(a) ||
    !["incomplete", "declared"].includes(a.dependency_review_status) ||
    !factStates.includes(a.required_facts_assessment) ||
    !["unproven", "range_submitted_quality_unmeasured"].includes(
      a.inventory_status,
    ) ||
    !count(a.requirement_count) ||
    a.requirement_count > 10000 ||
    !Array.isArray(a.requirements) ||
    a.requirements.length !== a.requirement_count ||
    !count(a.selected_fact_count) ||
    a.selected_fact_count > 500
  )
    return bad();
  if (
    !exactKeys(u, [
      "version",
      "kind",
      "purpose",
      "prepared",
      "identity_digest",
      "selected",
      "selection_digest",
      "selected_facts_digest",
      "required_facts_assessment",
      "facts_qualified",
      "review_ready",
      "launch_available",
      "publication_authorized",
    ]) ||
    u.version !== "package-fact-usage/1" ||
    u.kind !== "fact_usage_selection" ||
    u.purpose !== "prebid_compliance" ||
    !binding(u.prepared, s) ||
    u.identity_digest !==
      p.prepared.manifest.identity.binding.identity_digest ||
    ![u.selection_digest, u.selected_facts_digest].every(executionSha) ||
    u.required_facts_assessment !== "not_performed" ||
    flags
      .filter((k) => k !== "inventory_complete")
      .some((k) => u[k as keyof typeof u] !== false) ||
    !Array.isArray(u.selected) ||
    u.selected.length !== a.selected_fact_count
  )
    return bad();
  const selected: string[] = [];
  for (const item of u.selected) {
    if (
      !recordObject(item) ||
      !exactKeys(item, ["fact_id", "fact_item_digest"]) ||
      !executionId(item.fact_id) ||
      !executionSha(item.fact_item_digest) ||
      (selected.length > 0 && selected[selected.length - 1] >= item.fact_id)
    )
      return bad();
    selected.push(item.fact_id);
  }
  const seen = new Set<string>();
  for (const row of a.requirements) {
    if (
      !recordObject(row) ||
      !exactKeys(row, [
        "requirement_id",
        "requirement_digest",
        "declaration",
        "fact_status",
        "unselected_fact_ids",
        "coverage_state",
        "source_bound",
        "applicability",
      ]) ||
      !executionId(row.requirement_id) ||
      seen.has(row.requirement_id) ||
      !executionSha(row.requirement_digest) ||
      !factStates.includes(row.fact_status) ||
      !ids(row.unselected_fact_ids) ||
      typeof row.source_bound !== "boolean" ||
      !["applicable", "unknown", "not_applicable"].includes(
        row.applicability,
      ) ||
      ![
        "not_provided",
        "missing",
        "pending_parse",
        "parse_gap",
        "unsupported",
        "verified",
        "not_applicable",
        "conflict",
        "unknown",
      ].includes(row.coverage_state)
    )
      return bad();
    seen.add(row.requirement_id);
    const d = row.declaration;
    if (
      d !== null &&
      (!recordObject(d) ||
        d.requirement_id !== row.requirement_id ||
        d.requirement_digest !== row.requirement_digest)
    )
      return bad();
  }
  const checkRequest = {
    execution_input_digest: p.prepared.digest,
    purpose: "prebid_compliance" as const,
    fact_ids: selected,
    dependencies: a.requirements.flatMap((r) =>
      r.declaration ? [r.declaration] : [],
    ),
  };
  if (!validDependencyRequest(checkRequest, p)) return bad();
  if (
    pending &&
    (!validPendingPlan(pending, p) ||
      m.actor_id !== s.memberId ||
      m.reason !== pending.body.reason ||
      av.digest !== pending.body.assessment_digest ||
      (await frozenManifestDigest({ body: pending.body, if_match: null })) !==
        m.request_digest ||
      JSON.stringify(selected) !==
        JSON.stringify([...pending.body.fact_ids].sort()))
  )
    return bad();
  if (
    (await frozenManifestDigest({
      version: "package-fact-usage-content/1",
      purpose: u.purpose,
      scope: {
        bid_id: s.bidId,
        package_id: s.packageId,
        revision_id: s.revisionId,
        inventory_id: s.inventoryId,
      },
      identity_digest: u.identity_digest,
      selected: u.selected,
    })) !== u.selection_digest ||
    (await frozenManifestDigest(a)) !== av.digest ||
    (await frozenManifestDigest(u)) !== uv.digest ||
    (await frozenManifestDigest(m)) !== v.digest
  )
    return bad();
}
