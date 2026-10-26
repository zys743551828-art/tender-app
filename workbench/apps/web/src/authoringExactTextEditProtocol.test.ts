import { expect, it } from "vitest";
import { jsonDigest } from "./editorSchema";
import {
  readTextEditCapabilities,
  verifyTextEditACK,
  verifyTextEditBase,
  verifyTextEditPending,
} from "./authoringExactTextEditProtocol";
import native from "./test-fixtures/authoring-exact-text-edit-http.json";

export const nativeTextScope = {
  memberId: native.member_id,
  bidId: native.bid_id,
  draftId: native.parent_status.draft_id,
};
export const nativeTextBase = {
  status: native.parent_status,
  section: native.parent_section,
  qualification: native.parent_qualification,
};
export const nativeTextPending = {
  key: native.request_key,
  etag: native.request_etag,
  base: nativeTextBase,
  body: native.request,
};

it("verifies the unchanged native manual revision response and preserved root provenance", async () => {
  expect(native.fixture_kind).toContain("unchanged native PG17");
  expect(readTextEditCapabilities(native.capabilities).available).toBe(true);
  expect(await verifyTextEditBase(nativeTextBase, nativeTextScope)).toEqual(
    nativeTextBase,
  );
  const p = await verifyTextEditPending(nativeTextPending, nativeTextScope);
  expect(
    await verifyTextEditACK(native.ack, native.ack_etag, p, nativeTextScope),
  ).toEqual(native.ack);
  expect(native.ack.qualification.manifest.candidate_adopted).toBe(false);
});

it.each([
  "root",
  "actor",
  "body",
  "parent",
  "source",
  "candidate",
  "snapshot",
  "etag",
])(
  "rejects a %s substitution even after the attacker recomputes the qualification digest",
  async (kind) => {
    const p = await verifyTextEditPending(nativeTextPending, nativeTextScope);
    const value = structuredClone(native.ack);
    let etag = native.ack_etag;
    if (kind === "root")
      value.qualification.manifest.origin.root_qualification_id =
        crypto.randomUUID();
    if (kind === "actor")
      value.qualification.manifest.origin.actor_id = crypto.randomUUID();
    if (kind === "body")
      value.section_digest = value.qualification.manifest.section_digest =
        "0".repeat(64);
    if (kind === "parent")
      value.qualification.manifest.origin.parent_qualification_id =
        crypto.randomUUID();
    if (kind === "source")
      value.qualification.manifest.source_refs_digest = "0".repeat(64);
    if (kind === "candidate")
      value.qualification.manifest.candidate_adopted = true;
    if (kind === "snapshot") value.draft_revision += 1;
    if (kind === "etag") etag = '"draft:wrong:3"';
    value.qualification.digest = await jsonDigest(value.qualification.manifest);
    await expect(
      verifyTextEditACK(value, etag, p, nativeTextScope),
    ).rejects.toThrow();
  },
);

it("rejects mismatched section, qualification, scope and authority-bearing request fields", async () => {
  await expect(
    verifyTextEditBase(nativeTextBase, {
      ...nativeTextScope,
      bidId: crypto.randomUUID(),
    }),
  ).rejects.toThrow();
  const altered = structuredClone(nativeTextBase);
  altered.section.content.attrs.source_refs = [];
  await expect(verifyTextEditBase(altered, nativeTextScope)).rejects.toThrow();
  await expect(
    verifyTextEditPending(
      { ...nativeTextPending, body: { ...native.request, source_refs: [] } },
      nativeTextScope,
    ),
  ).rejects.toThrow();
});
