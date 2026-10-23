// Synthetic frontend fixtures only. Native PostgreSQL and byte acceptance are separate.
import type {
  DocumentEvidenceView,
  OutcomeRequest,
  PackageOutcomeContext,
  PackageOutcomeVerificationDetails,
  PackageOutcomeVerificationRequest,
  ResearchOutcomeDetail,
  ResearchOutcomePage,
  ResearchOutcomeView,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  outcomeAuthority,
  outcomeIdentity,
  packageOutcomeScope,
} from "./packageOutcomeProtocol";
import {
  submissionEtag,
  submissionFixture,
  submissionId as id,
  submissionReceipt,
  submissionScope,
} from "./packageSubmissionFixtures.test-support";
export { id as outcomeId };

export async function outcomeFixture(withAuthority = true) {
  const sourceId = id(500),
    evidenceId = id(501);
  const f = await submissionFixture(withAuthority);
  const ack = await submissionReceipt(f, {
    key: id(499),
    body: f.body,
    etag: submissionEtag(),
    supersedesId: null,
  });
  const submission = ack.submission;
  const m = submission.package_binding.manifest;
  const scope = packageOutcomeScope(
    submission.bid_id,
    submissionScope.memberId,
    submission,
  );
  const context: PackageOutcomeContext = {
    subject_kind: "bid_package",
    bid_id: scope.bidId,
    submission_id: submission.id,
    body_version_id: null,
    identity: outcomeIdentity(submission),
    authority: outcomeAuthority(submission),
    package_identity: m.package_identity,
    recorded_identity: m.recorded_identity,
    package_binding: submission.package_binding,
    display: {
      project_title: m.package_identity.engineering_title,
      lot: m.package_identity.lot,
      round_no: m.package_identity.round_no,
      bidder_name: m.package_identity.bidder_name,
      body_filename: null,
    },
    submitted_at: submission.submitted_at,
    kind: submission.kind,
    source_candidates: [
      {
        id: sourceId,
        original_name: "合成官方技术成绩.pdf",
        obtained_at: "2025-06-02T01:00:00Z",
      },
    ],
    identity_ready: true,
    identity_status: "confirmed",
    identity_reason: null,
    verification_blockers: withAuthority
      ? []
      : ["PACKAGE_OUTCOME_AUTHORITY_MISSING"],
    verification_requires_source_evidence: true,
    formal_sample_eligible: false,
    formal_sample_blockers: ["package_formal_sample_not_supported"],
  };
  const body: OutcomeRequest = {
    submission_id: submission.id,
    score_kind: "technical_total",
    value: "0.00",
    maximum: "100.00",
    source_version_id: sourceId,
    known_at: "2025-06-02T10:30:00.123456+08:00",
  };
  const view: ResearchOutcomeView = {
    ...body,
    id: id(502),
    bid_id: scope.bidId,
    verification: "pending",
    verification_revision: 0,
    supersedes_id: null,
    verification_details: null,
  };
  const detail: ResearchOutcomeDetail = {
    ...view,
    current: true,
    package_association: {
      available: false,
      reasons: ["package_outcome_verification_unproven"],
      checked_at: "2025-06-03T00:00:01Z",
      scope: "official_outcome_association",
      formal_sample_eligible: false,
    },
  };
  const page: ResearchOutcomePage = {
    items: [view],
    heads: [
      {
        bid_id: scope.bidId,
        submission_id: submission.id,
        outcome_id: view.id,
        revision: 1,
      },
    ],
  };
  const evidence: DocumentEvidenceView = {
    document_version_id: sourceId,
    parse_run_id: id(503),
    coverage: "complete",
    gaps: [],
    items: [
      {
        id: evidenceId,
        document_version_id: sourceId,
        parse_run_id: id(503),
        physical_page: 2,
        printed_label: "1",
        kind: "text",
        quote: "合成工程第一轮，合成投标人，技术总分 0 分，满分 100 分。",
        bbox: null,
        page_width: 600,
        page_height: 800,
        rotation: 0,
        source_status: "published",
      },
    ],
  };
  const verification: PackageOutcomeVerificationRequest = {
    version: "package-outcome-verification/1",
    subject_kind: "bid_package",
    state: "verified",
    reason: "逐项核对工程、轮次、投标主体和原页零分。",
    identity: context.identity,
    authority: context.authority,
    aggregation: "原件公示技术总分",
    published_at: "2025-06-02T09:00:00.123456+08:00",
    evidence_refs: [
      {
        document_version_id: sourceId,
        evidence_id: evidenceId,
        physical_page: 2,
        quote: evidence.items[0].quote,
      },
    ],
  };
  return {
    submission,
    scope,
    context,
    body,
    view,
    detail,
    page,
    evidence,
    verification,
  };
}
export type OutcomeFixture = Awaited<ReturnType<typeof outcomeFixture>>;
export async function outcomeVerificationAck(
  f: OutcomeFixture,
  body = f.verification,
  base = f.view,
): Promise<ResearchOutcomeView> {
  const authority = {
    version: "package-outcome-authority/1",
    authority: f.context.authority,
    binding_digest: f.scope.bindingDigest,
    documents: [],
    parses: [],
    sources: [],
  };
  const official = {
    schema: "official-source-authority/v2",
    root_id: id(510),
    heads: [{ document_version_id: base.source_version_id }],
    edges: [],
    evidence: await Promise.all(
      body.evidence_refs.map(async (ref) => ({
        id: ref.evidence_id,
        parse_id: f.evidence.parse_run_id,
        physical_page: ref.physical_page,
        digest: "e".repeat(64),
        quote_digest: Array.from(
          new Uint8Array(
            await crypto.subtle.digest(
              "SHA-256",
              new TextEncoder().encode(ref.quote),
            ),
          ),
          (b) => b.toString(16).padStart(2, "0"),
        ).join(""),
      })),
    ),
  };
  const details: PackageOutcomeVerificationDetails = {
    version: "package-outcome-verification-record/1",
    subject_kind: "bid_package",
    request: body,
    package_identity: f.context.package_identity,
    binding_digest: f.scope.bindingDigest,
    checked_at: "2025-06-03T00:00:00.123456Z",
    authority_proof:
      body.state === "verified"
        ? { digest: await jsonDigest(authority), snapshot: authority }
        : null,
    official_source_proof:
      body.state === "verified"
        ? { digest: await jsonDigest(official), snapshot: official }
        : null,
    verification_scope: "official_outcome_association",
    formal_sample_eligible: false,
    formal_sample_blockers: ["package_formal_sample_not_supported"],
  };
  return {
    ...base,
    verification: body.state,
    verification_revision: base.verification_revision + 1,
    verification_details: details,
  };
}
