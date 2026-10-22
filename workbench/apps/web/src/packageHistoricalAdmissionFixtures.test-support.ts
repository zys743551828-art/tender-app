// Explicit UI mechanism fixtures. Existing synthetic scope metadata is reused as
// a parent identity; the new context and acknowledgement below are simulated.
// They are never described as one native database run or real historical proof.
import raw from "./test-fixtures/technical-eligibility-catalog-http.json";
import type {
  PackageHistoricalAdmission,
  PackageHistoricalAdmissionContext,
  PackageSubmissionView,
  PackageTechnicalScopeView,
  ResearchOutcomeView,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import { historyEtag } from "./packageHistoricalResearchProtocol";

export async function historyAdmissionFixture() {
  const saved = structuredClone(
    raw.scope,
  ) as unknown as PackageTechnicalScopeView;
  const submission = structuredClone(
    raw.submissions.items[0],
  ) as unknown as PackageSubmissionView;
  const outcome = structuredClone(
    raw.outcomes.items[0],
  ) as unknown as ResearchOutcomeView;
  const scope = saved.manifest.preview.manifest.scope;
  const memberId = "10000000-0000-4000-8000-000000000001";
  const proofId = "20000000-0000-4000-8000-000000000001";
  const context: PackageHistoricalAdmissionContext = {
    schema: "package-historical-admission-context/1",
    schema_configured: true,
    scope_id: saved.manifest.id,
    submission_id: submission.id,
    outcome_id: outcome.id,
    context_digest: "a".repeat(64),
    official_technical_value: outcome.value,
    official_maximum: outcome.maximum,
    historical_as_of: submission.submitted_at,
    scope_frozen_at: saved.manifest.frozen_at,
    label_known_at: outcome.known_at,
    proofs: [
      {
        id: proofId,
        origin: "synthetic",
        adapter_id: "30000000-0000-4000-8000-000000000001",
        verified_at: "2026-10-22T00:00:00Z",
        context_digest: "a".repeat(64),
      },
    ],
    blockers: [
      {
        code: "PACKAGE_HISTORY_EXTERNAL_PROOF_ADAPTER_NOT_CONFIGURED",
        message: "真实证明接入来源尚未配置；签名本身不证明事实真实。",
      },
    ],
    research_only: true,
    formal_eligibility: "unavailable",
    strict_prebid_eligible: false,
    online_metrics_eligible: false,
    formal_sample_created: false,
    observed_at: "2026-10-22T01:00:00Z",
  };
  const document: Omit<PackageHistoricalAdmission, "digest"> = {
    schema: "package-historical-research-admission/1",
    id: "40000000-0000-4000-8000-000000000001",
    proof_id: proofId,
    bid_id: scope.bid_id,
    scope_id: saved.manifest.id,
    scope_digest: saved.digest,
    submission_id: submission.id,
    submission_binding_digest: submission.package_binding.digest,
    outcome_id: outcome.id,
    context_digest: context.context_digest!,
    proof_digest: "b".repeat(64),
    origin: "synthetic",
    state: "mechanism_candidate",
    historical_as_of: submission.submitted_at,
    scope_frozen_at: saved.manifest.frozen_at,
    label_known_at: outcome.known_at,
    evidence_verified_at: context.proofs[0].verified_at,
    admitted_at: "2026-10-22T01:01:00Z",
    official_technical_value: outcome.value!,
    technical_maximum: outcome.maximum!,
    aggregation: "published_final_technical_total",
    training_selected: false,
    research_only: true,
    formal_eligibility: "unavailable",
    strict_prebid_eligible: false,
    online_metrics_eligible: false,
    formal_sample_created: false,
  };
  const admission = { ...document, digest: await jsonDigest(document) };
  return {
    saved,
    submission,
    outcome,
    memberId,
    proofId,
    context,
    admission,
    contextEtag: await historyEtag("context", saved.manifest.id, context),
    admissionEtag: await historyEtag("admission", admission.id, admission),
    base: raw.basePath.replace("/api/v1", ""),
    workspace: `admission:${scope.bid_id}:${saved.manifest.id}`,
  };
}
