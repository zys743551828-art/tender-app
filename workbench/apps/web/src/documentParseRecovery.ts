import {
  exactKeys,
  executionId,
  recordObject,
} from "./executionInputValidation";
import { recordedCommandStorageKey } from "./recordedCommandStorage";
import { validPendingDocumentParse } from "./documentParseProtocol";
import type {
  DocumentParseScope,
  PendingDocumentParse,
} from "./documentParseProtocol";

export type DocumentParseRecord = {
  version: 1;
  scope: DocumentParseScope;
  pending: PendingDocumentParse | null;
  lastId: string | null;
};
export const documentParseStorageKey = (scope: DocumentParseScope) =>
  recordedCommandStorageKey(
    "document-parse",
    scope.memberId,
    scope.bidId,
    scope.documentId,
  );
export function loadDocumentParseRecord(
  scope: DocumentParseScope,
): DocumentParseRecord {
  try {
    const raw = sessionStorage.getItem(documentParseStorageKey(scope));
    if (raw === null) return { version: 1, scope, pending: null, lastId: null };
    const value: unknown = JSON.parse(raw);
    if (
      !recordObject(value) ||
      !exactKeys(value, ["version", "scope", "pending", "lastId"]) ||
      value.version !== 1 ||
      !recordObject(value.scope) ||
      !exactKeys(value.scope, ["memberId", "bidId", "documentId"]) ||
      Object.entries(scope).some(
        ([key, item]) => (value.scope as Record<string, unknown>)[key] !== item,
      ) ||
      (value.pending !== null && !validPendingDocumentParse(value.pending)) ||
      (value.lastId !== null && !executionId(value.lastId))
    )
      throw new Error("invalid stored parse request");
    return value as DocumentParseRecord;
  } catch {
    throw new Error(
      "原件解析的恢复记录无法核验，新申请已暂停；仍可查阅服务器解析历史。请保留原记录核对。",
    );
  }
}
export function storeDocumentParseRecord(record: DocumentParseRecord) {
  try {
    sessionStorage.setItem(
      documentParseStorageKey(record.scope),
      JSON.stringify(record),
    );
  } catch {
    throw new Error(
      "浏览器未能更新解析恢复记录。原申请可能已经受理，请按原请求恢复或核对服务器历史。",
    );
  }
}
