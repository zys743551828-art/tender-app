import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import {
  definitiveHistoryFailure,
  validateHistoryPending,
  type HistoryPending,
} from "./packageHistoricalResearchProtocol";
import {
  historyRecoveryKey,
  readHistoryRecovery,
  writeHistoryRecovery,
} from "./packageHistoricalResearchRecovery";
import { clearRecordedCommands } from "./recordedCommandStorage";

const id = (n: number) =>
  `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const member = id(1),
  other = id(2),
  digest = "a".repeat(64);
const protocol = (): HistoryPending => ({
  kind: "protocol",
  path: "/package-historical-research/protocols",
  key: id(3),
  etag: null,
  body: {
    method_digest: digest,
    seed: 17,
    bootstrap_iterations: 1000,
    reason: "明确冻结合成机制研究协议",
  },
  expected: {},
});
const admission = (): Extract<HistoryPending, { kind: "admission" }> => ({
  kind: "admission",
  path: `/bids/${id(10)}/packages/${id(11)}/revisions/${id(12)}/technical-scopes/${id(13)}/historical-admissions`,
  key: id(14),
  etag: `"package-history-context:${id(13)}:${digest}"`,
  body: {
    submission_id: id(15),
    outcome_id: id(16),
    proof_id: id(17),
    context_digest: digest,
    reason: "明确保存这份合成证据的机制候选",
  },
  expected: {
    bidId: id(10),
    packageId: id(11),
    revisionId: id(12),
    scopeId: id(13),
    scopeDigest: digest,
    submissionBindingDigest: digest,
    proofOrigin: "synthetic",
  },
});
beforeEach(() => {
  sessionStorage.clear();
  vi.restoreAllMocks();
});

it("retains the exact original body, conditional header and key after form/selection changes", () => {
  const pending = admission(),
    workspace = `admission:${id(10)}:${id(13)}`;
  writeHistoryRecovery(member, workspace, pending);
  const original = sessionStorage.getItem(
    historyRecoveryKey(member, workspace),
  );
  const changed = structuredClone(pending);
  changed.body.submission_id = id(115);
  changed.body.outcome_id = id(116);
  changed.key = id(114);
  expect(() => writeHistoryRecovery(member, workspace, changed)).toThrow(
    "不能用新的正文",
  );
  expect(readHistoryRecovery(member, workspace)).toEqual(pending);
  expect(sessionStorage.getItem(historyRecoveryKey(member, workspace))).toBe(
    original,
  );
  writeHistoryRecovery(member, workspace, pending);
  expect(readHistoryRecovery(member, workspace)).toEqual(pending);
});

it("uses independent research/admission workspaces and never restores another member", () => {
  const pending = protocol(),
    a = admission(),
    workspace = `admission:${id(10)}:${id(13)}`;
  writeHistoryRecovery(member, "research", pending);
  writeHistoryRecovery(member, workspace, a);
  expect(readHistoryRecovery(member)).toEqual(pending);
  expect(readHistoryRecovery(member, workspace)).toEqual(a);
  expect(readHistoryRecovery(other)).toBeNull();
  expect(() => writeHistoryRecovery(member, "research", a)).toThrow();
  expect(() => writeHistoryRecovery(member, workspace, pending)).toThrow();
  expect(() =>
    writeHistoryRecovery(member, `admission:${id(99)}:${id(13)}`, a),
  ).toThrow();
});

it("blocks malformed or identity-swapped stored requests without discarding them", () => {
  const key = historyRecoveryKey(member);
  for (const raw of [
    "{broken",
    JSON.stringify({
      version: 1,
      memberId: other,
      workspace: "research",
      pending: protocol(),
    }),
    JSON.stringify({
      version: 1,
      memberId: member,
      workspace: "research",
      pending: { ...protocol(), path: "/external/request" },
    }),
  ]) {
    sessionStorage.setItem(key, raw);
    expect(() => readHistoryRecovery(member)).toThrow();
    expect(() =>
      writeHistoryRecovery(member, "research", protocol()),
    ).toThrow();
    expect(sessionStorage.getItem(key)).toBe(raw);
  }
});

it("fails before sending when durable recovery storage is unavailable", () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new DOMException("quota", "QuotaExceededError");
  });
  expect(() => writeHistoryRecovery(member, "research", protocol())).toThrow(
    "未能保存",
  );
  expect(readHistoryRecovery(member)).toBeNull();
});

it("account cleanup retains only the current member and removes corrupt records without parsing", () => {
  const own = historyRecoveryKey(member),
    foreign = historyRecoveryKey(other);
  const localAdmission = historyRecoveryKey(
    member,
    `admission:${id(10)}:${id(13)}`,
  );
  sessionStorage.setItem(own, "{broken");
  sessionStorage.setItem(foreign, "{broken");
  sessionStorage.setItem(localAdmission, "{broken");
  sessionStorage.setItem("tender:theme", "dark");
  clearRecordedCommands(member);
  expect(sessionStorage.getItem(own)).toBe("{broken");
  expect(sessionStorage.getItem(foreign)).toBeNull();
  clearRecordedCommands();
  expect(sessionStorage.getItem(own)).toBeNull();
  expect(sessionStorage.getItem(localAdmission)).toBeNull();
  expect(sessionStorage.getItem("tender:theme")).toBe("dark");
});

describe("pending commands use only exact supported paths and their original conditions", () => {
  it.each(["key", "etag", "path", "expected", "extra", "body"])(
    "rejects tampered %s",
    (field) => {
      const value = structuredClone(admission()) as unknown as Record<
        string,
        unknown
      >;
      if (field === "extra") value.extra = true;
      else
        value[field] =
          field === "key"
            ? "unscoped-key"
            : field === "etag"
              ? '"weak"'
              : field === "body"
                ? { ...(value.body as object), formal_eligible: true }
                : field === "expected"
                  ? {}
                  : "/package-historical-research/protocols";
      expect(() => validateHistoryPending(value)).toThrow();
    },
  );
  it("requires timezone-aware cohort boundaries and refuses duplicate admissions", () => {
    const value: HistoryPending = {
      kind: "cohort",
      path: "/package-historical-research/cohorts",
      key: id(20),
      etag: null,
      expected: { protocolDigest: digest },
      body: {
        protocol_id: id(21),
        submission_split_at: "2026-01-01T00:00:00+08:00",
        label_available_as_of: "2026-09-01T00:00:00+08:00",
        selections: [22, 23, 24, 25].map((n, index) => ({
          admission_id: id(n),
          purpose: (["fit", "fit", "development", "final"] as const)[index],
        })),
        reason: "明确冻结分组及独立用途",
      },
    };
    expect(validateHistoryPending(value)).toEqual(value);
    expect(() =>
      validateHistoryPending({
        ...value,
        body: { ...value.body, submission_split_at: "2026-01-01T00:00:00" },
      }),
    ).toThrow();
    expect(() =>
      validateHistoryPending({
        ...value,
        body: {
          ...value.body,
          selections: Array(4).fill(value.body.selections[0]),
        },
      }),
    ).toThrow();
  });
});

it.each([
  [0, "NETWORK_ERROR", true],
  [503, "PACKAGE_HISTORY_NOT_CONFIGURED", false],
  [403, "PERMISSION_DENIED", false],
  [401, "AUTH_REQUIRED", false],
  [409, "COMMAND_INCOMPLETE", false],
  [409, "IDEMPOTENCY_CONFLICT", false],
  [429, "RATE_LIMIT", false],
  [408, "TIMEOUT", false],
])(
  "keeps ambiguous or pre-replay failures %s/%s",
  (status, code, retryable) => {
    expect(
      definitiveHistoryFailure(
        new ApiError("合成故障", status, code, undefined, retryable),
      ),
    ).toBe(false);
  },
);
it("recognizes a definitive stale-request rejection without treating malformed success as rejection", () => {
  expect(
    definitiveHistoryFailure(
      new ApiError("状态变化", 412, "PRECONDITION_FAILED"),
    ),
  ).toBe(true);
  expect(definitiveHistoryFailure(new Error("wrong ACK"))).toBe(false);
});
