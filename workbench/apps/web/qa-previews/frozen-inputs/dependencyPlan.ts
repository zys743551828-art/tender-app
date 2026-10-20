import type {
  CheckPackageInputDependencies,
  PackageDependencyPlanPage,
  PackageDependencyPlanView,
  SavePackageDependencyPlan,
} from "../../src/contracts";
import { frozenManifestDigest } from "../../src/packageFrozenInput";
import { inputDependencyFixture, dependencyReply } from "./inputDependencies";
import { changeId as id } from "./factChange";
export { inputDependencyFixture as dependencyPlanFixture } from "./inputDependencies";
type Fixture = Awaited<ReturnType<typeof inputDependencyFixture>>;
async function usage(f: Fixture, body: CheckPackageInputDependencies) {
  const p = f.props;
  const selected = [...body.fact_ids].sort().map((fact_id) => {
    const row = f.directory.items.find((item) => item.fact_id === fact_id);
    if (!row) throw new Error("unknown synthetic fact");
    return { fact_id, fact_item_digest: row.fact_item_digest };
  });
  const scope = {
    bid_id: p.scope.bidId,
    package_id: p.scope.packageId,
    revision_id: p.scope.revisionId,
    inventory_id: p.scope.inventoryId,
  };
  const identity_digest = p.prepared.manifest.identity.binding.identity_digest;
  const manifest: PackageDependencyPlanView["manifest"]["usage"]["manifest"] = {
    version: "package-fact-usage/1",
    kind: "fact_usage_selection",
    purpose: "prebid_compliance",
    prepared: {
      ...scope,
      frozen_input_id: p.frozen.manifest.id,
      execution_input_id: p.prepared.manifest.id,
      execution_input_digest: p.prepared.digest,
    },
    identity_digest,
    selected,
    selection_digest: await frozenManifestDigest({
      version: "package-fact-usage-content/1",
      purpose: body.purpose,
      scope,
      identity_digest,
      selected,
    }),
    selected_facts_digest: await frozenManifestDigest({
      synthetic_selected: body.fact_ids,
    }),
    required_facts_assessment: "not_performed",
    facts_qualified: false,
    review_ready: false,
    launch_available: false,
    publication_authorized: false,
  };
  return { manifest, digest: await frozenManifestDigest(manifest) };
}
export async function dependencyPlanAssessment(
  f: Fixture,
  body: CheckPackageInputDependencies,
) {
  const value = await dependencyReply(f, body);
  value.manifest.usage_digest = (await usage(f, body)).digest;
  value.digest = await frozenManifestDigest(value.manifest);
  return value;
}
export async function dependencyPlanReply(
  f: Fixture,
  body: SavePackageDependencyPlan,
  recordId = id(95),
): Promise<PackageDependencyPlanView> {
  const assessment = await dependencyPlanAssessment(f, body);
  if (assessment.digest !== body.assessment_digest)
    throw new Error("synthetic assessment changed");
  const selected = await usage(f, body);
  const manifest: PackageDependencyPlanView["manifest"] = {
    version: "package-dependency-plan/1",
    kind: "human_dependency_plan",
    id: recordId,
    actor_id: f.props.scope.memberId,
    command_id: id(96),
    saved_at: "2026-10-20T12:00:00.000000Z",
    reason: body.reason,
    request_digest: await frozenManifestDigest({ body, if_match: null }),
    prepared: selected.manifest.prepared,
    assessment,
    usage: selected,
    inventory_complete: false,
    facts_qualified: false,
    review_ready: false,
    launch_available: false,
    publication_authorized: false,
  };
  return { manifest, digest: await frozenManifestDigest(manifest) };
}
export function dependencyPlanPage(
  f: Fixture,
  values: PackageDependencyPlanView[],
): PackageDependencyPlanPage {
  const p = f.props;
  return {
    prepared: {
      bid_id: p.scope.bidId,
      package_id: p.scope.packageId,
      revision_id: p.scope.revisionId,
      inventory_id: p.scope.inventoryId,
      frozen_input_id: p.frozen.manifest.id,
      execution_input_id: p.prepared.manifest.id,
      execution_input_digest: p.prepared.digest,
    },
    items: values.map((v) => ({
      id: v.manifest.id,
      digest: v.digest,
      actor_id: v.manifest.actor_id,
      saved_at: v.manifest.saved_at,
      reason: v.manifest.reason,
      assessment_digest: v.manifest.assessment.digest,
      required_facts_assessment:
        v.manifest.assessment.manifest.required_facts_assessment,
      dependency_review_status:
        v.manifest.assessment.manifest.dependency_review_status,
      selected_fact_count: v.manifest.assessment.manifest.selected_fact_count,
      requirement_count: v.manifest.assessment.manifest.requirement_count,
    })),
    has_more: false,
    next_cursor: null,
    inventory_complete: false,
    facts_qualified: false,
    review_ready: false,
    launch_available: false,
    publication_authorized: false,
  };
}
