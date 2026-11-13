/** Synthetic B7 protocol fixture. NOT a native database ACK or real DOCX. */
import native from "./test-fixtures/authoring-exact-text-edit-http.json";
import { jsonDigest } from "./editorSchema";
import { verifyTextEditPending } from "./authoringExactTextEditProtocol";
export async function syntheticMarkedTextEdit() {
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
  const node = base.section.content.content[0];
  const marks = [{ type: "italic" }, { type: "bold" }];
  node.content = [
    Object.assign(
      { type: "text", text: "Synthetic marked original" },
      { marks },
    ),
  ];
  base.qualification.manifest.section_digest = await jsonDigest(
    base.section.content,
  );
  base.qualification.digest = await jsonDigest(base.qualification.manifest);
  Object.assign(base.status.exact_sections[0], {
    section_digest: base.qualification.manifest.section_digest,
    qualification_digest: base.qualification.digest,
  });
  const body = {
    ...native.request,
    protocol: "authoring-exact-marked-text-edit/1",
    before_node_digest: await jsonDigest(node),
  };
  const pending = await verifyTextEditPending(
    { key: native.request_key, etag: native.request_etag, base, body },
    scope,
  );
  const after = structuredClone(base.section.content);
  after.content[0].content[0].text = body.replacement_text;
  const sectionDigest = await jsonDigest(after);
  const old = native.ack.qualification.manifest;
  const method = {
    ...old.method,
    protocol: "authoring-exact-text-edit-policy/3",
    supported_content: "single_marked_text_leaf_preserve_marks",
  };
  const manifest = {
    ...old,
    protocol: "authoring-exact-manual-revision/3",
    section_digest: sectionDigest,
    parent_section_digest: base.qualification.manifest.section_digest,
    method,
    method_digest: await jsonDigest(method),
    origin: {
      ...old.origin,
      kind: "manual_marked_text_edit",
      before_node_digest: body.before_node_digest,
      preserved_marks_digest: await jsonDigest(marks),
      parent_qualification_digest: base.qualification.digest,
      root_qualification_digest: base.qualification.digest,
      before_action_digest: await jsonDigest({
        request: body,
        base_snapshot_id: base.status.snapshot_id,
        base_snapshot_digest: base.status.snapshot_digest,
      }),
    },
  };
  return {
    scope,
    pending,
    after,
    etag: native.ack_etag,
    ack: {
      ...native.ack,
      protocol: "authoring-exact-text-edit-result/3",
      section_digest: sectionDigest,
      qualification: { manifest, digest: await jsonDigest(manifest) },
    },
    capabilities: {
      ...native.capabilities,
      protocol: "authoring-exact-text-edit-capabilities/3",
      supported_content: "single_marked_text_leaf_preserve_marks",
      preserves_marks: true,
    },
  };
}
