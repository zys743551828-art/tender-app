import { expect, it } from "vitest";
import { jsonDigest } from "./editorSchema";
import {
  verifyTextEditACK,
  verifyTextEditPending,
  readTextEditCapabilities,
} from "./authoringExactTextEditProtocol";
import { syntheticMultiTextEdit } from "./authoringMultiTextEdit.test-support";
it("validates a synthetic multi-node request and receipt retaining the source chain", async () => {
  const f = await syntheticMultiTextEdit();
  expect(readTextEditCapabilities(f.capabilities).supported_content).toBe(
    "plain_text_stable_nodes",
  );
  expect(await verifyTextEditACK(f.ack, f.etag, f.pending, f.scope)).toEqual(
    f.ack,
  );
});
it.each([
  "duplicate",
  "missing",
  "digest",
  "extra",
  "nochange",
  "too-long",
  "one",
  "unknown-version",
])("rejects %s before sending any multi-node change", async (kind) => {
  const f = await syntheticMultiTextEdit();
  const p = structuredClone(f.pending);
  if (!("edits" in p.body)) throw Error("expected batch");
  const edits = p.body.edits;
  if (kind === "duplicate") edits[1] = edits[0];
  if (kind === "missing") edits[1].node_id = "absent";
  if (kind === "digest") edits[1].before_node_digest = "0".repeat(64);
  if (kind === "extra") Object.assign(edits[1], { source_refs: [] });
  if (kind === "nochange")
    edits[1].replacement_text = "Synthetic second paragraph";
  if (kind === "too-long") edits[1].replacement_text = "界".repeat(20000);
  if (kind === "one") edits.pop();
  if (kind === "unknown-version")
    Object.assign(p.body, { protocol: "unknown" });
  await expect(verifyTextEditPending(p, f.scope)).rejects.toThrow();
});
it.each(["omit", "reorder", "text", "actor", "source", "version"])(
  "rejects a re-signed %s batch receipt",
  async (kind) => {
    const f = await syntheticMultiTextEdit();
    const ack = structuredClone(f.ack);
    if (kind === "omit") ack.qualification.manifest.origin.edits.pop();
    if (kind === "reorder") ack.qualification.manifest.origin.edits.reverse();
    if (kind === "text")
      ack.qualification.manifest.origin.edits[1].replacement_text_digest =
        "0".repeat(64);
    if (kind === "actor")
      ack.qualification.manifest.origin.actor_id = crypto.randomUUID();
    if (kind === "source")
      ack.qualification.manifest.source_refs_digest = "0".repeat(64);
    if (kind === "version") ack.protocol = "authoring-exact-text-edit-result/1";
    ack.qualification.digest = await jsonDigest(ack.qualification.manifest);
    await expect(
      verifyTextEditACK(ack, f.etag, f.pending, f.scope),
    ).rejects.toThrow();
  },
);
