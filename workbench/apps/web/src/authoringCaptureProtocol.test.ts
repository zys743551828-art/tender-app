import { expect, it } from "vitest";
import { captureFixture } from "./authoringCaptureFixtures.test-support";
import { buildCaptureRequest, readCaptureDraft } from "./authoringCaptureForm";
import {
  captureInventoryView,
  capturePackageView,
} from "./authoringCaptureDirectoryProtocol";
import {
  validateCaptureFacts,
  validateCaptureFactSets,
  validateCaptureNodes,
} from "./authoringInputCatalogProtocol";
import {
  captureCommandKey,
  readCaptureRecovery,
  validateCaptureAck,
  verifyCaptureRecovery,
} from "./authoringCaptureCommandProtocol";
import { clearRecordedCommands } from "./recordedCommandStorage";
import { jsonDigest } from "./editorSchema";

it("accepts native discovery and reconstructs the complete explicit save request", async () => {
  const f = captureFixture();
  const nodes = await validateCaptureNodes(f.body("nodes"), f.bidId, {
    snapshot_id: f.request.target_section.snapshot_id,
    snapshot_digest: f.request.target_section.snapshot_digest,
    section_id: f.request.target_section.section_id,
    section_digest: f.request.target_section.section_digest,
  });
  validateCaptureFactSets(f.body("sets"), f.bidId);
  const facts = validateCaptureFacts(
    f.body("facts"),
    f.bidId,
    f.facts.selection,
  );
  const target = await capturePackageView(
    f.body("target"),
    f.bidId,
    "target",
    f.request.package_context.target,
  );
  const authority = await capturePackageView(
    f.body("authority"),
    f.bidId,
    "authority",
    f.request.package_context.authority,
  );
  const inventory = await captureInventoryView(
    f.body("inventory"),
    target,
    authority,
    f.request.package_context.inventory,
  );
  const request = buildCaptureRequest(readCaptureDraft(f.draft, f.bidId), {
    target,
    authority,
    inventory,
    nodes,
    facts,
    items: facts.items,
    snapshot: f.snapshot,
  });
  expect({
    ...request,
    facts: {
      ...request.facts,
      identity_fact_ids: [...request.facts.identity_fact_ids].sort(),
    },
  }).toEqual({
    ...f.request,
    facts: {
      ...f.request.facts,
      identity_fact_ids: [...f.request.facts.identity_fact_ids].sort(),
    },
  });
});

it("rejects edited original text even when the discovery envelope is rehashed", async () => {
  const f = captureFixture();
  const value = f.body<Record<string, unknown>>("nodes");
  (value.nodes as { text: string }[])[0].text = "Changed node text";
  const basis = { ...value };
  delete basis.observation_digest;
  delete basis.observed_at;
  value.observation_digest = await jsonDigest(basis);
  await expect(
    validateCaptureNodes(value, f.bidId, f.request.target_section),
  ).rejects.toThrow();
});

it("does not reuse fact pages from another fixed package or silently choose a new head", () => {
  const f = captureFixture();
  const wrong = structuredClone(f.facts.selection);
  wrong.target.revision_id = crypto.randomUUID();
  expect(() => validateCaptureFacts(f.body("facts"), f.bidId, wrong)).toThrow();
  const value = f.body<Record<string, unknown>>("facts");
  (value.current_head as { revision: number }).revision += 1;
  expect(() =>
    validateCaptureFacts(value, f.bidId, f.facts.selection),
  ).toThrow();
});

it("binds recovery and native ACK to actor, project, complete request, and original key", async () => {
  const f = captureFixture();
  const scope = { memberId: f.memberId, bidId: f.bidId };
  const request = {
    method: "POST" as const,
    path: "/bids/" + f.bidId + "/authoring/package-inputs",
    etag: "" as const,
    key: crypto.randomUUID(),
    body: f.request,
  };
  const recovery = {
    version: 1 as const,
    scope,
    state: "pending" as const,
    request,
    request_digest: await jsonDigest({ scope, request }),
  };
  await expect(
    validateCaptureAck({ data: f.saved, etag: null }, recovery),
  ).resolves.toMatchObject({ digest: f.saved.digest });
  expect(() =>
    readCaptureRecovery(JSON.stringify(recovery), {
      ...scope,
      memberId: crypto.randomUUID(),
    }),
  ).toThrow();
  const changed = structuredClone(recovery);
  changed.request.body.facts.uses[0].reason += " changed";
  await expect(verifyCaptureRecovery(changed)).rejects.toThrow();
  sessionStorage.setItem(captureCommandKey(scope), JSON.stringify(recovery));
  clearRecordedCommands(f.memberId);
  expect(sessionStorage.getItem(captureCommandKey(scope))).not.toBeNull();
  clearRecordedCommands();
  expect(sessionStorage.getItem(captureCommandKey(scope))).toBeNull();
});
