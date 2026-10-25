// Explicit synthetic state for exercising the actual draft workspace guard.
// The native adoption/qualification contract is tested separately without edits.
import {
  authoringLayoutFixture,
  layoutScope,
} from "./authoringLayoutFixtures.test-support";
import { exactAuthoringFixture } from "./authoringExactFixtures.test-support";
import { jsonDigest } from "./editorSchema";

export async function exactDraftLayoutFixture(buildAvailable = false) {
  const ordinary = authoringLayoutFixture(),
    source = await exactAuthoringFixture();
  const draft = ordinary.state.draft,
    section = ordinary.state.sections[0];
  draft.revision = 2;
  draft.sections[0].revision = 2;
  section.revision = 2;
  const binding = {
    ...source.binding,
    section_id: section.id,
    section_revision: section.revision,
    section_digest: await jsonDigest(section.content),
  };
  const extension = {
    protocol: "authoring-exact-snapshot/1" as const,
    sections: [binding],
  };
  const snapshot = {
    snapshot_id: draft.snapshot_id,
    snapshot_digest: "a".repeat(64),
    title: "合成固定整包正文",
    sections: ordinary.state.sections.map((item) => item.content),
    authoring_exact_sections: {
      ...extension,
      digest: await jsonDigest(extension),
    },
  };
  const status = {
    ...source.status,
    bid_id: layoutScope.bidId,
    draft_id: layoutScope.draftId,
    draft_revision: draft.revision,
    snapshot_id: draft.snapshot_id,
    snapshot_digest: snapshot.snapshot_digest,
    exact_sections: [binding],
    build_available: buildAvailable,
  };
  const reads: string[] = [];
  const fetcher: typeof fetch = async (input, options = {}) => {
    const path = new URL(
      typeof input === "string" || input instanceof URL ? input : input.url,
      window.location.href,
    ).pathname.replace(/^\/api\/v1/, "");
    reads.push(path);
    if (path === "/authoring/exact-text-edit-capabilities")
      return new Response(
        JSON.stringify({
          protocol: "authoring-exact-text-edit-capabilities/1",
          available: false,
          supported_content: "plain_text_stable_node",
          preserves_source_refs: true,
          preserves_rule_ids: true,
          ordinary_edit_available: false,
          blocking_reasons: ["AUTHORING_EXACT_TEXT_EDIT_NOT_CONFIGURED"],
        }),
        { headers: { "Content-Type": "application/json" } },
      );
    if (
      (!options.method || options.method === "GET") &&
      [
        `/bids/${layoutScope.bidId}/draft-snapshots/${draft.snapshot_id}`,
        `/bids/${layoutScope.bidId}/authoring/drafts/${draft.id}/exact-qualification`,
      ].includes(path)
    )
      return new Response(
        JSON.stringify(path.includes("/draft-snapshots/") ? snapshot : status),
        { headers: { "Content-Type": "application/json" } },
      );
    return ordinary.fetcher(input, options);
  };
  return { ...ordinary, fetcher, snapshot, status, reads };
}
