import { ApiError } from "./api";
import type {
  AuthoringGenerationBatchCreateRequest,
  AuthoringGenerationBatchResolveRequest,
  AuthoringGenerationBatchRetryRequest,
} from "./contracts";
import { authoringStorageKey } from "./editorStorage";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
import {
  generationAmountScale,
  sumGenerationLimits,
} from "./authoringGenerationBudget";

export type GenerationScope = {
  memberId: string;
  bidId: string;
  draftId: string;
};
type PendingBase = { key: string; etag: string; baseDraftRevision: number };
export type PendingGeneration = PendingBase &
  (
    | { kind: "create"; body: AuthoringGenerationBatchCreateRequest }
    | {
        kind: "retry";
        batchId: string;
        body: AuthoringGenerationBatchRetryRequest;
      }
    | {
        kind: "resolve";
        batchId: string;
        body: AuthoringGenerationBatchResolveRequest;
      }
  );
export type GenerationRecovery = {
  version: 1;
  scope: GenerationScope;
  pending: PendingGeneration | null;
  lastBatchId: string | null;
};
export const generationPath = (scope: GenerationScope) =>
  `/bids/${scope.bidId}/drafts/${scope.draftId}/generation-batches`;
export const generationStorageKey = (scope: GenerationScope) =>
  authoringStorageKey(
    scope.memberId,
    scope.bidId,
    `${scope.draftId}:generation-batch`,
  );
export const generationInteger = (
  value: unknown,
  min = 0,
  max = Number.MAX_SAFE_INTEGER,
): value is number =>
  Number.isSafeInteger(value) && Number(value) >= min && Number(value) <= max;
export const generationText = (value: unknown, max = 1000): value is string =>
  typeof value === "string" &&
  !!value.trim() &&
  Array.from(value).length <= max &&
  Array.from(value).every((character) => {
    const point = character.codePointAt(0)!;
    return (
      (point >= 32 || point === 9 || point === 10 || point === 13) &&
      (point < 0xd800 || point > 0xdfff)
    );
  });
export const generationEtag = (value: unknown): value is string =>
  typeof value === "string" &&
  value.length <= 512 &&
  /^"[^"\r\n]+"$/.test(value);
function ids(
  value: unknown,
  min: number,
  max: number,
  stable = false,
): value is string[] {
  return (
    Array.isArray(value) &&
    value.length >= min &&
    value.length <= max &&
    new Set(value).size === value.length &&
    value.every(stable ? (item) => generationText(item, 128) : executionId)
  );
}
export function validGenerationCreate(
  value: unknown,
): value is AuthoringGenerationBatchCreateRequest {
  if (
    !recordObject(value) ||
    !exactKeys(value, [
      "base_draft_revision",
      "price_version_id",
      "currency",
      "amount_scale",
      "total_limit_minor",
      "sections",
      "reason",
    ]) ||
    !generationInteger(value.base_draft_revision, 1) ||
    !executionId(value.price_version_id) ||
    !["USD", "CNY"].includes(String(value.currency)) ||
    value.amount_scale !== generationAmountScale ||
    !generationInteger(value.total_limit_minor, 1) ||
    !generationText(value.reason) ||
    !Array.isArray(value.sections) ||
    value.sections.length < 1 ||
    value.sections.length > 20
  )
    return false;
  const selected = new Set<string>();
  const limits: number[] = [];
  for (const section of value.sections) {
    if (
      !recordObject(section) ||
      !exactKeys(section, [
        "section_id",
        "base_section_revision",
        "instruction",
        "source_version_ids",
        "selected_node_ids",
        "max_tokens",
        "budget_limit_minor",
      ]) ||
      !executionId(section.section_id) ||
      selected.has(section.section_id) ||
      !generationInteger(section.base_section_revision, 1) ||
      !generationText(section.instruction, 8000) ||
      !ids(section.source_version_ids, 0, 30) ||
      (section.selected_node_ids !== null &&
        !ids(section.selected_node_ids, 1, 2000, true)) ||
      !generationInteger(section.max_tokens, 1, 8192) ||
      !generationInteger(section.budget_limit_minor, 1)
    )
      return false;
    selected.add(section.section_id);
    limits.push(section.budget_limit_minor);
  }
  const total = sumGenerationLimits(limits);
  return total !== null && total <= value.total_limit_minor;
}
export function validGenerationRetry(
  value: unknown,
): value is AuthoringGenerationBatchRetryRequest {
  return (
    recordObject(value) &&
    exactKeys(value, [
      "batch_digest",
      "section_id",
      "previous_attempt",
      "previous_job_id",
      "reason",
    ]) &&
    executionSha(value.batch_digest) &&
    executionId(value.section_id) &&
    generationInteger(value.previous_attempt, 1, 5) &&
    executionId(value.previous_job_id) &&
    generationText(value.reason)
  );
}
export function validGenerationResolve(
  value: unknown,
): value is AuthoringGenerationBatchResolveRequest {
  if (
    !recordObject(value) ||
    !exactKeys(value, ["decision", "batch_digest", "selections", "reason"]) ||
    !["apply", "reject"].includes(String(value.decision)) ||
    !executionSha(value.batch_digest) ||
    !generationText(value.reason) ||
    !Array.isArray(value.selections) ||
    value.selections.length > 20 ||
    (value.decision === "apply"
      ? value.selections.length === 0
      : value.selections.length !== 0)
  )
    return false;
  const sections = new Set<string>();
  return value.selections.every((item) => {
    if (
      !recordObject(item) ||
      !exactKeys(item, [
        "section_id",
        "attempt",
        "job_id",
        "action_id",
        "candidate_digest",
      ]) ||
      !executionId(item.section_id) ||
      sections.has(item.section_id) ||
      !generationInteger(item.attempt, 1, 5) ||
      !executionId(item.job_id) ||
      !executionId(item.action_id) ||
      !executionSha(item.candidate_digest)
    )
      return false;
    sections.add(item.section_id);
    return true;
  });
}
function validPending(value: unknown): value is PendingGeneration {
  if (
    !recordObject(value) ||
    !executionId(value.key) ||
    !generationEtag(value.etag) ||
    !generationInteger(value.baseDraftRevision, 1)
  )
    return false;
  if (value.kind === "create")
    return (
      exactKeys(value, ["kind", "key", "etag", "baseDraftRevision", "body"]) &&
      validGenerationCreate(value.body) &&
      value.body.base_draft_revision === value.baseDraftRevision
    );
  return (
    exactKeys(value, [
      "kind",
      "key",
      "etag",
      "baseDraftRevision",
      "batchId",
      "body",
    ]) &&
    executionId(value.batchId) &&
    (value.kind === "retry"
      ? validGenerationRetry(value.body)
      : value.kind === "resolve" && validGenerationResolve(value.body))
  );
}
export function readGenerationRecovery(
  scope: GenerationScope,
): GenerationRecovery {
  try {
    const raw = sessionStorage.getItem(generationStorageKey(scope));
    if (raw === null)
      return { version: 1, scope, pending: null, lastBatchId: null };
    const value: unknown = JSON.parse(raw);
    if (
      !recordObject(value) ||
      !exactKeys(value, ["version", "scope", "pending", "lastBatchId"]) ||
      value.version !== 1 ||
      !recordObject(value.scope) ||
      !exactKeys(value.scope, ["memberId", "bidId", "draftId"]) ||
      Object.entries(scope).some(
        ([key, item]) => (value.scope as Record<string, unknown>)[key] !== item,
      ) ||
      (value.pending !== null && !validPending(value.pending)) ||
      (value.lastBatchId !== null && !executionId(value.lastBatchId))
    )
      throw new Error("Invalid generation recovery");
    return value as GenerationRecovery;
  } catch {
    throw new Error(
      "多章节编写恢复记录无法核验，新的付费请求已暂停。请保留原记录并读取服务器批次历史核对。",
    );
  }
}
export function storeGenerationRecovery(value: GenerationRecovery) {
  try {
    sessionStorage.setItem(
      generationStorageKey(value.scope),
      JSON.stringify(value),
    );
  } catch {
    throw new Error(
      "浏览器未能保存批次恢复记录。请保留页面并释放此站点存储空间；未确认请求可能已受理，不能另建付费请求。",
    );
  }
}
/** Generic auth, routing and 409 failures do not prove a previous paid attempt was unaccepted. */
export function definitiveGenerationFailure(error: unknown) {
  const rejected = [
    "CHANGED",
    "RESOLVED",
    "CONTEXT_CHANGED",
    "SOURCE_CHANGED",
    "PRICE_CHANGED",
    "JOB_REUSED",
    "SECTION_UNAVAILABLE",
    "ATTEMPT_CHANGED",
    "RUNNING",
    "RECONCILIATION_REQUIRED",
    "NOT_FAILED",
    "ATTEMPT_LIMIT",
    "BUDGET_INSUFFICIENT",
    "INDEPENDENCE_UNPROVEN",
    "CANDIDATE_CHANGED",
    "CANDIDATE_CONSUMED",
    "CANDIDATE_EXPIRED",
    "OUTPUT_UNVERIFIED",
    "INVALID",
    "SELECTION_INVALID",
    "SECTION_DUPLICATE",
    "BUDGET_INVALID",
    "OUTPUT_LIMIT",
    "TOO_LARGE",
  ].map((code) => `AUTHORING_GENERATION_BATCH_${code}`);
  return (
    error instanceof ApiError &&
    !error.retryable &&
    [400, 409, 412, 413, 422].includes(error.status) &&
    ![
      "IDEMPOTENCY_CONFLICT",
      "COMMAND_INCOMPLETE",
      "SERVICE_VERSION_NOT_READY",
      "SCOPE_MISMATCH",
    ].includes(error.code) &&
    (error.status === 412 || rejected.includes(error.code))
  );
}
