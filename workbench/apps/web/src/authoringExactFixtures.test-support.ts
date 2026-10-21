import { jsonDigest } from "./editorSchema";
import { packageAuthoringFixture } from "./packageAuthoringFixtures.test-support";
import { readPackageAuthoringProposal } from "./taskPackageAuthoringProtocol";
import { validateAuthoringInput } from "./packageAuthoringInputProtocol";
import type {
  AuthoringExactRevisionView,
  AuthoringExactSectionBinding,
  DraftSaved,
} from "./contracts";

export const exactId = (n: number) =>
  `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
export const actionEtag = async (value: { action_id: string }) =>
  `"assistant-action:${value.action_id}:${await jsonDigest(value)}"`;

/** Synthetic B3 responses for browser/protocol tests; they extend the separately
 * captured B2 fixture and are not represented as native database evidence. */
export async function exactAuthoringFixture() {
  const f = packageAuthoringFixture(),
    input = await validateAuthoringInput(f.input, f.bid.id);
  const action = readPackageAuthoringProposal(f.proposal, f.bid.id);
  action.preview.apply_available = true;
  const saved: DraftSaved = {
    draft_id: input.manifest.selection.target_section.draft_id,
    draft_revision: action.base_revision + 1,
    snapshot_id: exactId(9001),
    snapshot_digest: "b".repeat(64),
  };
  const executed = structuredClone(action);
  executed.state = "executed";
  executed.revision += 1;
  executed.resolved_by = f.member_id;
  executed.result = {
    assistant_resolution: {
      action_id: action.action_id,
      state: "executed",
      tool: "authoring.apply_patch",
      target_bid_id: f.bid.id,
      domain_result: saved,
      error_code: null,
      http_status: 200,
      business_effect_executed: true,
    },
  };
  const method = {
    protocol: "authoring-exact-adoption-policy/1" as const,
    supported_content: "plain_text_stable_node" as const,
    source_sha256: {
      "packages/authoring/package_proposals.py": "c".repeat(64),
    },
  };
  const manifest: AuthoringExactRevisionView["manifest"] = {
    protocol: "authoring-exact-revision/1",
    id: exactId(9002),
    bid_id: f.bid.id,
    draft_id: saved.draft_id,
    draft_revision: saved.draft_revision,
    section_id: action.preview.section_id,
    section_revision_id: exactId(9003),
    section_revision: action.preview.base_section_revision + 1,
    section_digest: await jsonDigest(action.preview.after),
    schema_digest: "d".repeat(64),
    parent_section_revision_id: exactId(9004),
    parent_section_revision: action.preview.base_section_revision,
    parent_section_digest: await jsonDigest(action.preview.before),
    input: {
      id: action.preview.authoring_input_id,
      digest: action.preview.authoring_input_digest,
      context_digest: input.manifest.context_digest,
    },
    origin: {
      kind: "model_candidate_adoption",
      job_id: action.job_id,
      job_input_digest: "e".repeat(64),
      action_id: action.action_id,
      action_digest: action.request_digest,
      candidate_digest: "f".repeat(64),
      command_id: exactId(9005),
      actor_id: f.member_id,
      before_action_digest: await jsonDigest(action),
    },
    source_scope: "exact_package_context",
    source_refs_digest: await jsonDigest(
      action.preview.after.attrs.source_refs,
    ),
    rule_ids_digest: await jsonDigest(action.preview.after.attrs.rule_ids),
    method,
    method_digest: await jsonDigest(method),
    candidate_adopted: true,
    content_correctness_certified: false,
  };
  const qualification: AuthoringExactRevisionView = {
    manifest,
    digest: await jsonDigest(manifest),
  };
  const binding: AuthoringExactSectionBinding = {
    section_id: manifest.section_id,
    section_revision_id: manifest.section_revision_id,
    section_revision: manifest.section_revision,
    section_digest: manifest.section_digest,
    qualification_id: manifest.id,
    qualification_digest: qualification.digest,
    authoring_input_id: manifest.input.id,
    authoring_input_digest: manifest.input.digest,
    source_scope: "exact_package_context",
  };
  const extension = {
    protocol: "authoring-exact-snapshot/1",
    sections: [binding],
  };
  const snapshot = {
    snapshot_id: saved.snapshot_id,
    snapshot_digest: saved.snapshot_digest,
    title: "合成采纳快照",
    sections: [action.preview.after],
    authoring_exact_sections: {
      ...extension,
      digest: await jsonDigest(extension),
    },
  };
  const status = {
    protocol: "authoring-exact-draft-status/1",
    bid_id: f.bid.id,
    draft_id: saved.draft_id,
    draft_revision: saved.draft_revision,
    snapshot_id: saved.snapshot_id,
    snapshot_digest: saved.snapshot_digest,
    exact_sections: [binding],
    ordinary_edit_available: false,
    build_available: true,
    blocking_reasons: [],
  };
  return {
    f,
    input,
    action,
    etag: await actionEtag(action),
    executed,
    executedEtag: await actionEtag(executed),
    saved,
    qualification,
    binding,
    snapshot,
    status,
    capabilities: {
      protocol: "authoring-exact-revision-capabilities/1",
      apply_available: true,
      build_available: true,
      ordinary_edit_available: false,
      supported_content: "plain_text_stable_node",
      blocking_reasons: [],
    },
  };
}
