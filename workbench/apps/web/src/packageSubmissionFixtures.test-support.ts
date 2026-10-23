// Synthetic frontend protocol fixtures. Original-byte/PG acceptance is separate.
import type {
  PackageReviewRunView,
  PackageSubmissionAppliedView,
  PackageSubmissionBindingView,
  PackageSubmissionPreview,
  PackageSubmissionRequest,
  SingleBodySubmissionView,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import { historicalDateTime } from "./historicalImportProtocol";
import {
  correctionFixture,
  correctionId as id,
  correctionPackage,
  correctionScope,
} from "./packageRuleCorrectionFixtures.test-support";
import type {
  PendingPackageSubmission,
  SubmissionRunTarget,
} from "./packageSubmissionProtocol";
export { id as submissionId };
export const submissionScope = {
  bidId: correctionScope.bidId,
  memberId: correctionScope.memberId,
};
export const submissionEtag = (n = 1) =>
  `"bid:${submissionScope.bidId}:${String(n).repeat(64)}"`;
const sha = (n: number) => String(n).repeat(64);
export async function submissionFixture(
  withInventory = false,
  head: PackageSubmissionPreview["current_submission_head"] = null,
) {
  const target = structuredClone(correctionPackage);
  target.digest = await jsonDigest(target.manifest);
  const selection: PackageSubmissionPreview["selection"] = {
    target,
    authority: null,
    inventory: null,
    coverage: null,
  };
  if (withInventory) {
    const f = await correctionFixture();
    const authority = structuredClone(target);
    authority.manifest.kind = "authority";
    authority.manifest.package_id = id(90);
    authority.manifest.revision_id = id(6);
    authority.manifest.members[0].member_id = "招标依据";
    authority.manifest.members[0].document_version_id = id(41);
    authority.digest = await jsonDigest(authority.manifest);
    f.inventory.manifest.package_digest = target.digest;
    f.inventory.manifest.authority_digest = authority.digest;
    f.inventory.digest = await jsonDigest(f.inventory.manifest);
    selection.authority = authority;
    selection.inventory = f.inventory;
  }
  const request: PackageSubmissionPreview["selection_request"] = {
    package_id: target.manifest.package_id,
    revision_id: target.manifest.revision_id,
    package_digest: target.digest,
    inventory: selection.inventory
      ? {
          id: selection.inventory.manifest.id,
          digest: selection.inventory.digest,
        }
      : null,
    coverage: null,
    review_run: null,
  };
  const context = {
    fixture: "synthetic client mechanism only",
    current: { current: { identity: target.identity } },
    current_submission_head: head,
    method_digest: sha(4),
  };
  const manifest: PackageSubmissionPreview["gate"]["manifest"] = {
    version: "package-submission-gate/1",
    kind: "current_package_submission_observation",
    subject: {
      kind: "bid_package",
      bid_id: submissionScope.bidId,
      package_id: request.package_id,
      revision_id: request.revision_id,
      package_digest: request.package_digest,
      identity_digest: target.identity.digest,
    },
    selection: {
      digest: sha(5),
      authority_revision_id: selection.authority?.manifest.revision_id ?? null,
      authority_digest: selection.authority?.digest ?? null,
      inventory_id: request.inventory?.id ?? null,
      inventory_digest: request.inventory?.digest ?? null,
      coverage_attempt_id: null,
      coverage_digest: null,
      run_id: null,
      result_digest: null,
    },
    checked_at: "2025-06-01T08:00:00.123456Z",
    policy_digest: context.method_digest,
    gates: {
      current_input: {
        state: "unknown",
        codes: ["ORIGINAL_BYTES_NOT_CHECKED"],
        scope: "current_metadata_observation",
        observations_digest: sha(6),
        current_identity_digest: target.identity.digest,
        original_verification: "not_performed",
        member_count: withInventory ? 2 : 1,
        physical_page_gaps: [],
      },
      core_coverage: {
        state: "unknown",
        codes: ["INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED"],
        scope: "known_inventory_core_rules",
        inventory_proof_digest: null,
        run_id: null,
        active_core_count: 0,
        judged_core_count: 0,
        unknown_core_count: 0,
        unfavorable_core_count: 0,
        human_declared_count: 0,
        extraction_range_proven: false,
        inventory_complete: false,
        quality_status: "not_measured",
        overall_coverage: "unknown",
      },
      mandatory_confirmation: {
        state: "unknown",
        codes: ["REQUIREMENT_INVENTORY_NOT_SELECTED"],
        scope: "known_inventory_core_rules",
        core_rule_count: 0,
        confirmed_count: 0,
        pending_rule_ids: [],
        inactive_rule_ids: [],
        needs_revalidation_rule_ids: [],
        decisions: [],
      },
      known_blocking_risks: {
        state: "pass",
        codes: [],
        scope: "whole_bid_known_history",
        history_digest: sha(7),
        history_complete: true,
        runs_read: 0,
        result_rows_read: 0,
        unknown_run_ids: [],
        blocked_count: 0,
        unknown_count: 0,
        risks: [],
      },
    },
    state: "unknown",
    allowed: false,
    inventory_complete: false,
    quality_status: "not_measured",
    formal_scoring_eligible: false,
    submission_eligible: false,
    publication_authorized: false,
    platform_submission_verified: false,
    limitations: [
      "INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED",
      "REGISTRATION_IS_NOT_PLATFORM_SUBMISSION",
    ],
  };
  const input_digest = await jsonDigest({
    selection,
    selection_request: request,
    context,
    review_run: null,
    inventory_proof: null,
  });
  const preview: PackageSubmissionPreview = {
    selection,
    selection_request: request,
    gate: { manifest, digest: await jsonDigest(manifest) },
    input_digest,
    bid_etag: submissionEtag(),
    current_submission_head: head,
  };
  const doc = {
    document_version_id: target.manifest.members[0].document_version_id,
    digest: target.manifest.members[0].file_digest,
    byte_size: 101,
    media_type: "application/pdf",
    artifact_kind: "bid_body",
    original_name: "合成实际投标原件.pdf",
  };
  const body: PackageSubmissionRequest = {
    kind: "offline_fact",
    selection: request,
    input_digest,
    evidence: {
      document_version_id: doc.document_version_id,
      digest: doc.digest,
      byte_size: doc.byte_size,
    },
    submitted_at: "2025-01-02T10:30:00.123456+08:00",
    explanation: "合成线下提交事实，未宣称事前系统检查通过。",
    expected_head: head ? { id: head.id, revision: head.revision } : null,
    correction_reason: head ? "据实追加整包更正，原记录保留。" : null,
  };
  return { target, selection, context, preview, doc, body };
}
export type SubmissionFixture = Awaited<ReturnType<typeof submissionFixture>>;
export async function submissionReceipt(
  f: SubmissionFixture,
  pending: PendingPackageSubmission,
  number = 100,
): Promise<PackageSubmissionAppliedView> {
  const command_id = id(number + 1),
    submission_id = id(number);
  const request_digest = await jsonDigest({
    body: {
      scope: [
        submissionScope.bidId,
        pending.body.selection.package_id,
        pending.body.selection.revision_id,
      ],
      supersedes_id: pending.supersedesId,
      ...pending.body,
    },
    if_match: pending.etag,
  });
  const originals: PackageSubmissionBindingView["manifest"]["originals"] =
    f.selection.target.manifest.members.map((m) => ({
      ...f.doc,
      document_version_id: m.document_version_id,
      digest: m.file_digest,
      roles: [
        "target",
        ...(m.document_version_id === pending.body.evidence.document_version_id
          ? ["submission_attachment" as const]
          : []),
      ],
    }));
  if (f.selection.authority)
    originals.push(
      ...f.selection.authority.manifest.members.map((m) => ({
        ...f.doc,
        document_version_id: m.document_version_id,
        digest: m.file_digest,
        original_name: "合成招标依据.pdf",
        roles: ["authority" as const],
      })),
    );
  const evidence = originals.find(
    (o) => o.document_version_id === pending.body.evidence.document_version_id,
  )!;
  const m: PackageSubmissionBindingView["manifest"] = {
    version: "package-submission-binding/1",
    submission_id,
    bid_id: submissionScope.bidId,
    subject: {
      kind: "bid_package",
      bid_id: submissionScope.bidId,
      package_id: pending.body.selection.package_id,
      revision_id: pending.body.selection.revision_id,
      package_digest: pending.body.selection.package_digest,
    },
    selection: f.selection,
    selection_request: pending.body.selection,
    package_identity: f.target.identity,
    recorded_identity: {
      ...f.target.identity,
      lot_id: f.target.manifest.scope.lot_id,
      identity_version: "bid-identity/2",
    },
    submitted_at: historicalDateTime(pending.body.submitted_at),
    recorded_at: "2025-06-01T08:00:00.223456Z",
    assessed_at: f.preview.gate.manifest.checked_at,
    actor_id: submissionScope.memberId,
    command_id,
    request: pending.body,
    request_digest,
    if_match: pending.etag,
    input_digest: pending.body.input_digest,
    context: f.context,
    review_run: null,
    inventory_proof: null,
    gate: f.preview.gate,
    originals,
    evidence,
    attachment_sources: [],
    supersedes_id: pending.supersedesId,
    head_revision: (pending.body.expected_head?.revision ?? 0) + 1,
    platform_submission_verified: false,
    pre_submission_system_check_verified: false,
    original_bytes_verified: true,
  };
  return {
    submission: {
      id: submission_id,
      bid_id: submissionScope.bidId,
      subject_kind: "bid_package",
      body_version_id: null,
      review_id: null,
      kind: pending.body.kind,
      submitted_at: m.submitted_at,
      recorded_at: m.recorded_at,
      recorded_by: m.actor_id,
      gate_checked: false,
      evidence_ref: m.evidence.document_version_id,
      current: true,
      supersedes_id: m.supersedes_id,
      identity: m.package_identity,
      original_name: null,
      artifact_kind: null,
      checks_label: "未经过系统完整检查；已记录完整投标包实际提交事实",
      open_risk_snapshot: m.gate.manifest.gates.known_blocking_risks,
      platform_submission_verified: false,
      explanation: pending.body.explanation,
      correction_reason: pending.body.correction_reason,
      package_binding: { manifest: m, digest: await jsonDigest(m) },
    },
    command: {
      command_id,
      actor_id: m.actor_id,
      idempotency_key: pending.key,
      request_digest,
      request: pending.body,
      if_match: pending.etag,
    },
  };
}
export function singleSubmission(
  f: SubmissionFixture,
): SingleBodySubmissionView {
  return {
    id: id(120),
    bid_id: submissionScope.bidId,
    body_version_id: f.doc.document_version_id,
    review_id: null,
    kind: "offline_fact",
    submitted_at: f.body.submitted_at,
    recorded_by: submissionScope.memberId,
    gate_checked: false,
    evidence_ref: f.doc.document_version_id,
    current: true,
    supersedes_id: null,
    identity: f.target.identity,
    original_name: "旧单稿实际提交.pdf",
    artifact_kind: "bid_body",
    checks_label: "未经过系统完整检查",
    open_risk_snapshot: null,
    platform_submission_verified: false,
    explanation: "旧单稿实际提交声明。",
    correction_reason: null,
  };
}
export function submissionRunFixture(f: SubmissionFixture) {
  if (!f.preview.selection_request.inventory)
    throw new Error("fixture requires inventory");
  const scope = {
    bid_id: submissionScope.bidId,
    package_id: f.target.manifest.package_id,
    revision_id: f.target.manifest.revision_id,
    inventory_id: f.preview.selection_request.inventory.id,
  };
  const run: PackageReviewRunView = {
    kind: "package_review_run",
    id: id(150),
    actor_id: submissionScope.memberId,
    created_at: "2025-01-01T00:00:00Z",
    scope,
    frozen_input_id: id(151),
    frozen_input_digest: sha(1),
    execution_input_id: id(152),
    execution_input_digest: sha(2),
    execution_digest: sha(3),
    dependency_plan_id: id(153),
    dependency_plan_digest: sha(4),
    input_digest: sha(5),
    method_digest: sha(6),
    operation: {
      id: id(154),
      kind: "package-scope-review",
      state: "failed",
      input_digest: sha(5),
      handler_version: "package-review/1",
      error_code: "SYNTHETIC_TEST",
      created_at: "2025-01-01T00:00:00Z",
      finished_at: "2025-01-01T00:01:00Z",
    },
    result: null,
  };
  const target: SubmissionRunTarget = {
    id: run.id,
    target_kind: "package_review_run",
    created_at: run.created_at,
    input_digest: run.input_digest,
    execution_input_id: run.execution_input_id,
    state: run.operation.state,
    package_id: scope.package_id,
    revision_id: scope.revision_id,
    inventory_id: scope.inventory_id,
    frozen_input_id: run.frozen_input_id,
    result_digest: null,
  };
  return { run, target };
}
