import { ApiError } from "./api";
import type {
  DocumentParseContext,
  DocumentParsePage,
  DocumentParseStarted,
  DocumentParseView,
  StartDocumentParse,
} from "./contracts";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
import { frozenManifestDigest } from "./packageFrozenInput";

export type DocumentParseScope = {
  memberId: string;
  bidId: string;
  documentId: string;
};
export type PendingDocumentParse = { key: string; body: StartDocumentParse };
export const documentParsePath = (scope: DocumentParseScope) =>
  `/bids/${scope.bidId}/documents/${scope.documentId}/parse-requests`;
export const documentParseContextPath = (scope: DocumentParseScope) =>
  `/bids/${scope.bidId}/documents/${scope.documentId}/parse-context`;
export const documentParseEnded = (state: string) =>
  ["succeeded", "failed", "cancelled"].includes(state);
export const documentParseStateLabels = {
  queued: "解析申请已受理，等待处理",
  running: "正在解析原件",
  cancel_requested: "已请求取消，等待最终状态",
  cancelled: "此次解析已取消",
  failed: "此次解析运行失败",
  succeeded: "此次解析运行结束",
} as const;
const bounded = (value: unknown, min: number, max: number) =>
  typeof value === "number" &&
  Number.isSafeInteger(value) &&
  value >= min &&
  value <= max;
const text = (value: unknown, max: number, empty = false): value is string =>
  typeof value === "string" &&
  (empty || !!value.length) &&
  Array.from(value).length <= max;
const time = (value: unknown): value is string =>
  typeof value === "string" &&
  /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)$/.test(
    value,
  ) &&
  Number.isFinite(Date.parse(value)) &&
  new Date(`${value.slice(0, 10)}T00:00:00Z`).toISOString().slice(0, 10) ===
    value.slice(0, 10);
function fail(): never {
  throw new Error(
    "解析记录的项目、原件、方法或回执身份无法核验，未采用其他解析；原请求仍需核对。",
  );
}
export function validDocumentParseReason(value: unknown): value is string {
  return (
    typeof value === "string" &&
    !!value.trim() &&
    Array.from(value).length <= 1000 &&
    Array.from(value).every((char) => {
      const point = char.codePointAt(0)!;
      return point > 31 && (point < 0xd800 || point > 0xdfff);
    })
  );
}
export function validPendingDocumentParse(
  value: unknown,
): value is PendingDocumentParse {
  return (
    recordObject(value) &&
    exactKeys(value, ["key", "body"]) &&
    executionId(value.key) &&
    recordObject(value.body) &&
    exactKeys(value.body, ["context_digest", "reason"]) &&
    executionSha(value.body.context_digest) &&
    validDocumentParseReason(value.body.reason)
  );
}
function contextShape(value: unknown, scope: DocumentParseScope) {
  if (
    !recordObject(value) ||
    !exactKeys(value, [
      "protocol",
      "bid_id",
      "document_version_id",
      "document",
      "qualification",
      "source",
      "method",
      "word_coverage_claimed",
      "current_body_changed",
      "automatically_started_review",
    ]) ||
    value.protocol !== "document-parse-context/1" ||
    value.bid_id !== scope.bidId ||
    value.document_version_id !== scope.documentId ||
    value.word_coverage_claimed !== false ||
    value.current_body_changed !== false ||
    value.automatically_started_review !== false ||
    !recordObject(value.document) ||
    !recordObject(value.qualification) ||
    !recordObject(value.source) ||
    !recordObject(value.method)
  )
    return false;
  const d = value.document,
    q = value.qualification,
    s = value.source,
    m = value.method;
  return (
    exactKeys(d, [
      "sha256",
      "byte_size",
      "media_type",
      "filename",
      "file_id",
      "file_revision",
      "role",
      "artifact_kind",
      "locator_digest",
    ]) &&
    executionSha(d.sha256) &&
    bounded(d.byte_size, 1, 104857600) &&
    d.media_type === "application/pdf" &&
    text(d.filename, 4096) &&
    executionId(d.file_id) &&
    bounded(d.file_revision, 1, Number.MAX_SAFE_INTEGER) &&
    ["body", "tender", "supplement", "drawing", "boq"].includes(
      String(d.role),
    ) &&
    ["source_original", "bid_body"].includes(String(d.artifact_kind)) &&
    executionSha(d.locator_digest) &&
    exactKeys(q, ["kind", "identity_digest"]) &&
    ["verified_upload", "adopted_generated"].includes(String(q.kind)) &&
    executionSha(q.identity_digest) &&
    exactKeys(s, ["root_id", "state", "authority_digest"]) &&
    executionId(s.root_id) &&
    ["unregistered", "published"].includes(String(s.state)) &&
    executionSha(s.authority_digest) &&
    exactKeys(m, [
      "protocol",
      "mode",
      "parser_digest",
      "config_digest",
      "implementation_digest",
      "max_bytes",
      "max_pages",
    ]) &&
    m.protocol === "document-parse-method/1" &&
    ["physical_text_only", "configured_local"].includes(String(m.mode)) &&
    [m.parser_digest, m.config_digest, m.implementation_digest].every(
      executionSha,
    ) &&
    m.max_bytes === 104857600 &&
    m.max_pages === 1000
  );
}
export async function validateDocumentParseContext(
  value: unknown,
  scope: DocumentParseScope,
): Promise<DocumentParseContext> {
  if (
    !recordObject(value) ||
    !exactKeys(value, ["context", "context_digest"]) ||
    !executionSha(value.context_digest) ||
    !contextShape(value.context, scope) ||
    (await frozenManifestDigest(value.context)) !== value.context_digest
  )
    return fail();
  return value as DocumentParseContext;
}
export async function validateDocumentParseView(
  value: unknown,
  scope: DocumentParseScope,
  expectedId?: string,
): Promise<DocumentParseView> {
  if (
    !recordObject(value) ||
    !exactKeys(value, [
      "protocol",
      "id",
      "bid_id",
      "document_version_id",
      "actor_id",
      "created_at",
      "context",
      "context_digest",
      "reason",
      "operation",
      "result",
      "current_body_changed",
      "automatically_started_review",
    ]) ||
    value.protocol !== "document-parse-request/1" ||
    ![value.id, value.actor_id].every(executionId) ||
    (expectedId !== undefined && value.id !== expectedId) ||
    value.bid_id !== scope.bidId ||
    value.document_version_id !== scope.documentId ||
    !time(value.created_at) ||
    !validDocumentParseReason(value.reason) ||
    value.current_body_changed !== false ||
    value.automatically_started_review !== false ||
    !recordObject(value.operation)
  )
    return fail();
  await validateDocumentParseContext(
    { context: value.context, context_digest: value.context_digest },
    scope,
  );
  const op = value.operation;
  if (
    !exactKeys(op, [
      "id",
      "kind",
      "state",
      "input_digest",
      "handler_version",
      "error_code",
      "created_at",
      "finished_at",
    ]) ||
    !executionId(op.id) ||
    op.kind !== "parse-document" ||
    op.handler_version !== "document-parse/1" ||
    !Object.hasOwn(documentParseStateLabels, String(op.state)) ||
    op.input_digest !== value.context_digest ||
    !time(op.created_at) ||
    !(op.error_code === null || typeof op.error_code === "string") ||
    (documentParseEnded(String(op.state))
      ? !time(op.finished_at)
      : op.finished_at !== null) ||
    (op.state === "succeeded") !== (value.result !== null)
  )
    return fail();
  const view = value as unknown as DocumentParseView,
    r = view.result;
  if (
    r !== null &&
    (!recordObject(r) ||
      !exactKeys(r, [
        "parse_run_id",
        "document_version_id",
        "source_digest",
        "parser_digest",
        "config_digest",
        "parsed_digest",
        "coverage",
        "page_count",
        "evidence_count",
        "gaps",
        "gap_count",
        "word_coverage_claimed",
      ]) ||
      !executionId(r.parse_run_id) ||
      r.document_version_id !== scope.documentId ||
      r.source_digest !== view.context.document.sha256 ||
      r.parser_digest !== view.context.method.parser_digest ||
      r.config_digest !== view.context.method.config_digest ||
      !executionSha(r.parsed_digest) ||
      !["complete", "partial", "failed"].includes(r.coverage) ||
      !bounded(r.page_count, 0, 1000) ||
      !bounded(r.evidence_count, 0, 100000) ||
      !bounded(r.gap_count, 0, 10000) ||
      !Array.isArray(r.gaps) ||
      r.gaps.length !== Math.min(r.gap_count, 100) ||
      !r.gaps.every((gap) => text(gap, 1000, true)) ||
      r.word_coverage_claimed !== false ||
      (r.coverage === "complete" &&
        (view.context.method.mode === "physical_text_only" ||
          r.page_count === 0 ||
          r.gap_count !== 0)))
  )
    return fail();
  return view;
}
export async function validateDocumentParseStarted(
  value: unknown,
  scope: DocumentParseScope,
  pending: PendingDocumentParse,
): Promise<DocumentParseStarted> {
  if (
    !validPendingDocumentParse(pending) ||
    !recordObject(value) ||
    !exactKeys(value, [
      "protocol",
      "actor_id",
      "command_id",
      "request_digest",
      "reused",
      "request",
    ]) ||
    value.protocol !== "document-parse-start/1" ||
    value.actor_id !== scope.memberId ||
    !executionId(value.command_id) ||
    typeof value.reused !== "boolean" ||
    (await frozenManifestDigest({
      body: { bid_id: scope.bidId, ...pending.body },
      if_match: null,
    })) !== value.request_digest
  )
    return fail();
  const request = await validateDocumentParseView(value.request, scope);
  if (
    request.context_digest !== pending.body.context_digest ||
    (!value.reused &&
      (request.actor_id !== scope.memberId ||
        request.reason !== pending.body.reason))
  )
    return fail();
  return value as DocumentParseStarted;
}
export async function validateDocumentParsePage(
  value: unknown,
  scope: DocumentParseScope,
  limit = 10,
): Promise<DocumentParsePage> {
  if (
    !recordObject(value) ||
    !exactKeys(value, [
      "bid_id",
      "document_version_id",
      "items",
      "has_more",
      "next_cursor",
    ]) ||
    value.bid_id !== scope.bidId ||
    value.document_version_id !== scope.documentId ||
    !Array.isArray(value.items) ||
    value.items.length > limit ||
    typeof value.has_more !== "boolean" ||
    (value.has_more
      ? !value.items.length || !text(value.next_cursor, 4096)
      : value.next_cursor !== null)
  )
    return fail();
  const items = await Promise.all(
    value.items.map((item) => validateDocumentParseView(item, scope)),
  );
  if (items.some((item, index) => index > 0 && items[index - 1].id >= item.id))
    return fail();
  return value as DocumentParsePage;
}
export function sameDocumentParseRequest(
  left: DocumentParseView,
  right: DocumentParseView,
) {
  return (
    [
      "id",
      "bid_id",
      "document_version_id",
      "actor_id",
      "created_at",
      "context_digest",
      "reason",
    ].every(
      (key) =>
        left[key as keyof DocumentParseView] ===
        right[key as keyof DocumentParseView],
    ) &&
    ["id", "kind", "input_digest", "handler_version", "created_at"].every(
      (key) =>
        left.operation[key as keyof DocumentParseView["operation"]] ===
        right.operation[key as keyof DocumentParseView["operation"]],
    )
  );
}
export async function assertDocumentParseUpdate(
  before: DocumentParseView,
  after: DocumentParseView,
) {
  if (
    !sameDocumentParseRequest(before, after) ||
    (documentParseEnded(before.operation.state) &&
      (before.operation.state !== after.operation.state ||
        before.operation.finished_at !== after.operation.finished_at)) ||
    (before.result !== null &&
      (await frozenManifestDigest(before.result)) !==
        (await frozenManifestDigest(after.result)))
  )
    throw new Error(
      "解析的原申请、已确认终态或结果发生变化，已保留原记录，请重新核对。",
    );
}
const rejectedCodes = new Set([
  "DOCUMENT_PARSE_ORIGINAL_NOT_FOUND",
  "DOCUMENT_PARSE_CONTEXT_CHANGED",
  "DOCUMENT_PARSE_INVALID",
  "DOCUMENT_PARSE_ORIGINAL_UNSUPPORTED",
  "DOCUMENT_PARSE_ORIGINAL_TOO_LARGE",
  "DOCUMENT_PARSE_GENERATED_UNPROVEN",
  "DOCUMENT_PARSE_ORIGINAL_UNPROVEN",
  "DOCUMENT_PARSE_SOURCE_INVALID",
  "DOCUMENT_PARSE_ACTOR_CHANGED",
  "PROJECT_WORK_CLOSED",
]);
/** An incomplete/conflicting command is not proof that the original work was rejected. */
export const definitelyRejectedDocumentParse = (error: unknown) =>
  error instanceof ApiError &&
  [404, 409, 413, 422].includes(error.status) &&
  rejectedCodes.has(error.code);
