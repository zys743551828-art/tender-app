import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { clearRecordedCommands } from "./recordedCommandStorage";
import {
  documentParseStorageKey,
  loadDocumentParseRecord,
  storeDocumentParseRecord,
} from "./documentParseRecovery";
import {
  documentParseTestFixture,
  documentParseTestId as id,
} from "./documentParseTestFixture";
let f: Awaited<ReturnType<typeof documentParseTestFixture>>;
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  sessionStorage.clear();
  f = await documentParseTestFixture();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("keeps original bodies under exact member, bid and document scope", () => {
  const record = {
    version: 1 as const,
    scope: f.scope,
    pending: f.pending,
    lastId: f.request.id,
  };
  storeDocumentParseRecord(record);
  expect(loadDocumentParseRecord(f.scope)).toEqual(record);
  for (const key of ["memberId", "bidId", "documentId"] as const)
    expect(
      loadDocumentParseRecord({ ...f.scope, [key]: id(99) }).pending,
    ).toBeNull();
});
it("is covered by logout and account-switch cleanup", () => {
  const record = {
    version: 1 as const,
    scope: f.scope,
    pending: f.pending,
    lastId: null,
  };
  storeDocumentParseRecord(record);
  clearRecordedCommands(f.scope.memberId);
  expect(loadDocumentParseRecord(f.scope).pending).toEqual(f.pending);
  clearRecordedCommands(id(99));
  expect(loadDocumentParseRecord(f.scope).pending).toBeNull();
  storeDocumentParseRecord(record);
  clearRecordedCommands();
  expect(loadDocumentParseRecord(f.scope).pending).toBeNull();
});
it("blocks new work on malformed or transplanted recovery records without deleting evidence", () => {
  const key = documentParseStorageKey(f.scope),
    raw = JSON.stringify({
      version: 1,
      scope: { ...f.scope, memberId: id(99) },
      pending: f.pending,
      lastId: null,
    });
  sessionStorage.setItem(key, raw);
  expect(() => loadDocumentParseRecord(f.scope)).toThrow(/无法核验/);
  expect(sessionStorage.getItem(key)).toBe(raw);
});
it("reports storage failures without claiming a prior network request was not sent", () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new DOMException("synthetic quota", "QuotaExceededError");
  });
  expect(() =>
    storeDocumentParseRecord({
      version: 1,
      scope: f.scope,
      pending: f.pending,
      lastId: null,
    }),
  ).toThrow(/可能已经受理/);
});
