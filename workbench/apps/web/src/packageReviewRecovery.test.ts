import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { packageReviewFixture } from "../qa-previews/frozen-inputs/packageReview";
import { changeId as id } from "../qa-previews/frozen-inputs/factChange";
import { dependencyPlanScope } from "./dependencyPlanProtocol";
import { clearRecordedCommands } from "./recordedCommandStorage";
import {
  loadPackageReviewCancel,
  loadPackageReviewRecord,
  packageReviewCancelStorageKey,
  packageReviewStorageKey,
  storePackageReviewCancel,
  storePackageReviewRecord,
} from "./packageReviewRecovery";

let fixture: Awaited<ReturnType<typeof packageReviewFixture>>;
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  sessionStorage.clear();
  fixture = await packageReviewFixture();
});
afterEach(() => vi.unstubAllGlobals());
it("retains the original launch body, key, prepared scope and last run across remount", () => {
  const record = loadPackageReviewRecord(fixture.props);
  record.pending = { key: id(150), body: fixture.body };
  record.lastId = fixture.run.id;
  storePackageReviewRecord(record);
  expect(loadPackageReviewRecord(fixture.props)).toEqual(record);
  expect(
    loadPackageReviewRecord({
      ...fixture.props,
      scope: { ...fixture.props.scope, memberId: id(151) },
    }).pending,
  ).toBeNull();
});
it.each(["{broken", JSON.stringify({ version: 1, pending: null })])(
  "preserves damaged records instead of silently starting again",
  (raw) => {
    const key = packageReviewStorageKey(dependencyPlanScope(fixture.props));
    sessionStorage.setItem(key, raw);
    expect(() => loadPackageReviewRecord(fixture.props)).toThrow(
      "已阻止新启动",
    );
    expect(sessionStorage.getItem(key)).toBe(raw);
  },
);
it("rejects copied scope or plan digests but keeps the retained evidence of the pending request", () => {
  const record = loadPackageReviewRecord(fixture.props);
  record.pending = {
    key: id(150),
    body: { ...fixture.body, execution_input_digest: "0".repeat(64) },
  };
  storePackageReviewRecord(record);
  expect(() => loadPackageReviewRecord(fixture.props)).toThrow();
  expect(sessionStorage.length).toBe(1);
});
it("preserves exact cancellation body, operation identity and If-Match for recovery", () => {
  const pending = {
    key: id(151),
    etag: '"operation-revision-1"',
    body: { reason: "合成取消理由", cancel_pending_same_input: false as const },
  };
  storePackageReviewCancel(fixture.props, fixture.run, pending);
  expect(loadPackageReviewCancel(fixture.props, fixture.run)).toEqual(pending);
  const key = packageReviewCancelStorageKey(fixture.props, fixture.run),
    corrupt = JSON.parse(sessionStorage.getItem(key)!);
  corrupt.scope.operationId = id(152);
  sessionStorage.setItem(key, JSON.stringify(corrupt));
  expect(() => loadPackageReviewCancel(fixture.props, fixture.run)).toThrow(
    "任务身份不符",
  );
});
it("uses registered account cleanup for both launch and cancellation while keeping the signed-in member", () => {
  const record = loadPackageReviewRecord(fixture.props);
  record.pending = { key: id(150), body: fixture.body };
  storePackageReviewRecord(record);
  storePackageReviewCancel(fixture.props, fixture.run, {
    key: id(151),
    etag: '"original"',
    body: { reason: "含业务原因的原请求", cancel_pending_same_input: false },
  });
  clearRecordedCommands(fixture.props.scope.memberId);
  expect(sessionStorage.length).toBe(2);
  clearRecordedCommands(id(152));
  expect(sessionStorage.length).toBe(0);
});
