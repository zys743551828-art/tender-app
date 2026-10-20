import type {
  CheckPackageInputDependencies,
  PackageInputDependencyAssessment,
  PackageRequirementInventoryView,
  PackageExecutionInputView,
  PackageReviewFrozenInputView,
} from "./contracts";
import type { FreezeScope } from "./packageFrozenInput";
import { frozenManifestDigest } from "./packageFrozenInput";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
export type DependencyProps = {
  scope: FreezeScope;
  frozen: PackageReviewFrozenInputView;
  prepared: PackageExecutionInputView;
};
export type DependencyRequirement =
  PackageRequirementInventoryView["manifest"]["requirements"][number];
export const dependencyInventoryPath = (s: FreezeScope) =>
  `/bids/${s.bidId}/packages/${s.packageId}/revisions/${s.revisionId}/requirement-inventories/${s.inventoryId}`;
export const dependencyPath = (p: DependencyProps) =>
  `${dependencyInventoryPath(p.scope)}/frozen-review-inputs/${p.frozen.manifest.id}/execution-inputs/${p.prepared.manifest.id}/dependency-check`;
const ids = (v: unknown): v is string[] =>
  Array.isArray(v) &&
  v.length <= 500 &&
  v.every(executionId) &&
  new Set(v).size === v.length;
export const ruleEvidenceIds = (r: DependencyRequirement) =>
  ids(r.rule_snapshot.evidence_ids) ? r.rule_snapshot.evidence_ids : [];
export async function validateDependencyInventory(
  v: PackageRequirementInventoryView,
  p: DependencyProps,
) {
  const m = v?.manifest;
  if (
    !m ||
    !["bid-package-requirements/1", "bid-package-requirements/2"].includes(
      m.version,
    ) ||
    m.id !== p.scope.inventoryId ||
    m.bid_id !== p.scope.bidId ||
    m.package_id !== p.scope.packageId ||
    m.target_revision_id !== p.scope.revisionId ||
    !executionSha(v.digest) ||
    !Array.isArray(m.requirements) ||
    m.requirements.length > 10000 ||
    m.inventory_complete !== false ||
    m.review_ready !== false ||
    (await frozenManifestDigest(m)) !== v.digest
  )
    throw new Error("要求清单与此准备输入范围不符，未采用其他版本。");
  const seen = new Set<string>();
  for (const row of m.requirements) {
    if (
      !recordObject(row) ||
      !recordObject(row.rule_snapshot) ||
      !recordObject(row.requirement) ||
      !executionId(row.rule_id) ||
      seen.has(row.rule_id) ||
      row.rule_snapshot.id !== row.rule_id ||
      row.requirement.requirement_id !== row.rule_id ||
      typeof row.source_bound !== "boolean" ||
      (await frozenManifestDigest(row.requirement)) !==
        row.requirement_digest ||
      (await frozenManifestDigest(row.rule_snapshot)) !== row.rule_digest
    )
      throw new Error("要求投影身份或原文摘要不符，未读取该清单。");
    seen.add(row.rule_id);
  }
}
export function validDependencyRequest(
  v: CheckPackageInputDependencies,
  p: DependencyProps,
) {
  if (
    !recordObject(v) ||
    !exactKeys(v, [
      "execution_input_digest",
      "purpose",
      "fact_ids",
      "dependencies",
    ]) ||
    v.execution_input_digest !== p.prepared.digest ||
    v.purpose !== "prebid_compliance" ||
    !ids(v.fact_ids) ||
    !Array.isArray(v.dependencies) ||
    v.dependencies.length > 500
  )
    return false;
  const seen = new Set<string>();
  return v.dependencies.every((d) => {
    if (
      !recordObject(d) ||
      !exactKeys(d, [
        "requirement_id",
        "requirement_digest",
        "state",
        "fact_ids",
        "evidence_ids",
        "reason",
      ]) ||
      !executionId(d.requirement_id) ||
      seen.has(d.requirement_id) ||
      !executionSha(d.requirement_digest) ||
      !["unknown", "required", "not_needed"].includes(d.state) ||
      !ids(d.fact_ids) ||
      (d.state !== "required" && d.fact_ids.length > 0) ||
      !ids(d.evidence_ids) ||
      !d.evidence_ids.length ||
      typeof d.reason !== "string" ||
      !d.reason ||
      d.reason !== d.reason.trim() ||
      Array.from(d.reason).length > 2000
    )
      return false;
    seen.add(d.requirement_id);
    return true;
  });
}
export async function validateDependencyAssessment(
  v: PackageInputDependencyAssessment,
  p: DependencyProps,
  inventory: PackageRequirementInventoryView,
  body: CheckPackageInputDependencies,
) {
  const bad = () => {
    throw new Error("依赖评估的输入身份、逐条结果或资格边界不符，请重新核对。");
  };
  if (
    !validDependencyRequest(body, p) ||
    !recordObject(v) ||
    !exactKeys(v, ["manifest", "digest"]) ||
    !recordObject(v.manifest) ||
    !executionSha(v.digest)
  )
    return bad();
  const m = v.manifest;
  const flags = [
    "inventory_complete",
    "original_bytes_verified",
    "facts_qualified",
    "review_ready",
    "launch_available",
    "publication_authorized",
  ];
  if (
    !exactKeys(m, [
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
      ...flags,
    ]) ||
    m.version !== "package-input-dependencies/1" ||
    m.kind !== "input_dependency_assessment" ||
    m.purpose !== "prebid_compliance" ||
    m.declaration_kind !== "human_dependency_annotation" ||
    !executionSha(m.usage_digest) ||
    !executionSha(m.policy_digest) ||
    flags.some((k) => m[k as keyof typeof m] !== false) ||
    m.frozen_digest !== p.frozen.digest ||
    m.inventory_digest !== inventory.digest ||
    m.selected_fact_count !== body.fact_ids.length ||
    m.requirement_count !== inventory.manifest.requirements.length ||
    !Array.isArray(m.requirements) ||
    m.requirements.length !== m.requirement_count
  )
    return bad();
  const expected = {
    bid_id: p.scope.bidId,
    package_id: p.scope.packageId,
    revision_id: p.scope.revisionId,
    inventory_id: p.scope.inventoryId,
    frozen_input_id: p.frozen.manifest.id,
    execution_input_id: p.prepared.manifest.id,
    execution_input_digest: p.prepared.digest,
  };
  if (
    !recordObject(m.prepared) ||
    !exactKeys(m.prepared, Object.keys(expected)) ||
    Object.entries(expected).some(
      ([k, value]) => m.prepared[k as keyof typeof expected] !== value,
    )
  )
    return bad();
  const rows = [...inventory.manifest.requirements].sort((a, b) =>
    a.rule_id < b.rule_id ? -1 : a.rule_id > b.rule_id ? 1 : 0,
  );
  for (const d of body.dependencies) {
    const row = rows.find((r) => r.rule_id === d.requirement_id);
    if (
      !row ||
      row.requirement_digest !== d.requirement_digest ||
      d.evidence_ids.some((id) => !ruleEvidenceIds(row).includes(id))
    )
      return bad();
  }
  const states = new Set<string>();
  let declared = rows.length > 0;
  for (const [n, r] of rows.entries()) {
    const item = m.requirements[n],
      d = body.dependencies.find((x) => x.requirement_id === r.rule_id);
    if (
      !recordObject(item) ||
      !exactKeys(item, [
        "requirement_id",
        "requirement_digest",
        "declaration",
        "fact_status",
        "unselected_fact_ids",
        "coverage_state",
        "source_bound",
        "applicability",
      ]) ||
      item.requirement_id !== r.rule_id ||
      item.requirement_digest !== r.requirement_digest ||
      item.source_bound !== r.source_bound ||
      item.applicability !== r.requirement.applicability ||
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
      ].includes(item.coverage_state)
    )
      return bad();
    const normalized = d
      ? {
          ...d,
          fact_ids: [...d.fact_ids].sort(),
          evidence_ids: [...d.evidence_ids].sort(),
        }
      : null;
    if (
      (await frozenManifestDigest(item.declaration)) !==
      (await frozenManifestDigest(normalized))
    )
      return bad();
    const missing = d
      ? d.fact_ids.filter((id) => !body.fact_ids.includes(id)).sort()
      : [];
    const status =
      !d || d.state === "unknown" || !r.source_bound
        ? "unknown"
        : d.state === "not_needed"
          ? "not_used"
          : !d.fact_ids.length || missing.length
            ? "missing"
            : "selected_unvalidated";
    if (
      item.fact_status !== status ||
      JSON.stringify(item.unselected_fact_ids) !== JSON.stringify(missing)
    )
      return bad();
    states.add(status);
    declared = declared && !!d && d.state !== "unknown";
  }
  const overall = rows.length
    ? (["missing", "unknown", "selected_unvalidated"].find((x) =>
        states.has(x),
      ) ?? "not_used")
    : "unknown";
  if (
    m.required_facts_assessment !== overall ||
    m.dependency_review_status !== (declared ? "declared" : "incomplete") ||
    m.inventory_status !==
      (inventory.manifest.extraction_binding === "exact_frozen_input_result"
        ? "range_submitted_quality_unmeasured"
        : "unproven") ||
    (await frozenManifestDigest(m)) !== v.digest
  )
    return bad();
}
