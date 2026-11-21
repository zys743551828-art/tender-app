import { beforeEach, expect, it } from "vitest";
import { captureFixture } from "./authoringCaptureFixtures.test-support";
import { clearKnowledgeStorage } from "./knowledgeStorage";
import {
  outlineSelectionKey,
  recoverOutlineSelection,
  storeOutlineSelection,
} from "./technicalOutlineSelection";

const f = captureFixture();
const scope = {
  memberId: f.memberId,
  bidId: f.bidId,
  draftId: f.request.target_section.draft_id,
};
const otherId = "d43187a0-d0da-4490-ab27-1ce0898df2e8";
const { target, authority, inventory } = f.request.package_context;
const basis = {
  target,
  authority,
  inventory: { id: inventory.id, digest: inventory.digest },
};

beforeEach(() => sessionStorage.clear());

it("preserves only exact reference choices and participates in account cleanup", () => {
  const anotherDraft = { ...scope, draftId: otherId };
  storeOutlineSelection(scope, basis);
  storeOutlineSelection(anotherDraft, basis);
  expect(recoverOutlineSelection(scope)).toEqual(basis);
  storeOutlineSelection(scope, null);
  expect(recoverOutlineSelection(scope)).toBeNull();
  expect(recoverOutlineSelection(anotherDraft)).toEqual(basis);
  clearKnowledgeStorage(otherId);
  expect(recoverOutlineSelection(anotherDraft)).toBeNull();
});

it("rejects copied records across accounts, bids and drafts even if found under the new key", () => {
  storeOutlineSelection(scope, basis);
  const saved = sessionStorage.getItem(outlineSelectionKey(scope))!;
  for (const field of ["memberId", "bidId", "draftId"]) {
    const wrongScope = { ...scope, [field]: otherId };
    sessionStorage.setItem(outlineSelectionKey(wrongScope), saved);
    expect(recoverOutlineSelection(wrongScope)).toBeNull();
  }
});

it("does not reflect incomplete, embedded unauthorized state, or malformed cache", () => {
  storeOutlineSelection(scope, basis);
  const key = outlineSelectionKey(scope);
  const envelope = JSON.parse(sessionStorage.getItem(key)!);
  for (const raw of [
    "not-json",
    "x".repeat(4100),
    JSON.stringify({ ...envelope, approved: true }),
    JSON.stringify({
      ...envelope,
      basis: { ...basis, inventory: { id: inventory.id } },
    }),
    JSON.stringify({ ...envelope, basis: { ...basis, authority: target } }),
    JSON.stringify({
      ...envelope,
      basis: { ...basis, target: { ...target, statement: "not an ID" } },
    }),
  ]) {
    sessionStorage.setItem(key, raw);
    expect(recoverOutlineSelection(scope)).toBeNull();
  }
});
