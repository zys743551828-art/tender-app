import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { packageReviewFixture } from "../qa-previews/frozen-inputs/packageReview";
import { packageReviewDecisionBody } from "../qa-previews/frozen-inputs/packageReviewDecision";
import { changeId as id } from "../qa-previews/frozen-inputs/factChange";
import { clearRecordedCommands } from "./recordedCommandStorage";
import {
  loadPackageReviewDecisionRecord,
  packageReviewDecisionScope,
  packageReviewDecisionStorageKey,
  storePackageReviewDecisionRecord,
} from "./packageReviewDecisionRecovery";
let f: Awaited<ReturnType<typeof packageReviewFixture>>;
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  sessionStorage.clear();
  f = await packageReviewFixture();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("retains row drafts and an exact pending CAS request across remount, isolated by member and result", async () => {
  const p = { ...f.props, run: f.completed },
    row = f.completed.result!.manifest.matrix[0],
    record = loadPackageReviewDecisionRecord(p);
  record.drafts[row.requirement_id] = {
    reason: "未提交的合成人工理由",
    quoteIndexes: [0],
  };
  record.pending = {
    key: id(900),
    requirementId: row.requirement_id,
    previousSequence: null,
    body: await packageReviewDecisionBody(f),
  };
  storePackageReviewDecisionRecord(record);
  expect(loadPackageReviewDecisionRecord(p)).toEqual(record);
  expect(
    loadPackageReviewDecisionRecord({
      ...p,
      scope: { ...p.scope, memberId: id(999) },
    }).pending,
  ).toBeNull();
  expect(
    loadPackageReviewDecisionRecord({
      ...p,
      run: { ...p.run, result: { ...p.run.result!, digest: "0".repeat(64) } },
    }).drafts,
  ).toEqual({});
});
it.each(["json", "scope", "quote", "draft_row"])(
  "preserves damaged %s storage and blocks writing a replacement request",
  async (field) => {
    const p = { ...f.props, run: f.completed },
      row = f.completed.result!.manifest.matrix[0],
      record = loadPackageReviewDecisionRecord(p);
    record.pending = {
      key: id(900),
      requirementId: row.requirement_id,
      previousSequence: null,
      body: await packageReviewDecisionBody(f),
    };
    if (field === "scope") record.scope.runId = id(999);
    if (field === "quote")
      record.pending.body.selected_quotes[0] = {
        ...record.pending.body.selected_quotes[0],
        quote: "被改写的引用",
      };
    if (field === "draft_row")
      record.drafts[id(999)] = { reason: "串到其他要求", quoteIndexes: [] };
    const raw = field === "json" ? "{broken" : JSON.stringify(record),
      key = packageReviewDecisionStorageKey(packageReviewDecisionScope(p));
    sessionStorage.setItem(key, raw);
    expect(() => loadPackageReviewDecisionRecord(p)).toThrow(/已阻止新保存/);
    expect(sessionStorage.getItem(key)).toBe(raw);
  },
);
it("participates in existing logout and account-switch cleanup, including saved business reasons", () => {
  const p = { ...f.props, run: f.completed },
    record = loadPackageReviewDecisionRecord(p);
  record.drafts[f.completed.result!.manifest.matrix[0].requirement_id] = {
    reason: "合成业务原因，不属于其他账户",
    quoteIndexes: [],
  };
  storePackageReviewDecisionRecord(record);
  clearRecordedCommands(f.props.scope.memberId);
  expect(sessionStorage.length).toBe(1);
  clearRecordedCommands(id(999));
  expect(sessionStorage.length).toBe(0);
});
it("does not overwrite the previously retained request when browser storage fails", async () => {
  const p = { ...f.props, run: f.completed },
    row = f.completed.result!.manifest.matrix[0],
    record = loadPackageReviewDecisionRecord(p);
  record.pending = {
    key: id(900),
    requirementId: row.requirement_id,
    previousSequence: null,
    body: await packageReviewDecisionBody(f),
  };
  storePackageReviewDecisionRecord(record);
  const before = sessionStorage.getItem(
    packageReviewDecisionStorageKey(record.scope),
  );
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new DOMException("full", "QuotaExceededError");
  });
  expect(() =>
    storePackageReviewDecisionRecord({ ...record, pending: null }),
  ).toThrow(/原请求可能已经受理/);
  expect(
    sessionStorage.getItem(packageReviewDecisionStorageKey(record.scope)),
  ).toBe(before);
});
