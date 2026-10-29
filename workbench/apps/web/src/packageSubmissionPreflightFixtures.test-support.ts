// Synthetic client mechanism only. Native PG and actual byte checks have separate receipts.
import type { PackageSubmissionPreflightView } from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  submissionFixture,
  submissionId as id,
  submissionScope,
} from "./packageSubmissionFixtures.test-support";

export async function submissionPreflightFixture(withReview = true) {
  const source = await submissionFixture(true);
  const preview = structuredClone(source.preview);
  if (withReview) {
    preview.selection_request.review_run = {
      id: id(450),
      input_digest: "a".repeat(64),
      result_digest: "b".repeat(64),
    };
    preview.gate.manifest.selection.run_id = id(450);
    preview.gate.manifest.selection.result_digest = "b".repeat(64);
    preview.gate.manifest.gates.current_input.codes.push(
      "REVIEW_RUNTIME_DEPENDENCIES_NOT_CHECKED",
    );
  }
  preview.gate.digest = await jsonDigest(preview.gate.manifest);
  const originals: PackageSubmissionPreflightView["manifest"]["originals"] = [];
  for (const role of ["target", "authority"] as const) {
    for (const member of preview.selection[role]?.manifest.members ?? []) {
      const old = originals.find(
        (row) => row.document_version_id === member.document_version_id,
      );
      if (old) old.roles.push(role);
      else
        originals.push({
          document_version_id: member.document_version_id,
          digest: member.file_digest,
          byte_size: 42,
          media_type: "application/pdf",
          artifact_kind: "source_original",
          original_name: `synthetic-${role}.pdf`,
          roles: [role],
        });
    }
  }
  const metadata = preview.gate.manifest.gates.current_input;
  const manifest: PackageSubmissionPreflightView["manifest"] = {
    version: "package-submission-preflight/1",
    kind: "verified_package_submission_observation",
    subject: structuredClone(preview.gate.manifest.subject),
    selection_request: structuredClone(preview.selection_request),
    selection_digest: await jsonDigest(preview.selection),
    input_digest: preview.input_digest,
    actor_id: submissionScope.memberId,
    checked_at: "2026-10-26T03:00:00.123456Z",
    bid_etag: preview.bid_etag,
    policy_digest: "c".repeat(64),
    metadata_gate_digest: "d".repeat(64),
    review_runtime: withReview
      ? {
          state: "matched",
          run_id: id(450),
          selected_input_digest: "a".repeat(64),
          current_input_digest: "a".repeat(64),
          codes: [],
        }
      : {
          state: "not_selected",
          run_id: null,
          selected_input_digest: null,
          current_input_digest: null,
          codes: ["PACKAGE_REVIEW_NOT_SELECTED"],
        },
    originals,
    gates: {
      ...structuredClone(preview.gate.manifest.gates),
      current_input: {
        state: withReview ? "pass" : "unknown",
        codes: withReview ? [] : ["PACKAGE_REVIEW_NOT_SELECTED"],
        scope: "current_input_verified_observation",
        metadata_observations_digest: metadata.observations_digest,
        current_identity_digest: metadata.current_identity_digest,
        original_verification: "verified_at_observation",
        original_count: originals.length,
        originals_digest: await jsonDigest(originals),
        physical_page_gaps: metadata.physical_page_gaps,
      },
    },
    state: "unknown",
    allowed: false,
    inventory_complete: false,
    quality_status: "not_measured",
    submission_eligible: false,
    publication_authorized: false,
    platform_submission_verified: false,
    limitations: [
      "INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED",
      "PACKAGE_REVIEW_QUALITY_NOT_MEASURED",
      "HUMAN_OPINION_IS_NOT_RECHECK_RESOLUTION",
      "ORIGINAL_BYTES_VERIFIED_AT_OBSERVATION_ONLY",
      "ORIGINAL_BYTES_NOT_ATOMIC_WITH_DATABASE",
      "PREFLIGHT_IS_NOT_SUBMISSION_AUTHORIZATION",
    ],
  };
  return { preview, result: { manifest, digest: await jsonDigest(manifest) } };
}
