import { expect, it } from "vitest";
import type { AuthoringDocument } from "./contracts";
import {
  editableMarkedTextNodes,
  replaceMarkedText,
  validMarkedReplacement,
  readMarkedTextEditCapabilities,
} from "./authoringExactMarkedTextEditProtocol";
import { editableTextNodes } from "./authoringExactTextEditProtocol";
import native from "./test-fixtures/authoring-exact-text-edit-http.json";

function fixture() {
  const doc = structuredClone(
    native.parent_section.content,
  ) as AuthoringDocument;
  const node = editableTextNodes(doc)[0].node;
  if (!("content" in node)) throw new Error("fixture");
  node.content = [
    {
      type: "text",
      text: "合成格式文字",
      marks: [{ type: "italic" }, { type: "bold" }],
    },
  ];
  return { doc, node, id: "attrs" in node ? node.attrs.id : "" };
}
it("only offers a single legal marked leaf, leaving old plain eligibility strict", () => {
  const { doc, id } = fixture();
  expect(editableMarkedTextNodes(doc).map((n) => n.id)).toEqual([id]);
  expect(editableTextNodes(doc).some((n) => n.id === id)).toBe(false);
});
it("deep copies only text and retains mark order, sources, rules and all surrounding content", () => {
  const { doc, id } = fixture();
  const before = structuredClone(doc);
  const updated = replaceMarkedText(doc, id, "新的格式文字");
  const target = editableMarkedTextNodes(updated)[0].node;
  expect(doc).toEqual(before);
  if (!("content" in target) || target.content[0].type !== "text")
    throw new Error("fixture");
  expect(target.content[0].marks).toEqual([
    { type: "italic" },
    { type: "bold" },
  ]);
  target.content[0].text = "合成格式文字";
  expect(updated).toEqual(before);
});
it.each(["", " ", "\n", "a\nb", "a\tb", "a\u0000b", "a\u007fb"])(
  "rejects empty/control replacement %j",
  (text) => {
    expect(validMarkedReplacement(text)).toBe(false);
    const { doc, id } = fixture();
    expect(() => replaceMarkedText(doc, id, text)).toThrow();
  },
);
it.each(["plain", "duplicate", "mixed", "break", "attrs", "unknown"])(
  "rejects unsupported %s target without normalizing",
  (kind) => {
    const { doc, node, id } = fixture();
    if (
      (node.type !== "paragraph" && node.type !== "heading") ||
      node.content[0].type !== "text"
    )
      throw new Error("fixture");
    const leaf = node.content[0];
    if (kind === "plain") delete leaf.marks;
    if (kind === "duplicate") leaf.marks = [{ type: "bold" }, { type: "bold" }];
    if (kind === "mixed") node.content.push({ type: "text", text: "run" });
    if (kind === "break") node.content.push({ type: "hardBreak" });
    if (kind === "attrs") Object.assign(leaf.marks![0], { attrs: {} });
    if (kind === "unknown")
      Object.assign(leaf.marks![0], { type: "underline" });
    expect(editableMarkedTextNodes(doc)).toEqual([]);
    expect(() => replaceMarkedText(doc, id, "new")).toThrow();
  },
);
it("requires explicit available installed preserving capability", () => {
  const caps = {
    protocol: "authoring-exact-text-edit-capabilities/3",
    available: true,
    supported_content: "single_marked_text_leaf_preserve_marks",
    preserves_source_refs: true,
    preserves_rule_ids: true,
    preserves_marks: true,
    ordinary_edit_available: false,
    blocking_reasons: [],
  };
  expect(readMarkedTextEditCapabilities(caps).available).toBe(true);
  for (const changed of [
    { preserves_marks: false },
    { protocol: "authoring-exact-text-edit-capabilities/2" },
    { blocking_reasons: ["not installed"] },
    { ordinary_edit_available: true },
    { extra: true },
  ])
    expect(() =>
      readMarkedTextEditCapabilities({ ...caps, ...changed }),
    ).toThrow();
});

it("verifies a synthetic /3 ACK and preserves /3 as a later qualification parent", async () => {
  const { syntheticMarkedTextEdit } = await import(
    "./authoringMarkedTextEdit.test-support"
  );
  const { verifyTextEditACK, verifyTextEditBase } = await import(
    "./authoringExactTextEditProtocol"
  );
  const f = await syntheticMarkedTextEdit();
  expect(await verifyTextEditACK(f.ack, f.etag, f.pending, f.scope)).toEqual(
    f.ack,
  );
  const next = structuredClone(f.pending.base);
  Object.assign(next.section, {
    content: f.after,
    revision: next.section.revision + 1,
  });
  Object.assign(next.status, {
    draft_revision: f.ack.draft_revision,
    snapshot_id: f.ack.snapshot_id,
    snapshot_digest: f.ack.snapshot_digest,
  });
  Object.assign(next.status.exact_sections[0], {
    section_revision_id: f.ack.section_revision_id,
    section_revision: next.section.revision,
    section_digest: f.ack.section_digest,
    qualification_id: f.ack.qualification.manifest.id,
    qualification_digest: f.ack.qualification.digest,
  });
  expect(
    await verifyTextEditBase(
      { ...next, qualification: f.ack.qualification },
      f.scope,
    ),
  ).toBeTruthy();
});
it.each(["marks", "protocol", "root", "text", "source"])(
  "rejects a rehashed synthetic /3 %s ACK substitution",
  async (kind) => {
    const { syntheticMarkedTextEdit } = await import(
      "./authoringMarkedTextEdit.test-support"
    );
    const { verifyTextEditACK } = await import(
      "./authoringExactTextEditProtocol"
    );
    const { jsonDigest } = await import("./editorSchema");
    const f = await syntheticMarkedTextEdit();
    const m = f.ack.qualification.manifest;
    if (kind === "marks") m.origin.preserved_marks_digest = "0".repeat(64);
    if (kind === "protocol")
      f.ack.protocol = "authoring-exact-text-edit-result/1";
    if (kind === "root") m.origin.root_qualification_id = crypto.randomUUID();
    if (kind === "text")
      m.section_digest = f.ack.section_digest = "0".repeat(64);
    if (kind === "source") m.source_refs_digest = "0".repeat(64);
    f.ack.qualification.digest = await jsonDigest(m);
    await expect(
      verifyTextEditACK(f.ack, f.etag, f.pending, f.scope),
    ).rejects.toThrow();
  },
);
it("does not allow marked requests to supply marks or downgrade to a plain request", async () => {
  const { syntheticMarkedTextEdit } = await import(
    "./authoringMarkedTextEdit.test-support"
  );
  const { verifyTextEditPending } = await import(
    "./authoringExactTextEditProtocol"
  );
  const f = await syntheticMarkedTextEdit();
  await expect(
    verifyTextEditPending(
      { ...f.pending, body: { ...f.pending.body, marks: [] } },
      f.scope,
    ),
  ).rejects.toThrow();
  await expect(
    verifyTextEditPending(
      { ...f.pending, body: { ...f.pending.body, protocol: undefined } },
      f.scope,
    ),
  ).rejects.toThrow();
});

it("accepts the unchanged native non-owner PG17/API marked ACK and base proof", async () => {
  const { default: native } = await import(
    "./test-fixtures/authoring-exact-marked-text-edit-http.json"
  );
  const { verifyTextEditPending, verifyTextEditACK } = await import(
    "./authoringExactTextEditProtocol"
  );
  const scope = {
    memberId: native.member_id,
    bidId: native.bid_id,
    draftId: native.parent_status.draft_id,
  };
  const pending = await verifyTextEditPending(
    {
      key: native.request_key,
      etag: native.request_etag,
      body: native.request,
      base: {
        status: native.parent_status,
        section: native.parent_section,
        qualification: native.parent_qualification,
      },
    },
    scope,
  );
  expect(readMarkedTextEditCapabilities(native.capabilities).available).toBe(
    true,
  );
  expect(
    await verifyTextEditACK(native.ack, native.ack_etag, pending, scope),
  ).toEqual(native.ack);
});

it.each(["\u00a0", "\u202f", "\u0085", "\ufeff", " \ufeff \u0085\u202f"])(
  "rejects cross-language blank %j",
  (text) => {
    expect(validMarkedReplacement(text)).toBe(false);
  },
);
it("does not normalize mixed visible text with Unicode whitespace", () => {
  const { doc, id } = fixture();
  const text = " \ufeffWord\u0085\u202f";
  expect(validMarkedReplacement(text)).toBe(true);
  expect(
    editableMarkedTextNodes(replaceMarkedText(doc, id, text))[0].text,
  ).toBe(text);
});

it("supports heading leaves but rejects ambiguous duplicate target IDs", () => {
  const { doc, node, id } = fixture();
  if (node.type !== "paragraph" && node.type !== "heading")
    throw new Error("fixture");
  Object.assign(node, { type: "heading", attrs: { id, level: 2 } });
  expect(editableMarkedTextNodes(doc).map((n) => n.id)).toEqual([id]);
  expect(
    editableMarkedTextNodes(replaceMarkedText(doc, id, "Heading changed"))[0]
      .text,
  ).toBe("Heading changed");
  doc.content.push(structuredClone(node));
  expect(() => replaceMarkedText(doc, id, "Ambiguous change")).toThrow();
});

it.each(["\u00a0", "\u0085", "\u202f", "\ufeff", " \ufeff\u0085"])(
  "rejects marked blank reason %j without changing old plain behavior",
  async (reason) => {
    const { syntheticMarkedTextEdit } = await import(
      "./authoringMarkedTextEdit.test-support"
    );
    const { verifyTextEditPending } = await import(
      "./authoringExactTextEditProtocol"
    );
    const f = await syntheticMarkedTextEdit();
    await expect(
      verifyTextEditPending(
        { ...f.pending, body: { ...f.pending.body, reason } },
        f.scope,
      ),
    ).rejects.toThrow();
  },
);
it("retains mixed marked reasons including permitted newline and tab without trimming", async () => {
  const { syntheticMarkedTextEdit } = await import(
    "./authoringMarkedTextEdit.test-support"
  );
  const { verifyTextEditPending } = await import(
    "./authoringExactTextEditProtocol"
  );
  const f = await syntheticMarkedTextEdit();
  const reason = " \ufeffReason\u0085\n\t";
  const p = await verifyTextEditPending(
    { ...f.pending, body: { ...f.pending.body, reason } },
    f.scope,
  );
  expect(p.body.reason).toBe(reason);
});

it.each(["word\u007f", "word\u0000", "word\r"])(
  "rejects marked reason control %j",
  async (reason) => {
    const { syntheticMarkedTextEdit } = await import(
      "./authoringMarkedTextEdit.test-support"
    );
    const { verifyTextEditPending } = await import(
      "./authoringExactTextEditProtocol"
    );
    const f = await syntheticMarkedTextEdit();
    await expect(
      verifyTextEditPending(
        { ...f.pending, body: { ...f.pending.body, reason } },
        f.scope,
      ),
    ).rejects.toThrow();
  },
);
