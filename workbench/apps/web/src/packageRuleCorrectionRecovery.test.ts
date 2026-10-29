import { beforeEach, expect, it } from "vitest";
import { ApiError } from "./api";
import {
  correctionBase,
  correctionStorageKey,
  definitiveCorrectionFailure,
  readCorrectionRecovery,
  validCorrectionRequest,
  writeCorrectionRecovery,
  type CorrectionRecovery,
} from "./packageRuleCorrectionRecovery";
import { clearRecordedCommands } from "./recordedCommandStorage";
import {
  correctionFixture,
  correctionId,
  correctionPreview,
  correctionScope,
} from "./packageRuleCorrectionFixtures.test-support";

beforeEach(() => sessionStorage.clear());
async function record(): Promise<CorrectionRecovery> {
  const f = await correctionFixture(),
    preview = await correctionPreview(f.inventory, f.request, f.evidence);
  return {
    version: 1,
    scope: correctionScope,
    pending: {
      key: correctionId(700),
      etag: f.etag,
      base: correctionBase(f.inventory),
      body: { request: f.request, preview_digest: preview.digest },
    },
    last: null,
  };
}
it("restores the exact conditional request under member and package revision, with no automatic new command", async () => {
  const saved = await record();
  writeCorrectionRecovery(saved);
  expect(readCorrectionRecovery(correctionScope)).toEqual(saved);
  expect(
    readCorrectionRecovery({ ...correctionScope, memberId: correctionId(900) })
      .pending,
  ).toBeNull();
  expect(
    readCorrectionRecovery({
      ...correctionScope,
      revisionId: correctionId(901),
    }).pending,
  ).toBeNull();
});
it("blocks corrupt, cross-digest or unexpected stored request fields", async () => {
  const saved = await record();
  for (const corrupt of [
    "not-json",
    { ...saved, scope: { ...saved.scope, packageDigest: "0".repeat(64) } },
    { ...saved, pending: { ...saved.pending, etag: 'W/"weak"' } },
    {
      ...saved,
      pending: {
        ...saved.pending,
        body: { ...saved.pending!.body, unauthorized: true },
      },
    },
  ]) {
    sessionStorage.setItem(
      correctionStorageKey(correctionScope),
      typeof corrupt === "string" ? corrupt : JSON.stringify(corrupt),
    );
    expect(() => readCorrectionRecovery(correctionScope)).toThrow();
  }
});
it("keeps decimal spelling and denies duplicate edits, wrong-project rules and oversized reasons", async () => {
  const f = await correctionFixture();
  const scoring = {
    ...f.request,
    changes: [
      {
        op: "add" as const,
        rule: {
          ...(
            f.request.changes[0] as Extract<
              (typeof f.request.changes)[number],
              { op: "add" }
            >
          ).rule,
          kind: "scoring" as const,
          maximum: "12.5000",
        },
      },
    ],
  };
  expect(validCorrectionRequest(scoring, correctionScope.bidId)).toBe(true);
  expect(scoring.changes[0].rule.maximum).toBe("12.5000");
  const old = f.inventory.manifest.requirements[0];
  const withdraw = {
    op: "withdraw" as const,
    rule_id: old.rule_id,
    rule_digest: old.rule_digest,
    evidence_quotes: scoring.changes[0].rule.evidence_quotes,
  };
  expect(
    validCorrectionRequest(
      { ...f.request, changes: [withdraw, withdraw] },
      correctionScope.bidId,
    ),
  ).toBe(false);
  expect(
    validCorrectionRequest(
      { ...f.request, reason: "x".repeat(2001) },
      correctionScope.bidId,
    ),
  ).toBe(false);
  expect(validCorrectionRequest(scoring, correctionId(99))).toBe(false);
});
it("retains unknown, missing-original and generic conflict outcomes rather than releasing the original key", () => {
  for (const error of [
    new ApiError("network", 0, "NETWORK_ERROR"),
    new ApiError("conflict", 409, "IDEMPOTENCY_CONFLICT"),
    new ApiError("incomplete", 409, "COMMAND_INCOMPLETE"),
    new ApiError("missing", 503, "PACKAGE_ORIGINAL_UNAVAILABLE"),
    new ApiError("auth", 403, "FORBIDDEN"),
    new ApiError("unknown", 409, "UNKNOWN_CONFLICT"),
    new ApiError(
      "schema before original ACK",
      422,
      "PACKAGE_RULE_CORRECTION_INVALID",
    ),
    new ApiError("corrupt", 409, "PACKAGE_RULE_CORRECTION_CORRUPT"),
    new ApiError("unknown precondition", 412, "UNKNOWN_PRECONDITION"),
  ])
    expect(definitiveCorrectionFailure(error)).toBe(false);
  expect(
    definitiveCorrectionFailure(new ApiError("CAS", 412, "REVISION_CONFLICT")),
  ).toBe(true);
  for (const [status, code] of [
    [422, "PACKAGE_RULE_CORRECTION_QUOTE_INVALID"],
    [409, "ORIGINAL_BYTES_CORRUPTED"],
    [409, "PROJECT_WORK_CLOSED"],
  ] as const)
    expect(
      definitiveCorrectionFailure(
        new ApiError("proven rejected", status, code),
      ),
    ).toBe(true);
  expect(
    definitiveCorrectionFailure(
      new ApiError("temporary missing", 503, "ORIGINAL_NOT_AVAILABLE"),
    ),
  ).toBe(false);
  expect(
    definitiveCorrectionFailure(
      new ApiError(
        "preview changed",
        409,
        "PACKAGE_RULE_CORRECTION_PREVIEW_CHANGED",
      ),
    ),
  ).toBe(true);
});
it("uses the account cleanup registry while preserving the active member", async () => {
  const saved = await record();
  writeCorrectionRecovery(saved);
  const other = {
    ...saved,
    scope: { ...correctionScope, memberId: correctionId(900) },
  };
  writeCorrectionRecovery(other);
  clearRecordedCommands(correctionScope.memberId);
  expect(sessionStorage.getItem(correctionStorageKey(other.scope))).toBeNull();
  expect(readCorrectionRecovery(correctionScope).pending).toEqual(
    saved.pending,
  );
  clearRecordedCommands();
  expect(
    sessionStorage.getItem(correctionStorageKey(correctionScope)),
  ).toBeNull();
});
