import { beforeEach, expect, it } from "vitest";
import { ApiError } from "./api";
import { clearAuthoringStorage } from "./editorStorage";
import {
  definitiveWordImportFailure,
  readWordImportRecovery,
  storeWordImportRecovery,
  wordImportStorageKey,
} from "./authoringWordImportRecovery";
import type { WordImportRecovery } from "./authoringWordImportRecovery";

const scope = {
  memberId: "00000000-0000-4000-8000-000000000001",
  bidId: "00000000-0000-4000-8000-000000000002",
  draftId: "00000000-0000-4000-8000-000000000003",
};
const candidateId = "00000000-0000-4000-8000-000000000004";
function request(): WordImportRecovery {
  return {
    version: 1,
    scope,
    pending: {
      kind: "prepare",
      key: "00000000-0000-4000-8000-000000000005",
      etag: '"draft-7"',
      body: {
        source_document_version_id: "00000000-0000-4000-8000-000000000006",
        source_digest: "a".repeat(64),
        source_byte_size: 23000,
        base_draft_revision: 7,
        method_digest: "b".repeat(64),
        reason: "导入已核对的原件，先查看候选",
      },
    },
    lastCandidateId: candidateId,
  };
}
beforeEach(() => sessionStorage.clear());

it("刷新保留精确原件、方法、修订、原键与If-Match，记录不包含Word正文", () => {
  const original = request();
  storeWordImportRecovery(original);
  expect(readWordImportRecovery(scope)).toEqual(original);
  expect(
    JSON.parse(sessionStorage.getItem(wordImportStorageKey(scope))!),
  ).not.toHaveProperty("content");
});

it("追加确认的损失ID与理由按原请求恢复，不重新取得草稿头", () => {
  const original: WordImportRecovery = {
    ...request(),
    pending: {
      kind: "resolve",
      candidateId,
      key: "00000000-0000-4000-8000-000000000007",
      etag: '"draft-7"',
      body: {
        decision: "append",
        candidate_digest: "c".repeat(64),
        acknowledged_issue_ids: ["d".repeat(64), "e".repeat(64)],
        reason: "已逐项核对损失，追加为新章节",
      },
    },
  };
  storeWordImportRecovery(original);
  expect(readWordImportRecovery(scope)).toEqual(original);
});

it.each(["memberId", "bidId", "draftId"] as const)(
  "拒绝错置到另一%s的恢复记录",
  (field) => {
    const other = { ...scope, [field]: "00000000-0000-4000-8000-000000000099" };
    sessionStorage.setItem(
      wordImportStorageKey(other),
      JSON.stringify(request()),
    );
    expect(() => readWordImportRecovery(other)).toThrow("无法核验");
    expect(sessionStorage.getItem(wordImportStorageKey(other))).not.toBeNull();
  },
);

it.each([
  { source_digest: "not-a-digest" },
  { source_byte_size: 0 },
  { base_draft_revision: 0 },
  { content: "unexpected private Word content" },
])("损坏的精确请求不会被当作新的空白申请：%j", (change) => {
  const original = request();
  original.pending!.body = { ...original.pending!.body, ...change };
  sessionStorage.setItem(wordImportStorageKey(scope), JSON.stringify(original));
  expect(() => readWordImportRecovery(scope)).toThrow("无法核验");
});

it("同账号继续可恢复，切账号和退出清理导入请求与候选定位", () => {
  const own = request();
  const other = {
    ...request(),
    scope: { ...scope, memberId: "00000000-0000-4000-8000-000000000099" },
  };
  storeWordImportRecovery(own);
  storeWordImportRecovery(other);
  clearAuthoringStorage(scope.memberId);
  expect(readWordImportRecovery(scope)).toEqual(own);
  expect(sessionStorage.getItem(wordImportStorageKey(other.scope))).toBeNull();
  clearAuthoringStorage();
  expect(sessionStorage.getItem(wordImportStorageKey(scope))).toBeNull();
});

it("CAS明确拒绝可结束请求；网络、认证恢复、幂等冲突和未知ACK继续保留", () => {
  expect(
    definitiveWordImportFailure(
      new ApiError("stale", 412, "PRECONDITION_FAILED"),
    ),
  ).toBe(true);
  expect(
    definitiveWordImportFailure(
      new ApiError(
        "method changed",
        409,
        "AUTHORING_WORD_IMPORT_METHOD_CHANGED",
      ),
    ),
  ).toBe(true);
  expect(
    definitiveWordImportFailure(
      new ApiError("unrecognized", 409, "UNRECOGNIZED_CONFLICT"),
    ),
  ).toBe(false);
  for (const error of [
    new ApiError("offline", 0, "NETWORK_ERROR", undefined, true),
    new ApiError("login", 401, "LOGIN_REQUIRED"),
    new ApiError("permission changed before replay", 403, "FORBIDDEN"),
    new ApiError("endpoint unavailable before replay", 404, "NOT_FOUND"),
    new ApiError("conflict", 409, "IDEMPOTENCY_CONFLICT"),
    new ApiError("unfinished", 409, "COMMAND_INCOMPLETE"),
    new ApiError(
      "missing route",
      404,
      "SERVICE_VERSION_NOT_READY",
      undefined,
      true,
    ),
    new ApiError("failed", 503, "UNAVAILABLE", undefined, true),
    new Error("响应身份无法核对"),
  ])
    expect(definitiveWordImportFailure(error)).toBe(false);
});
