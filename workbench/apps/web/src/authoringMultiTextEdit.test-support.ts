/** Synthetic multi-node protocol fixture, NOT a native database acknowledgement. */
import native from "./test-fixtures/authoring-exact-text-edit-http.json";
import { jsonDigest } from "./editorSchema";
import { verifyTextEditPending } from "./authoringExactTextEditProtocol";
export async function syntheticMultiTextEdit() {
  const scope = {
    memberId: native.member_id,
    bidId: native.bid_id,
    draftId: native.parent_status.draft_id,
  };
  const base = structuredClone({
    status: native.parent_status,
    section: native.parent_section,
    qualification: native.parent_qualification,
  });
  const second = structuredClone(base.section.content.content[0]);
  second.attrs.id = "11111111-1111-4111-8111-111111111111";
  second.content = [{ type: "text", text: "Synthetic second paragraph" }];
  base.section.content.content.push(second);
  base.qualification.manifest.section_digest = await jsonDigest(
    base.section.content,
  );
  base.qualification.digest = await jsonDigest(base.qualification.manifest);
  base.status.exact_sections[0].section_digest =
    base.qualification.manifest.section_digest;
  base.status.exact_sections[0].qualification_digest =
    base.qualification.digest;
  const edits = await Promise.all(
    base.section.content.content.map(async (node, i) => ({
      node_id: node.attrs.id,
      before_node_digest: await jsonDigest(node),
      replacement_text: `Synthetic change ${i}`,
    })),
  );
  const body = {
    protocol: "authoring-exact-multi-text-edit/1",
    base_draft_revision: base.status.draft_revision,
    section_revision_id: base.qualification.manifest.section_revision_id,
    edits,
    reason: "Synthetic batch wording correction",
  };
  const pending = await verifyTextEditPending(
    { key: native.request_key, etag: native.request_etag, base, body },
    scope,
  );
  const after = structuredClone(base.section.content);
  after.content.forEach((node, i) => {
    node.content = [{ type: "text", text: edits[i].replacement_text }];
  });
  const sectionDigest = await jsonDigest(after);
  const hashes = await Promise.all(
    edits.map(async (edit) => {
      const bytes = new Uint8Array(
        await crypto.subtle.digest(
          "SHA-256",
          new TextEncoder().encode(edit.replacement_text),
        ),
      );
      return {
        node_id: edit.node_id,
        before_node_digest: edit.before_node_digest,
        replacement_text_digest: [...bytes]
          .map((x) => x.toString(16).padStart(2, "0"))
          .join(""),
      };
    }),
  );
  const old = native.ack.qualification.manifest;
  const method = {
    ...old.method,
    protocol: "authoring-exact-text-edit-policy/2",
    supported_content: "plain_text_stable_nodes",
  };
  const { node_id, before_node_digest, replacement_text_digest, ...origin } =
    old.origin;
  void node_id;
  void before_node_digest;
  void replacement_text_digest;
  const manifest = {
    ...old,
    protocol: "authoring-exact-manual-revision/2",
    section_digest: sectionDigest,
    parent_section_digest: base.qualification.manifest.section_digest,
    method,
    method_digest: await jsonDigest(method),
    origin: {
      ...origin,
      kind: "manual_multi_text_edit",
      edits: hashes,
      reason: body.reason,
      parent_qualification_digest: base.qualification.digest,
      root_qualification_digest: base.qualification.digest,
      before_action_digest: await jsonDigest({
        request: body,
        base_snapshot_id: base.status.snapshot_id,
        base_snapshot_digest: base.status.snapshot_digest,
      }),
    },
  };
  const ack = {
    ...native.ack,
    protocol: "authoring-exact-text-edit-result/2",
    section_digest: sectionDigest,
    qualification: { manifest, digest: await jsonDigest(manifest) },
  };
  return {
    scope,
    pending,
    ack,
    etag: native.ack_etag,
    capabilities: {
      ...native.capabilities,
      protocol: "authoring-exact-text-edit-capabilities/2",
      supported_content: "plain_text_stable_nodes",
    },
  };
}
