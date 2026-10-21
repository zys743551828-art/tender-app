// Explicit synthetic protocol fixtures. These are not model-quality measurements.
import type {
  DocumentView,
  EvidenceView,
  Operation,
  PackageReviewResult,
  PackageReviewRunPage,
  PackageReviewRunView,
  PackageReviewRunInputView,
} from "../../src/contracts";
import { frozenManifestDigest } from "../../src/packageFrozenInput";
import { packageReviewScope } from "../../src/packageReviewProtocol";
import {
  dependencyPlanAssessment,
  dependencyPlanFixture,
  dependencyPlanReply,
} from "./dependencyPlan";
import { changeId as id } from "./factChange";

export async function packageReviewFixture(requirementCount = 2) {
  const f = await dependencyPlanFixture();
  f.props.prepared.manifest.execution_context.as_of =
    "2026-10-20T08:03:00.000001Z";
  f.props.prepared.manifest.originals_verified_at =
    f.props.prepared.manifest.execution_context.as_of;
  f.props.prepared.manifest.saved_at = "2026-10-20T08:03:01.000001Z";
  f.props.prepared.digest = await frozenManifestDigest(
    f.props.prepared.manifest,
  );
  f.directory.execution_input_digest = f.props.prepared.digest;
  while (f.inventory.manifest.requirements.length < requirementCount) {
    const index = f.inventory.manifest.requirements.length;
    const row = structuredClone(f.inventory.manifest.requirements[0]);
    row.rule_id = id(5000 + index);
    row.rule_snapshot.id = row.rule_id;
    row.rule_snapshot.statement = `合成容量要求第${index + 1}条`;
    row.requirement.requirement_id = row.rule_id;
    row.rule_digest = await frozenManifestDigest(row.rule_snapshot);
    row.requirement_digest = await frozenManifestDigest(row.requirement);
    f.inventory.manifest.requirements.push(row);
  }
  f.inventory.digest = await frozenManifestDigest(f.inventory.manifest);
  const request = {
    execution_input_digest: f.props.prepared.digest,
    purpose: "prebid_compliance" as const,
    fact_ids: [],
    dependencies: f.inventory.manifest.requirements.map((row) => ({
      requirement_id: row.rule_id,
      requirement_digest: row.requirement_digest,
      state: "not_needed" as const,
      fact_ids: [],
      evidence_ids: [id(61)],
      reason: "合成测试：本条直接核对冻结原文",
    })),
  };
  const assessment = await dependencyPlanAssessment(f, request);
  const plan = await dependencyPlanReply(f, {
    ...request,
    assessment_digest: assessment.digest,
    reason: "合成整包范围核查计划",
  });
  const body = {
    execution_input_digest: f.props.prepared.digest,
    dependency_plan_id: plan.manifest.id,
    dependency_plan_digest: plan.digest,
  };
  const profile: PackageReviewRunInputView["manifest"]["executor_method"]["profile"] =
    {
      engine: "package-review/1",
      purpose: "prebid_compliance",
      assessment: "declared_requirement_response",
      input_scope: "all_frozen_target_and_authority_members",
      model_json_encoding: "finite-json-numbers/1",
      model: "deepseek-flash",
      endpoint: "https://api.deepseek.com",
      source_digest: "d".repeat(64),
      batch_rule_limit: 100,
      batch_limit: 4,
      output_tokens_per_batch: 8192,
      input_character_limit: 240000,
      semantic_quality: "not_measured",
      formal_scoring_eligible: false,
      submission_eligible: false,
    };
  const input: PackageReviewRunInputView = {
    digest: "",
    manifest: {
      version: "package-scope-review-input/1",
      purpose: "prebid_compliance",
      scope: packageReviewScope(f.props),
      frozen_input: {
        id: f.props.frozen.manifest.id,
        digest: f.props.frozen.digest,
        input_digest: f.props.frozen.manifest.input_digest,
        evidence_digest: f.props.frozen.manifest.evidence_digest,
      },
      execution_input: {
        id: f.props.prepared.manifest.id,
        digest: f.props.prepared.digest,
        identity: f.props.prepared.manifest.identity,
      },
      dependency_plan: { id: plan.manifest.id, digest: plan.digest },
      usage_digest: plan.manifest.usage.digest,
      selected_facts_digest: plan.manifest.usage.manifest.selected_facts_digest,
      fact_admission: {
        content_digest: "1".repeat(64),
        proofs_digest: "2".repeat(64),
        policy_digest: "3".repeat(64),
        fact_declarations: [],
      },
      inventory_proof_digest: "4".repeat(64),
      executor_method: { profile, digest: await frozenManifestDigest(profile) },
      model_input_digest: "5".repeat(64),
      limitations: ["INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED"],
    },
  };
  const inputDigest = await frozenManifestDigest(input.manifest);
  input.digest = inputDigest;
  const run: PackageReviewRunView = {
    kind: "package_review_run",
    id: id(110),
    actor_id: f.props.scope.memberId,
    created_at: "2026-10-21T08:00:00.000000Z",
    scope: packageReviewScope(f.props),
    frozen_input_id: f.props.frozen.manifest.id,
    frozen_input_digest: f.props.frozen.digest,
    execution_input_id: f.props.prepared.manifest.id,
    execution_input_digest: f.props.prepared.digest,
    execution_digest: f.props.prepared.manifest.identity.execution_digest,
    dependency_plan_id: plan.manifest.id,
    dependency_plan_digest: plan.digest,
    input_digest: inputDigest,
    method_digest: input.manifest.executor_method.digest,
    operation: {
      id: id(111),
      kind: "package-scope-review",
      state: "queued",
      input_digest: inputDigest,
      handler_version: "package-review/1",
      error_code: null,
      created_at: "2026-10-21T08:00:00.000000Z",
      finished_at: null,
    },
    result: null,
  };
  const documents: PackageReviewResult["submitted_documents"] = [
    {
      package_role: "target",
      member_id: "synthetic-target",
      document_version_id: id(11),
      parse_run_id: id(12),
      file_digest: "a".repeat(64),
      page_count: 10,
      parts: [
        {
          part_id: "technical-body",
          category: "technical",
          first_page: 1,
          last_page: 10,
          shared_attachment: false,
          heading_path: [],
        },
      ],
      evidence_count: 10,
    },
    {
      package_role: "authority",
      member_id: "synthetic-authority",
      document_version_id: id(21),
      parse_run_id: id(22),
      file_digest: "b".repeat(64),
      page_count: 3,
      parts: [
        {
          part_id: "authority-main",
          category: "tender",
          first_page: 1,
          last_page: 3,
          shared_attachment: false,
          heading_path: [],
        },
      ],
      evidence_count: 3,
    },
  ];
  const quotes = documents.map((doc, i) => ({
    package_role: doc.package_role,
    member_id: doc.member_id,
    document_version_id: doc.document_version_id,
    parse_run_id: doc.parse_run_id,
    physical_page: 2,
    part_ids: doc.parts.map((part) => part.part_id),
    evidence_id: id(i ? 61 : 62),
    evidence_digest: "c".repeat(64),
    quote: i
      ? "合成招标原文：合同工期为180天。"
      : "合成投标原文：承诺180天完成。",
  }));
  const matrix = f.inventory.manifest.requirements.map((row, i) => ({
    requirement_id: row.rule_id,
    requirement_digest: row.requirement_digest,
    rule_digest: row.rule_digest,
    rule_kind: "mandatory" as const,
    requirement_statement: String(row.rule_snapshot.statement),
    applicability: row.requirement.applicability,
    target_part_ids: row.requirement.target_part_ids,
    inspected_ranges: [
      {
        member_id: documents[0].member_id,
        document_version_id: documents[0].document_version_id,
        parse_run_id: documents[0].parse_run_id,
        ...documents[0].parts[0],
      },
    ],
    verdict: i ? ("unable_to_judge" as const) : ("satisfied" as const),
    statement: i
      ? "合成机制示例：格式条件未由本次核查证明。"
      : "合成机制示例：所引原文中的工期一致，仍待人工复核。",
    target_quotes: i ? [] : [quotes[0]],
    authority_quotes: [quotes[1]],
    used_fact_ids: [],
    limitations: i ? ["REQUIREMENT_CHECK_UNSUPPORTED"] : [],
    human_review_state: "unreviewed" as const,
  }));
  const manifest: PackageReviewResult = {
    version: "package-scope-review-result/1",
    kind: "declared_package_scope_review",
    purpose: "prebid_compliance",
    run_id: run.id,
    bid_id: run.scope.bid_id,
    input_digest: run.input_digest,
    execution_input_id: run.execution_input_id,
    execution_input_digest: run.execution_input_digest,
    execution_digest: run.execution_digest,
    dependency_plan_id: run.dependency_plan_id,
    dependency_plan_digest: run.dependency_plan_digest,
    method_digest: run.method_digest,
    scope: run.scope,
    submitted_documents: documents,
    requirement_count: matrix.length,
    matrix_coverage: "partial",
    overall_coverage: "partial",
    quality_status: "not_measured",
    inventory_complete: false,
    formal_scoring_eligible: false,
    submission_eligible: false,
    limitations: [
      "INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED",
      "REQUIREMENT_CHECK_UNSUPPORTED",
    ],
    counts: {
      satisfied: 1,
      violated: 0,
      not_found: 0,
      unable_to_judge: matrix.length - 1,
      not_applicable: 0,
    },
    matrix,
  };
  const completed: PackageReviewRunView = {
    ...run,
    operation: {
      ...run.operation,
      state: "succeeded",
      finished_at: "2026-10-21T08:00:30.000000Z",
    },
    result: { manifest, digest: await frozenManifestDigest(manifest) },
  };
  return { ...f, plan, body, input, run, completed, documents, quotes };
}
export function packageReviewPage(
  f: Awaited<ReturnType<typeof packageReviewFixture>>,
  items: PackageReviewRunView[],
): PackageReviewRunPage {
  return {
    scope: f.run.scope,
    frozen_input_id: f.run.frozen_input_id,
    execution_input_id: f.run.execution_input_id,
    execution_input_digest: f.run.execution_input_digest,
    items: items.map((run) => ({
      ...run,
      result: run.result
        ? {
            digest: run.result.digest,
            requirement_count: run.result.manifest.requirement_count,
            matrix_coverage: run.result.manifest.matrix_coverage,
            overall_coverage: run.result.manifest.overall_coverage,
          }
        : null,
    })),
    has_more: false,
    next_cursor: null,
  };
}
export function packageReviewOperation(run: PackageReviewRunView): Operation {
  return {
    id: run.operation.id,
    bid_id: run.scope.bid_id,
    kind: run.operation.kind,
    state: run.operation.state,
    input_digest: run.input_digest,
    handler_version: run.operation.handler_version,
    result_ref: null,
  };
}
export function packageReviewEvidence(
  f: Awaited<ReturnType<typeof packageReviewFixture>>,
  index = 0,
) {
  const q = f.quotes[index],
    original = f.documents[index];
  const evidence: EvidenceView = {
    id: q.evidence_id,
    document_version_id: q.document_version_id,
    parse_run_id: q.parse_run_id,
    physical_page: q.physical_page,
    printed_label: null,
    kind: "text",
    quote: q.quote,
    bbox: null,
    page_width: 600,
    page_height: 800,
    rotation: 0,
    source_status: "published",
  };
  const document: DocumentView = {
    id: q.document_version_id,
    bid_id: f.props.scope.bidId,
    filename: "合成范围核查测试原文.pdf",
    role: index ? "tender" : "body",
    artifact_kind: "source_original",
    sha256: original.file_digest,
    byte_size: 1000,
    media_type: "application/pdf",
    obtained_at: "2026-10-21T07:00:00.000000Z",
    parse_coverage: "complete",
    file_id: id(130 + index),
    file_revision: 1,
    previous_version_id: null,
    file_head_revision: 1,
    file_head_version_id: original.document_version_id,
    source_relation: null,
  };
  return { evidence, document };
}
