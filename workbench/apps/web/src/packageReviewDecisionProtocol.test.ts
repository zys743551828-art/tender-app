import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { packageReviewFixture } from "../qa-previews/frozen-inputs/packageReview";
import {
  packageReviewDecisionBody,
  packageReviewDecisionCurrent,
  packageReviewDecisionPage,
  packageReviewDecisionReply,
} from "../qa-previews/frozen-inputs/packageReviewDecision";
import { changeId as id } from "../qa-previews/frozen-inputs/factChange";
import { frozenManifestDigest } from "./packageFrozenInput";
import {
  validatePackageReviewDecision,
  validatePackageReviewDecisionCurrent,
  validatePackageReviewDecisionPage,
  validPackageReviewDecisionBody,
} from "./packageReviewDecisionProtocol";

let f: Awaited<ReturnType<typeof packageReviewFixture>>;
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  f = await packageReviewFixture();
});
afterEach(() => {
  vi.unstubAllGlobals();
});
it("validates lightweight current heads for the entire exact matrix without duplicating quotes", async () => {
  const body = await packageReviewDecisionBody(f),
    head = await packageReviewDecisionReply(f, body, 0, 1, id(999)),
    current = await packageReviewDecisionCurrent(f, [head]);
  await expect(
    validatePackageReviewDecisionCurrent(current, f.completed),
  ).resolves.toEqual(current);
  expect(current.items[0].current).not.toHaveProperty("manifest");
  expect(current.items[0].current).not.toHaveProperty("selected_quotes");
});
it.each(["scope", "row_digest", "missing", "duplicate", "full_manifest"])(
  "rejects %s in the current-head directory",
  async (field) => {
    const body = await packageReviewDecisionBody(f),
      head = await packageReviewDecisionReply(f, body),
      current = await packageReviewDecisionCurrent(f, [head]);
    if (field === "scope")
      current.scope = { ...current.scope, package_id: id(999) };
    if (field === "row_digest") current.items[0].row_digest = "0".repeat(64);
    if (field === "missing") current.items.pop();
    if (field === "duplicate") current.items[1] = current.items[0];
    if (field === "full_manifest")
      Object.assign(current.items[0].current!, { manifest: head.manifest });
    await expect(
      validatePackageReviewDecisionCurrent(current, f.completed),
    ).rejects.toThrow(/人工记录/);
  },
);
it("binds a complete ACK to its original actor, sequence, body and quoted row", async () => {
  const body = await packageReviewDecisionBody(f),
    value = await packageReviewDecisionReply(f, body),
    row = f.completed.result!.manifest.matrix[0];
  const pending = {
    key: id(990),
    requirementId: row.requirement_id,
    previousSequence: null,
    body,
  };
  await expect(
    validatePackageReviewDecision(
      value,
      f.completed,
      row,
      pending,
      f.props.scope.memberId,
    ),
  ).resolves.toEqual(value);
  await expect(
    validatePackageReviewDecision(value, f.completed, row, pending, id(999)),
  ).rejects.toThrow(/人工记录/);
  await expect(
    validatePackageReviewDecision(
      value,
      f.completed,
      row,
      { ...pending, body: { ...body, state: "rejected" } },
      f.props.scope.memberId,
    ),
  ).rejects.toThrow(/人工记录/);
});
it.each(["quote", "qualification", "row", "sequence", "reason"])(
  "rejects a rehashed human record with invalid %s or changed request contents",
  async (field) => {
    const body = await packageReviewDecisionBody(f),
      value = await packageReviewDecisionReply(f, body),
      row = f.completed.result!.manifest.matrix[0];
    const pending = {
      key: id(990),
      requirementId: row.requirement_id,
      previousSequence: null,
      body: structuredClone(body),
    };
    if (field === "quote")
      value.manifest.selected_quotes[0] = {
        ...value.manifest.selected_quotes[0],
        physical_page: 9,
      };
    if (field === "qualification")
      value.manifest.formal_scoring_eligible = true as false;
    if (field === "row")
      value.manifest.requirement_id =
        f.completed.result!.manifest.matrix[1].requirement_id;
    if (field === "sequence") value.manifest.sequence_no = 2;
    if (field === "reason") value.manifest.reason = "其他请求的有效理由";
    value.digest = await frozenManifestDigest(value.manifest);
    await expect(
      validatePackageReviewDecision(
        value,
        f.completed,
        row,
        pending,
        f.props.scope.memberId,
      ),
    ).rejects.toThrow(/人工记录/);
  },
);
it("permits opinion without selected quotes and counts the reason in Unicode characters", async () => {
  const body = await packageReviewDecisionBody(f),
    row = f.completed.result!.manifest.matrix[0];
  body.selected_quotes = [];
  body.reason = "🔎".repeat(2000);
  expect(validPackageReviewDecisionBody(body, f.completed, row)).toBe(true);
  body.reason += "超";
  expect(validPackageReviewDecisionBody(body, f.completed, row)).toBe(false);
});
it("validates immutable history chains and refuses a correctly hashed unrelated predecessor", async () => {
  const body = await packageReviewDecisionBody(f),
    first = await packageReviewDecisionReply(f, body),
    nextBody = await packageReviewDecisionBody(f, 0, first, "needs_review"),
    second = await packageReviewDecisionReply(f, nextBody, 0, 2),
    page = await packageReviewDecisionPage(f, [second, first]),
    row = f.completed.result!.manifest.matrix[0];
  await expect(
    validatePackageReviewDecisionPage(page, f.completed, row),
  ).resolves.toEqual(page);
  second.manifest.previous_head = { id: id(999), digest: "a".repeat(64) };
  second.digest = await frozenManifestDigest(second.manifest);
  await expect(
    validatePackageReviewDecisionPage(page, f.completed, row),
  ).rejects.toThrow(/人工记录/);
});
