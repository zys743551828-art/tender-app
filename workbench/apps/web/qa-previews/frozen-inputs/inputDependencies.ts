import type {
  CheckPackageInputDependencies,
  PackageInputDependencyAssessment,
  PackageRequirementInventoryView,
} from "../../src/contracts";
import { frozenManifestDigest } from "../../src/packageFrozenInput";
import { factChangeFixture, changeId as id } from "./factChange";
import { prepared } from "./prepared";
export async function inputDependencyFixture() {
  const f = await factChangeFixture();
  const execution = await prepared(f.frozen, id(7));
  const requirements = [];
  for (const n of [80, 81]) {
    const rule = {
      id: id(n),
      origin_kind: "model_extracted",
      statement:
        n === 80
          ? "投标文件的合同工期应符合本工程要求。"
          : "按招标文件规定的格式提供技术正文。",
      conditions: [],
      exceptions: [],
      evidence_ids: [id(61)],
    };
    const requirement = {
      requirement_id: id(n),
      scope: f.target.manifest.scope,
      origin: "authority" as const,
      source_refs: [`evidence:${id(61)}`],
      categories: ["technical"],
      target_part_ids: ["technical-body"],
      minimum_count: null,
      applicability: "applicable" as const,
      applicability_evidence: [],
      valid_at: null,
      conditions: [],
      checks: [],
      identity_version: "bid-requirement/1" as const,
    };
    requirements.push({
      rule_id: id(n),
      rule_digest: await frozenManifestDigest(rule),
      rule_snapshot: rule,
      decision_id: null,
      decision_snapshot: null,
      requirement,
      requirement_digest: await frozenManifestDigest(requirement),
      source_bound: true,
      annotation: {
        kind: "human_check_plan_declaration" as const,
        mapped: true,
        reason: "合成检查计划",
        basis_evidence_ids: [id(61)],
      },
    });
  }
  const manifest: PackageRequirementInventoryView["manifest"] = {
    version: "bid-package-requirements/1",
    id: f.scope.inventoryId,
    bid_id: f.scope.bidId,
    package_id: f.scope.packageId,
    target_revision_id: f.scope.revisionId,
    package_digest: f.target.digest,
    authority_revision_id: f.authority.manifest.revision_id,
    authority_digest: f.authority.digest,
    rule_set_id: id(90),
    rule_set_digest: "9".repeat(64),
    revision: 1,
    predecessor_digest: null,
    identity_digest: f.target.identity.digest,
    source_snapshot: [],
    requirements,
    inventory_complete: false,
    extraction_binding: "unproven_legacy_rule_set",
    review_ready: false,
    actor_id: f.scope.memberId,
  };
  const inventory = { manifest, digest: await frozenManifestDigest(manifest) };
  const directory = {
    bid_id: f.scope.bidId,
    package_id: f.scope.packageId,
    revision_id: f.scope.revisionId,
    inventory_id: f.scope.inventoryId,
    frozen_input_id: f.frozen.manifest.id,
    execution_input_id: execution.manifest.id,
    execution_input_digest: execution.digest,
    facts_digest: execution.manifest.execution_context.facts_digest,
    fact_set_id: execution.manifest.execution_context.fact_set_id,
    fact_count: 1,
    items: [
      {
        fact_id: id(51),
        fact_item_digest: "5".repeat(64),
        name: "合同工期",
        subject: "本工程",
        scope: "标段一",
        value_preview: "180",
        unit: "天",
        preview_truncated: false,
      },
    ],
    has_more: false,
    next_cursor: null,
  };
  return {
    props: { scope: f.scope, frozen: f.frozen, prepared: execution },
    inventory,
    directory,
  };
}
export async function dependencyReply(
  f: Awaited<ReturnType<typeof inputDependencyFixture>>,
  body: CheckPackageInputDependencies,
): Promise<PackageInputDependencyAssessment> {
  const requirements = f.inventory.manifest.requirements.map((row) => {
    const d = body.dependencies.find((x) => x.requirement_id === row.rule_id);
    const unselected_fact_ids = d
      ? d.fact_ids.filter((x) => !body.fact_ids.includes(x)).sort()
      : [];
    const fact_status: PackageInputDependencyAssessment["manifest"]["requirements"][number]["fact_status"] =
      !d || d.state === "unknown" || !row.source_bound
        ? "unknown"
        : d.state === "not_needed"
          ? "not_used"
          : !d.fact_ids.length || unselected_fact_ids.length
            ? "missing"
            : "selected_unvalidated";
    return {
      requirement_id: row.rule_id,
      requirement_digest: row.requirement_digest,
      declaration: d
        ? {
            ...d,
            fact_ids: [...d.fact_ids].sort(),
            evidence_ids: [...d.evidence_ids].sort(),
          }
        : null,
      fact_status,
      unselected_fact_ids,
      coverage_state: "not_provided" as const,
      source_bound: row.source_bound,
      applicability: row.requirement.applicability,
    };
  });
  const states = new Set(requirements.map((x) => x.fact_status));
  const overall = requirements.length
    ? ((["missing", "unknown", "selected_unvalidated"] as const).find((x) =>
        states.has(x),
      ) ?? "not_used")
    : "unknown";
  const p = f.props;
  const manifest: PackageInputDependencyAssessment["manifest"] = {
    version: "package-input-dependencies/1",
    kind: "input_dependency_assessment",
    purpose: "prebid_compliance",
    prepared: {
      bid_id: p.scope.bidId,
      package_id: p.scope.packageId,
      revision_id: p.scope.revisionId,
      inventory_id: p.scope.inventoryId,
      frozen_input_id: p.frozen.manifest.id,
      execution_input_id: p.prepared.manifest.id,
      execution_input_digest: p.prepared.digest,
    },
    frozen_digest: p.frozen.digest,
    inventory_digest: f.inventory.digest,
    usage_digest: await frozenManifestDigest({
      synthetic_fact_ids: body.fact_ids,
    }),
    selected_fact_count: body.fact_ids.length,
    requirement_count: requirements.length,
    dependency_review_status:
      requirements.length &&
      requirements.every(
        (x) => x.declaration && x.declaration.state !== "unknown",
      )
        ? "declared"
        : "incomplete",
    required_facts_assessment: overall,
    requirements,
    inventory_status: "unproven",
    declaration_kind: "human_dependency_annotation",
    inventory_complete: false,
    original_bytes_verified: false,
    facts_qualified: false,
    review_ready: false,
    launch_available: false,
    publication_authorized: false,
    policy_digest: "8".repeat(64),
  };
  return { manifest, digest: await frozenManifestDigest(manifest) };
}
