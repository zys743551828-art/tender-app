import { ApiError } from "./api";
import type {
  AuthoringWordImportPrepareRequest,
  AuthoringWordImportResolveRequest,
} from "./contracts";
import { authoringStorageKey } from "./editorStorage";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";

export type WordImportScope = {
  memberId: string;
  bidId: string;
  draftId: string;
};
export type PendingWordImport =
  | {
      kind: "prepare";
      key: string;
      etag: string;
      body: AuthoringWordImportPrepareRequest;
    }
  | {
      kind: "resolve";
      candidateId: string;
      key: string;
      etag: string;
      body: AuthoringWordImportResolveRequest;
    };
export type WordImportRecovery = {
  version: 1;
  scope: WordImportScope;
  pending: PendingWordImport | null;
  lastCandidateId: string | null;
};
const positive = (value: unknown, maximum = Number.MAX_SAFE_INTEGER) =>
  Number.isSafeInteger(value) && Number(value) > 0 && Number(value) <= maximum;
export const wordImportReasonValid = (value: unknown): value is string =>
  typeof value === "string" &&
  !!value.trim() &&
  Array.from(value).length <= 1000 &&
  Array.from(value).every((character) => {
    const point = character.codePointAt(0)!;
    return point > 31 && point !== 127 && (point < 0xd800 || point > 0xdfff);
  });
export const wordImportPath = (scope: WordImportScope) =>
  `/bids/${scope.bidId}/drafts/${scope.draftId}/word-imports`;
export const wordImportStorageKey = (scope: WordImportScope) =>
  authoringStorageKey(
    scope.memberId,
    scope.bidId,
    `${scope.draftId}:word-import`,
  );

function validPending(value: unknown): value is PendingWordImport {
  if (
    !recordObject(value) ||
    !executionId(value.key) ||
    typeof value.etag !== "string" ||
    !/^"[^"\r\n]+"$/.test(value.etag) ||
    value.etag.length > 512 ||
    !recordObject(value.body) ||
    !wordImportReasonValid(value.body.reason)
  )
    return false;
  const body = value.body;
  if (value.kind === "prepare")
    return (
      exactKeys(value, ["kind", "key", "etag", "body"]) &&
      exactKeys(body, [
        "source_document_version_id",
        "source_digest",
        "source_byte_size",
        "base_draft_revision",
        "method_digest",
        "reason",
      ]) &&
      executionId(body.source_document_version_id) &&
      executionSha(body.source_digest) &&
      positive(body.source_byte_size, 33554432) &&
      positive(body.base_draft_revision) &&
      executionSha(body.method_digest)
    );
  return (
    value.kind === "resolve" &&
    exactKeys(value, ["kind", "candidateId", "key", "etag", "body"]) &&
    executionId(value.candidateId) &&
    exactKeys(body, [
      "decision",
      "candidate_digest",
      "acknowledged_issue_ids",
      "reason",
    ]) &&
    ["append", "reject"].includes(String(body.decision)) &&
    executionSha(body.candidate_digest) &&
    Array.isArray(body.acknowledged_issue_ids) &&
    body.acknowledged_issue_ids.length <= 10000 &&
    new Set(body.acknowledged_issue_ids).size ===
      body.acknowledged_issue_ids.length &&
    body.acknowledged_issue_ids.every(executionSha)
  );
}

export function readWordImportRecovery(
  scope: WordImportScope,
): WordImportRecovery {
  try {
    const raw = sessionStorage.getItem(wordImportStorageKey(scope));
    if (raw === null)
      return { version: 1, scope, pending: null, lastCandidateId: null };
    const value: unknown = JSON.parse(raw);
    if (
      !recordObject(value) ||
      !exactKeys(value, ["version", "scope", "pending", "lastCandidateId"]) ||
      value.version !== 1 ||
      !recordObject(value.scope) ||
      !exactKeys(value.scope, ["memberId", "bidId", "draftId"]) ||
      Object.entries(scope).some(
        ([key, item]) =>
          value.scope && (value.scope as Record<string, unknown>)[key] !== item,
      ) ||
      (value.lastCandidateId !== null && !executionId(value.lastCandidateId)) ||
      (value.pending !== null && !validPending(value.pending))
    )
      throw new Error("invalid stored import request");
    return value as WordImportRecovery;
  } catch {
    throw new Error(
      "Word导入恢复记录无法核验，新申请已暂停。请保留记录并从服务器导入历史核对，未丢弃原请求。",
    );
  }
}

export function storeWordImportRecovery(value: WordImportRecovery) {
  try {
    sessionStorage.setItem(
      wordImportStorageKey(value.scope),
      JSON.stringify(value),
    );
  } catch {
    throw new Error(
      "浏览器未能保存Word导入恢复记录。请释放此站点存储空间后恢复原请求；未确认的操作可能已被受理。",
    );
  }
}

const rejectedImportCodes = new Set([
  "AUTHORING_WORD_IMPORT_METHOD_CHANGED",
  "AUTHORING_WORD_IMPORT_ORIGINAL_CHANGED",
  "AUTHORING_WORD_IMPORT_CONTEXT_CHANGED",
  "AUTHORING_WORD_IMPORT_SOURCE_CHANGED",
  "AUTHORING_WORD_IMPORT_ACTOR_CHANGED",
  "AUTHORING_WORD_IMPORT_CANDIDATE_CHANGED",
  "AUTHORING_WORD_IMPORT_ALREADY_RESOLVED",
  "AUTHORING_WORD_IMPORT_BLOCKED",
]);

/** These domain failures precede the import transaction's commit; unknown 409 stays pending. */
export function definitiveWordImportFailure(error: unknown) {
  return (
    error instanceof ApiError &&
    !error.retryable &&
    error.code !== "SERVICE_VERSION_NOT_READY" &&
    ([400, 412, 413, 422].includes(error.status) ||
      (error.status === 409 && rejectedImportCodes.has(error.code)))
  );
}
