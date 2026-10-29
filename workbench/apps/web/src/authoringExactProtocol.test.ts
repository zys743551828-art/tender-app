import { expect, it } from "vitest";
import {
  exactAuthoringFixture,
  exactId,
  actionEtag,
} from "./authoringExactFixtures.test-support";
import {
  exactActionSaved,
  exactAdoptionBinding,
  readExactDraftStatus,
  verifyExactAction,
  verifyExactActionACK,
  verifyExactQualification,
  verifyExactCandidateInput,
} from "./authoringExactProtocol";
import { jsonDigest } from "./editorSchema";
import native from "./test-fixtures/authoring-exact-adoption-http.json";
import { readExactCapabilities } from "./authoringExactProtocol";
import {
  validateAuthoringInput,
  validateAuthoringPublicContext,
} from "./packageAuthoringInputProtocol";

it("accepts unchanged native B3 HTTP responses through the complete action, snapshot and qualification chain", async () => {
  expect(native.fixture_kind).toContain("unchanged native PG17/S3/API");
  expect(readExactCapabilities(native.capabilities).apply_available).toBe(true);
  const before = await verifyExactAction(
    native.before_action,
    native.before_etag,
    native.before_action.action_id,
    native.bid_id,
  );
  const input = await validateAuthoringInput(native.input, native.bid_id);
  expect(await verifyExactCandidateInput(input, before)).toEqual(input);
  expect(validateAuthoringPublicContext(native.context, input)).toEqual(
    native.context,
  );
  const adopted = await verifyExactActionACK(
    native.resolve_ack,
    native.resolve_etag,
    before,
  );
  const saved = exactActionSaved(adopted)!;
  expect(await verifyExactCandidateInput(input, adopted)).toEqual(input);
  expect(saved).toBeTruthy();
  const binding = await exactAdoptionBinding(native.snapshot, adopted, saved);
  expect(
    await verifyExactQualification(
      native.qualification,
      binding,
      adopted,
      saved,
    ),
  ).toEqual(native.qualification);
  expect(
    readExactDraftStatus(native.draft_status, native.bid_id, saved.draft_id),
  ).toEqual(native.draft_status);
});

it("binds the confirmed action, saved snapshot, adopted section and original exact input", async () => {
  const f = await exactAuthoringFixture();
  expect(await verifyExactAction(f.action, f.etag, f.action.action_id)).toEqual(
    f.action,
  );
  expect(
    await verifyExactActionACK(f.executed, f.executedEtag, f.action),
  ).toEqual(f.executed);
  expect(exactActionSaved(f.executed)).toEqual(f.saved);
  expect(await exactAdoptionBinding(f.snapshot, f.executed, f.saved)).toEqual(
    f.binding,
  );
  expect(
    await verifyExactQualification(
      f.qualification,
      f.binding,
      f.executed,
      f.saved,
    ),
  ).toEqual(f.qualification);
  expect(readExactDraftStatus(f.status, f.f.bid.id, f.saved.draft_id)).toEqual(
    f.status,
  );
});
it.each(["action", "job", "input", "content", "revision", "effect", "etag"])(
  "rejects an incorrect %s adoption acknowledgement",
  async (field) => {
    const f = await exactAuthoringFixture(),
      v = structuredClone(f.executed);
    if (field === "action") v.action_id = exactId(99);
    if (field === "job") v.job_id = exactId(99);
    if (field === "input") v.preview.authoring_input_id = exactId(99);
    if (field === "content") v.preview.after = v.preview.before;
    if (field === "revision") v.revision = f.action.revision;
    if (field === "effect" && v.result && "assistant_resolution" in v.result)
      v.result.assistant_resolution.business_effect_executed = false;
    await expect(
      verifyExactActionACK(
        v,
        field === "etag" ? f.etag : await actionEtag(v),
        f.action,
      ),
    ).rejects.toThrow();
  },
);
it("does not substitute a newer saved snapshot or a foreign qualification even with recomputed digests", async () => {
  const f = await exactAuthoringFixture();
  await expect(
    exactAdoptionBinding(
      { ...f.snapshot, snapshot_id: exactId(99) },
      f.executed,
      f.saved,
    ),
  ).rejects.toThrow();
  const q = structuredClone(f.qualification);
  q.manifest.origin.action_id = exactId(99);
  q.digest = await jsonDigest(q.manifest);
  const binding = { ...f.binding, qualification_digest: q.digest };
  await expect(
    verifyExactQualification(q, binding, f.executed, f.saved),
  ).rejects.toThrow();
});
it("retains a different member's globally consumed result instead of claiming our decision won", async () => {
  const f = await exactAuthoringFixture(),
    rejected = structuredClone(f.executed);
  rejected.state = "rejected";
  rejected.resolved_by = exactId(99);
  rejected.result = {
    assistant_resolution: {
      action_id: rejected.action_id,
      state: "rejected",
      tool: "authoring.apply_patch",
      target_bid_id: rejected.target_bid_id,
      domain_result: null,
      error_code: null,
      http_status: 200,
      business_effect_executed: false,
    },
  };
  expect(
    await verifyExactActionACK(rejected, await actionEtag(rejected), f.action),
  ).toEqual(rejected);
  expect(exactActionSaved(rejected)).toBeNull();
});
