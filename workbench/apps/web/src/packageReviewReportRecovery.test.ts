import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { packageReviewReportFixture } from "../qa-previews/frozen-inputs/packageReviewReport";
import {
  loadPackageReviewReportRecord,
  storePackageReviewReportRecord,
  packageReviewReportStorageKey,
  loadPackageReviewReportCancel,
  storePackageReviewReportCancel,
} from "./packageReviewReportRecovery";
import { clearRecordedCommands } from "./recordedCommandStorage";
import { changeId as id } from "../qa-previews/frozen-inputs/factChange";
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  sessionStorage.clear();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("keeps start and cancellation requests exact and clears both across account cleanup", async () => {
  const f = await packageReviewReportFixture(),
    member = f.f.props.scope.memberId,
    run = f.f.completed;
  const record = {
    ...loadPackageReviewReportRecord(member, run),
    pending: { key: id(390), body: f.body },
  };
  storePackageReviewReportRecord(member, run, record);
  const cancel = {
    key: id(391),
    etag: '"v1"',
    body: { reason: "合成取消报告", cancel_pending_same_input: false as const },
  };
  storePackageReviewReportCancel(member, run, f.report, cancel);
  expect(loadPackageReviewReportRecord(member, run)).toEqual(record);
  expect(loadPackageReviewReportCancel(member, run, f.report)).toEqual(cancel);
  clearRecordedCommands(member);
  expect(sessionStorage.length).toBe(2);
  clearRecordedCommands(id(999));
  expect(sessionStorage.length).toBe(0);
});
it.each(["null", "{}", "broken"])(
  "does not silently discard a corrupt stored report request: %s",
  async (raw) => {
    const f = await packageReviewReportFixture(),
      member = f.f.props.scope.memberId;
    sessionStorage.setItem(
      packageReviewReportStorageKey(member, f.f.completed),
      raw,
    );
    expect(() => loadPackageReviewReportRecord(member, f.f.completed)).toThrow(
      /新申请已暂停/,
    );
  },
);
it("rejects a transplanted recovery record from a different original result", async () => {
  const f = await packageReviewReportFixture(),
    member = f.f.props.scope.memberId,
    r = loadPackageReviewReportRecord(member, f.f.completed);
  r.scope.resultDigest = "0".repeat(64);
  sessionStorage.setItem(
    packageReviewReportStorageKey(member, f.f.completed),
    JSON.stringify(r),
  );
  expect(() => loadPackageReviewReportRecord(member, f.f.completed)).toThrow();
});
