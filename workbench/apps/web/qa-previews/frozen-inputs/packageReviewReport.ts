// Deliberately synthetic report bytes. These fixtures exercise binding and recovery, not rendering quality.
import type {
  DocumentView,
  DownloadGrant,
  Operation,
  PackageReviewReportContext,
  PackageReviewReportPage,
  PackageReviewReportView,
} from "../../src/contracts";
import { frozenManifestDigest } from "../../src/packageFrozenInput";
import { packageReviewFixture, packageReviewEvidence } from "./packageReview";
import { packageReviewDecisionCurrent } from "./packageReviewDecision";
import { changeId as id } from "./factChange";
import { packageReviewReportMedia } from "../../src/packageReviewReportProtocol";

export async function packageReviewReportFixture(
  format: "docx" | "pdf" = "docx",
) {
  const f = await packageReviewFixture(),
    run = f.completed;
  const binding = {
    scope: run.scope,
    frozen_input_id: run.frozen_input_id,
    execution_input_id: run.execution_input_id,
    run_id: run.id,
    input_digest: run.input_digest,
    result_digest: run.result!.digest,
  };
  const human = await packageReviewDecisionCurrent(f),
    method = {
      version: "package-review-report/1",
      writer_digest: "a".repeat(64),
      reporter_digest: "b".repeat(64),
      pdf_renderer:
        format === "pdf"
          ? {
              renderer_digest: "c".repeat(64),
              renderer_version: "synthetic renderer",
              fontset_digest: "d".repeat(64),
              options_digest: "e".repeat(64),
            }
          : null,
    };
  const contextValue = {
    ...binding,
    human_decisions: human,
    method,
    formal_scoring_eligible: false,
    submission_eligible: false,
  };
  const context: PackageReviewReportContext = {
    ...binding,
    human_decisions_digest: await frozenManifestDigest(human),
    method_digest: await frozenManifestDigest(method),
    context_digest: await frozenManifestDigest(contextValue),
    formats: format === "pdf" ? ["docx", "pdf"] : ["docx"],
    pdf_unavailable_code: format === "pdf" ? null : "RENDERER_UNAVAILABLE",
    formal_scoring_eligible: false,
    submission_eligible: false,
  };
  const body = { context_digest: context.context_digest, format };
  const reportInput = {
      version: "package-review-report-input/1",
      context: contextValue,
      ...body,
      artifact_kind: "review_report",
      formal_scoring_eligible: false,
      submission_eligible: false,
    },
    inputDigest = await frozenManifestDigest(reportInput);
  const report: PackageReviewReportView = {
    ...binding,
    id: id(310),
    actor_id: f.props.scope.memberId,
    created_at: "2026-10-21T10:00:00.000000Z",
    context_digest: context.context_digest,
    report_input_digest: inputDigest,
    format,
    artifact_kind: "review_report",
    operation: {
      id: id(311),
      kind: "package-scope-report",
      state: "queued",
      input_digest: inputDigest,
      handler_version: "package-report/1",
      error_code: null,
      created_at: "2026-10-21T10:00:00.000000Z",
      finished_at: null,
    },
    result: null,
    formal_scoring_eligible: false,
    submission_eligible: false,
  };
  const bytes = new TextEncoder().encode(
    `Explicitly synthetic ${format} report bytes: fixed machine result and human head snapshot.`,
  );
  const blobDigest = Array.from(
    new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("");
  const completed: PackageReviewReportView = {
    ...report,
    operation: {
      ...report.operation,
      state: "succeeded",
      finished_at: "2026-10-21T10:00:03.000000Z",
    },
    result: {
      document_version_id: id(312),
      blob_digest: blobDigest,
      byte_size: bytes.byteLength,
      media_type: packageReviewReportMedia[format],
      filename: `合成范围核查报告.${format}`,
      gaps: [],
    },
  };
  const document: DocumentView = {
    ...packageReviewEvidence(f).document,
    id: id(312),
    role: "other",
    artifact_kind: "review_report",
    filename: completed.result!.filename,
    sha256: blobDigest,
    byte_size: bytes.byteLength,
    media_type: packageReviewReportMedia[format],
    file_id: id(313),
    file_head_version_id: id(312),
  };
  const grant: DownloadGrant = {
    artifact_id: id(312),
    artifact_kind: "review_report",
    presentation_revision: null,
    download_url: "https://synthetic-objects.invalid/package-report",
    filename: document.filename,
    expires_at: "2026-10-21T10:20:00.000000Z",
  };
  const page = (
    items: PackageReviewReportView[] = [completed],
  ): PackageReviewReportPage => ({
    ...binding,
    items,
    has_more: false,
    next_cursor: null,
  });
  return { f, context, body, report, completed, bytes, document, grant, page };
}
export function packageReportOperation(
  report: PackageReviewReportView,
): Operation {
  return {
    id: report.operation.id,
    bid_id: report.scope.bid_id,
    kind: "package-scope-report",
    state: report.operation.state,
    input_digest: report.report_input_digest,
    handler_version: "package-report/1",
    result_ref: null,
  };
}
