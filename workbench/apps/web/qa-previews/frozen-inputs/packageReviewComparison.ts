// Synthetic protocol fixtures; no real-model quality claim.
import type {
  PackageReviewComparisonPage,
  PackageReviewComparisonRowSide,
  PackageReviewComparisonRun,
  PackageReviewResult,
  PackageReviewRunView,
} from "../../src/contracts";
import { frozenManifestDigest } from "../../src/packageFrozenInput";
import { packageReviewFixture } from "./packageReview";
import {
  dependencyPlanAssessment,
  dependencyPlanReply,
} from "./dependencyPlan";
import { packageReviewDecisionCurrent } from "./packageReviewDecision";
import { changeId as id } from "./factChange";

type Fixture = Awaited<ReturnType<typeof packageReviewFixture>>;
export async function packageReviewAlternateFixture(
  count = 2,
): Promise<Fixture> {
  const f = await packageReviewFixture(count),
    p = f.props.prepared;
  p.manifest.id = id(210);
  p.manifest.identity.rerun = {
    nonce: id(211),
    reason: "合成复检：核对另一轮修订",
  };
  p.manifest.identity.execution_digest = await frozenManifestDigest({
    version: "package-review-execution/1",
    content_digest: p.manifest.identity.content_digest,
    rerun: p.manifest.identity.rerun,
  });
  p.digest = await frozenManifestDigest(p.manifest);
  f.directory.execution_input_digest = p.digest;
  const request = {
    execution_input_digest: p.digest,
    purpose: "prebid_compliance" as const,
    fact_ids: [],
    dependencies: f.inventory.manifest.requirements.map((row) => ({
      requirement_id: row.rule_id,
      requirement_digest: row.requirement_digest,
      state: "not_needed" as const,
      fact_ids: [],
      evidence_ids: [id(61)],
      reason: "合成复检，逐条核对原文",
    })),
  };
  const assessment = await dependencyPlanAssessment(f, request);
  f.plan = await dependencyPlanReply(
    f,
    {
      ...request,
      assessment_digest: assessment.digest,
      reason: "合成另一轮依赖计划",
    },
    id(209),
  );
  f.body = {
    execution_input_digest: p.digest,
    dependency_plan_id: f.plan.manifest.id,
    dependency_plan_digest: f.plan.digest,
  };
  Object.assign(f.input.manifest, {
    execution_input: {
      id: p.manifest.id,
      digest: p.digest,
      identity: p.manifest.identity,
    },
    dependency_plan: { id: f.plan.manifest.id, digest: f.plan.digest },
    usage_digest: f.plan.manifest.usage.digest,
  });
  f.input.digest = await frozenManifestDigest(f.input.manifest);
  const binding = {
    id: id(212),
    execution_input_id: p.manifest.id,
    execution_input_digest: p.digest,
    execution_digest: p.manifest.identity.execution_digest,
    dependency_plan_id: f.plan.manifest.id,
    dependency_plan_digest: f.plan.digest,
    input_digest: f.input.digest,
  };
  for (const run of [f.run, f.completed]) {
    Object.assign(run, binding);
    run.operation.id = id(213);
    run.operation.input_digest = f.input.digest;
  }
  const result = f.completed.result!.manifest;
  Object.assign(result, {
    run_id: binding.id,
    execution_input_id: binding.execution_input_id,
    execution_input_digest: binding.execution_input_digest,
    execution_digest: binding.execution_digest,
    dependency_plan_id: binding.dependency_plan_id,
    dependency_plan_digest: binding.dependency_plan_digest,
    input_digest: binding.input_digest,
  });
  f.completed.result!.digest = await frozenManifestDigest(result);
  return f;
}
async function summary(f: Fixture): Promise<PackageReviewComparisonRun> {
  const r = f.completed;
  return {
    id: r.id,
    actor_id: r.actor_id,
    created_at: r.created_at,
    scope: r.scope,
    frozen_input_id: r.frozen_input_id,
    frozen_input_digest: r.frozen_input_digest,
    execution_input_id: r.execution_input_id,
    execution_input_digest: r.execution_input_digest,
    execution_digest: r.execution_digest,
    dependency_plan_id: r.dependency_plan_id,
    dependency_plan_digest: r.dependency_plan_digest,
    input_digest: r.input_digest,
    method_digest: r.method_digest,
    result_digest: r.result!.digest,
    requirement_count: r.result!.manifest.requirement_count,
    matrix_coverage: r.result!.manifest.matrix_coverage,
    overall_coverage: "partial",
    human_heads_digest: await frozenManifestDigest(
      await packageReviewDecisionCurrent(f),
    ),
  };
}
async function rowSide(
  row: PackageReviewResult["matrix"][number],
): Promise<PackageReviewComparisonRowSide> {
  return {
    row_digest: await frozenManifestDigest(row),
    requirement_digest: row.requirement_digest,
    rule_digest: row.rule_digest,
    rule_kind: row.rule_kind,
    requirement_statement: row.requirement_statement,
    applicability: row.applicability,
    target_part_ids: row.target_part_ids,
    verdict: row.verdict,
    statement: row.statement,
    limitations: row.limitations,
  };
}
export async function packageReviewComparisonFixture(count = 2) {
  const left = await packageReviewFixture(count),
    right = await packageReviewAlternateFixture(count);
  const result = right.completed.result!.manifest;
  result.matrix[0].verdict = "violated";
  result.matrix[0].statement = "合成机制示例：另一轮存在不符，人工尚未确认。";
  result.counts.satisfied = 0;
  result.counts.violated = 1;
  right.completed.result!.digest = await frozenManifestDigest(result);
  const items = await Promise.all(
    left.completed.result!.manifest.matrix.map(async (a, index) => {
      const b = right.completed.result!.manifest.matrix[index],
        sa = await rowSide(a),
        sb = await rowSide(b);
      return {
        requirement_id: a.requirement_id,
        definition_change: "unchanged" as const,
        machine_row_changed: sa.row_digest !== sb.row_digest,
        verdict_transition: {
          from: a.verdict,
          to: b.verdict,
          changed: a.verdict !== b.verdict,
        },
        left: sa,
        right: sb,
        left_human: null,
        right_human: null,
      };
    }),
  );
  items.sort((a, b) => a.requirement_id.localeCompare(b.requirement_id));
  const manifest = {
    version: "package-review-comparison/1" as const,
    kind: "declared_scope_review_comparison" as const,
    bid_id: left.props.scope.bidId,
    match_policy: "exact_requirement_id_and_definition_digests/1" as const,
    left: await summary(left),
    right: await summary(right),
    input_changes: {
      run_input: true,
      scope: false,
      frozen_input: false,
      prepared_input: true,
      rerun_intent: true,
      requirements: false,
      submitted_documents: false,
      selected_facts: false,
      fact_admission: false,
      dependency_plan: true,
      inventory_proof: false,
      method: false,
      method_fields: [],
    },
    counts: {
      added: 0,
      removed: 0,
      changed: 0,
      unchanged: items.length,
      machine_row_changed: 1,
      verdict_changed: 1,
    },
    overall_coverage: "partial" as const,
    risk_resolution_assessed: false as const,
    inventory_complete: false as const,
    formal_scoring_eligible: false as const,
    submission_eligible: false as const,
    items,
  };
  const digest = await frozenManifestDigest(manifest);
  const page = (offset = 0, limit = 20): PackageReviewComparisonPage => ({
    ...manifest,
    comparison_digest: digest,
    items: items.slice(offset, offset + limit),
    has_more: offset + limit < items.length,
    next_cursor:
      offset + limit < items.length ? `synthetic-${offset + limit}` : null,
  });
  return {
    left,
    right,
    manifest,
    digest,
    page,
    request: {
      bidId: manifest.bid_id,
      leftId: manifest.left.id,
      rightId: manifest.right.id,
    },
  };
}
export function packageReviewOriginalFetch(
  f: Fixture,
  path: string,
):
  | PackageReviewRunView
  | Fixture["props"]["prepared"]
  | Fixture["props"]["frozen"]
  | undefined {
  const { scope, frozen, prepared } = f.props;
  const base = `/bids/${scope.bidId}/packages/${scope.packageId}/revisions/${scope.revisionId}/requirement-inventories/${scope.inventoryId}/frozen-review-inputs/${frozen.manifest.id}`;
  if (path === base) return frozen;
  if (path === `${base}/execution-inputs/${prepared.manifest.id}`)
    return prepared;
  if (
    path ===
    `${base}/execution-inputs/${prepared.manifest.id}/review-runs/${f.completed.id}`
  )
    return f.completed;
}
