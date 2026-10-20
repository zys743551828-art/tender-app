import type {
  PackageExecutionInputView,
  PackageReviewFrozenInputView,
} from "../../src/contracts";
import { frozenManifestDigest } from "../../src/packageFrozenInput";
export async function prepared(
  frozen: PackageReviewFrozenInputView,
  id: string,
): Promise<PackageExecutionInputView> {
  const f = frozen.manifest;
  const execution_context = {
    ...f.execution_context,
    as_of: "2026-10-19T08:03:00Z",
    snapshot_digest: "8".repeat(64),
  };
  const binding = {
    bid_id: f.bid_id,
    package_id: f.package_id,
    revision_id: f.revision_id,
    inventory_id: f.inventory_id,
    identity_digest: "9".repeat(64),
    frozen_input_id: f.id,
    frozen_digest: frozen.digest,
    input_digest: f.input_digest,
    evidence_digest: f.evidence_digest,
    context_digest: execution_context.semantic_digest,
    method_digest: execution_context.method_digest,
    policy_digest: execution_context.policy_digest,
    purpose: "prebid_compliance" as const,
  };
  const content_digest = await frozenManifestDigest({
    version: "package-review-content/1",
    binding,
  });
  const identity = {
    version: "package-review-execution/1" as const,
    kind: "identity" as const,
    binding,
    rerun: null,
    content_digest,
    execution_digest: await frozenManifestDigest({
      version: "package-review-execution/1",
      content_digest,
      rerun: null,
    }),
  };
  const manifest: PackageExecutionInputView["manifest"] = {
    version: "package-review-execution-input/1",
    kind: "prepared_input",
    id,
    bid_id: f.bid_id,
    package_id: f.package_id,
    revision_id: f.revision_id,
    inventory_id: f.inventory_id,
    frozen_input_id: f.id,
    actor_id: f.actor_id,
    command_id: f.command_id,
    identity,
    execution_context,
    snapshot_digest: "6".repeat(64),
    originals_verified_at: execution_context.as_of,
    saved_at: "2026-10-19T08:03:01Z",
    blockers: [
      "PACKAGE_REVIEW_EXECUTOR_NOT_READY",
      "PACKAGE_REVIEW_FACTS_UNPROVEN",
    ],
    review_ready: false,
    launch_available: false,
    publication_authorized: false,
  };
  return { manifest, digest: await frozenManifestDigest(manifest) };
}
