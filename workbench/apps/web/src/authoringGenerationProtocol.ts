import type {
  AuthoringGenerationBatch,
  AuthoringGenerationBatchCandidate,
  AuthoringGenerationBatchCapabilities,
  AuthoringGenerationBatchPage,
  AuthoringGenerationBatchReceipt,
} from "./contracts";
import {
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
import { jsonDigest } from "./editorSchema";
import { readAuthoringContent } from "./richEditorSchema";
import {
  generationEtag,
  generationInteger as integer,
  generationText as text,
  validGenerationCreate,
  validGenerationResolve,
  validGenerationRetry,
} from "./authoringGenerationRecovery";
import type {
  GenerationScope,
  PendingGeneration,
} from "./authoringGenerationRecovery";
import {
  generationAmountScale,
  sumGenerationLimits,
} from "./authoringGenerationBudget";

export type GenerationSection = AuthoringGenerationBatch["sections"][number];
export type GenerationAttempt = GenerationSection["attempts"][number];
function fail(): never {
  throw new Error(
    "多章节编写响应的项目、草稿、预算、候选或回执身份无法核对。原请求保留，尚未确认操作成功。",
  );
}
function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (recordObject(value))
    return Object.fromEntries(
      Object.entries(value)
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([key, item]) => [key, canonical(item)]),
    );
  return value;
}
export const sameGenerationValue = (a: unknown, b: unknown) =>
  JSON.stringify(canonical(a)) === JSON.stringify(canonical(b));
/** The server hashes the exact scoped request, including the original strong precondition. */
export async function validateGenerationCommandDigest(
  value: AuthoringGenerationBatchReceipt["command"],
  scope: GenerationScope,
) {
  const digest = await jsonDigest({
    body: { bid_id: scope.bidId, draft_id: scope.draftId, ...value.request },
    if_match: value.if_match,
  });
  if (digest !== value.request_digest) fail();
}
const time = (value: unknown) =>
  typeof value === "string" &&
  value.length <= 100 &&
  Number.isFinite(Date.parse(value));
const nullableId = (value: unknown) => value === null || executionId(value);
const nullableSha = (value: unknown) => value === null || executionSha(value);
const arrayIds = (value: unknown, max = 20): value is string[] =>
  Array.isArray(value) &&
  value.length <= max &&
  new Set(value).size === value.length &&
  value.every(executionId);
const stableIds = (value: unknown, max = 2000): value is string[] =>
  Array.isArray(value) &&
  value.length <= max &&
  new Set(value).size === value.length &&
  value.every((item) => text(item, 128));
function blocked(value: unknown) {
  return (
    value === null ||
    (recordObject(value) && text(value.code, 200) && text(value.message, 10000))
  );
}
function price(value: unknown) {
  return (
    recordObject(value) &&
    executionId(value.price_version_id) &&
    text(value.version) &&
    text(value.provider) &&
    text(value.model) &&
    ["USD", "CNY"].includes(String(value.currency)) &&
    value.amount_scale === generationAmountScale &&
    integer(value.input_upper, 1) &&
    integer(value.output_upper, 1) &&
    integer(value.input_per_million_minor, 1) &&
    integer(value.output_per_million_minor, 1) &&
    time(value.valid_until) &&
    text(value.source_kind) &&
    text(value.source_uri, 10000) &&
    executionSha(value.source_sha256)
  );
}
function budget(value: unknown) {
  return (
    recordObject(value) &&
    ["USD", "CNY"].includes(String(value.currency)) &&
    value.amount_scale === generationAmountScale &&
    integer(value.limit_minor, 1) &&
    [
      "charged_minor",
      "reserved_minor",
      "exposure_minor",
      "remaining_minor",
    ].every((key) => integer(value[key])) &&
    typeof value.requires_reconciliation === "boolean" &&
    typeof value.over_limit === "boolean" &&
    value.estimate_not_provider_spend_cap === true
  );
}
function command(value: unknown) {
  return (
    recordObject(value) &&
    executionId(value.command_id) &&
    executionId(value.actor_id) &&
    text(value.idempotency_key, 128) &&
    executionSha(value.request_digest) &&
    (value.if_match === null || generationEtag(value.if_match)) &&
    (validGenerationCreate(value.request) ||
      validGenerationRetry(value.request) ||
      validGenerationResolve(value.request))
  );
}
function summary(value: unknown, scope: GenerationScope) {
  return (
    recordObject(value) &&
    executionId(value.batch_id) &&
    value.bid_id === scope.bidId &&
    value.draft_id === scope.draftId &&
    executionSha(value.batch_digest) &&
    integer(value.base_draft_revision, 1) &&
    ["open", "applied", "rejected"].includes(String(value.state)) &&
    time(value.created_at) &&
    executionId(value.created_by) &&
    integer(value.section_count, 1, 20) &&
    integer(value.ready_count, 0, Number(value.section_count)) &&
    integer(value.failed_count, 0, Number(value.section_count)) &&
    integer(value.running_count, 0, Number(value.section_count)) &&
    budget(value.budget)
  );
}
export function validateGenerationCapabilities(
  value: unknown,
): AuthoringGenerationBatchCapabilities {
  if (
    !recordObject(value) ||
    typeof value.enabled !== "boolean" ||
    !blocked(value.unavailable_reason) ||
    value.generation_mode !== "section_patch_set/1" ||
    !integer(value.max_sections, 1, 20) ||
    !integer(value.max_attempts_per_section, 1, 5) ||
    !integer(value.max_frozen_bytes, 1) ||
    !integer(value.max_instruction_chars, 1, 8000) ||
    !integer(value.max_limit_minor, 1) ||
    value.amount_scale !== generationAmountScale ||
    !integer(value.default_max_tokens, 1, 8192) ||
    (value.price !== null && !price(value.price)) ||
    (value.enabled && (!value.price || value.unavailable_reason !== null)) ||
    !Array.isArray(value.estimates) ||
    value.estimates.length > 10 ||
    !value.estimates.every(
      (item) =>
        recordObject(item) &&
        integer(item.max_tokens, 1, 8192) &&
        integer(item.reservation_minor, 1),
    ) ||
    value.requires_explicit_selection !== true ||
    value.atomic_apply !== true ||
    value.requires_verified_identity !== true ||
    value.automatic_retry_authorized !== false
  )
    fail();
  return value as AuthoringGenerationBatchCapabilities;
}
export function validateGenerationPage(
  value: unknown,
  scope: GenerationScope,
): AuthoringGenerationBatchPage {
  if (
    !recordObject(value) ||
    value.bid_id !== scope.bidId ||
    value.draft_id !== scope.draftId ||
    !Array.isArray(value.items) ||
    value.items.length > 50 ||
    !value.items.every((item) => summary(item, scope)) ||
    new Set(value.items.map((item) => (item as { batch_id: string }).batch_id))
      .size !== value.items.length ||
    typeof value.has_more !== "boolean" ||
    (value.has_more
      ? !executionId(value.next_cursor)
      : value.next_cursor !== null)
  )
    fail();
  return value as AuthoringGenerationBatchPage;
}
export function currentGenerationAttempt(section: GenerationSection) {
  return section.attempts.find(
    (attempt) => attempt.attempt === section.current_attempt,
  )!;
}
export function terminalGenerationAttempt(attempt: GenerationAttempt) {
  return ["succeeded", "failed", "cancelled"].includes(attempt.state);
}
export function publishedGenerationAttempt(attempt: GenerationAttempt) {
  return (
    attempt.state === "succeeded" &&
    attempt.publication_state === "published" &&
    !!attempt.action_id &&
    !!attempt.candidate_digest
  );
}
export function validateGenerationBatch(
  value: unknown,
  scope: GenerationScope,
  expectedId?: string,
): AuthoringGenerationBatch {
  if (!summary(value, scope) || !recordObject(value)) fail();
  const batch = value as unknown as AuthoringGenerationBatch;
  if (
    (expectedId && batch.batch_id !== expectedId) ||
    batch.protocol !== "authoring-generation-batch/1" ||
    batch.generation_mode !== "section_patch_set/1" ||
    !executionId(batch.base_snapshot_id) ||
    !executionSha(batch.base_snapshot_digest) ||
    !generationEtag(batch.base_draft_etag) ||
    !generationEtag(batch.etag) ||
    !price(batch.price) ||
    !text(batch.reason) ||
    !Array.isArray(batch.sections) ||
    batch.sections.length !== batch.section_count ||
    !command(batch.preparation) ||
    !validGenerationCreate(batch.preparation.request) ||
    batch.preparation.actor_id !== batch.created_by ||
    batch.preparation.if_match !== batch.base_draft_etag ||
    batch.current_validity !== "rechecked_on_retry_and_apply" ||
    batch.requires_explicit_selection !== true ||
    batch.atomic_apply !== true ||
    (batch.state !== "open") !== (batch.resolution !== null)
  )
    fail();
  const request = batch.preparation.request;
  if (
    request.base_draft_revision !== batch.base_draft_revision ||
    request.price_version_id !== batch.price.price_version_id ||
    request.currency !== batch.price.currency ||
    request.currency !== batch.budget.currency ||
    request.total_limit_minor !== batch.budget.limit_minor ||
    request.reason !== batch.reason ||
    request.sections.length !== batch.sections.length
  )
    fail();
  const seen = new Set<string>();
  const jobs = new Set<string>();
  for (const section of batch.sections) {
    const original = request.sections.find(
      (item) => item.section_id === section.section_id,
    );
    if (
      !original ||
      seen.has(section.section_id) ||
      !text(section.title, 200) ||
      !integer(section.ordinal) ||
      !executionSha(section.before_digest) ||
      !integer(section.current_attempt, 1, 5) ||
      !budget(section.budget) ||
      section.budget.currency !== batch.price.currency ||
      section.budget.limit_minor !== section.budget_limit_minor ||
      !Array.isArray(section.attempts) ||
      section.attempts.length !== section.current_attempt ||
      !sameGenerationValue(
        original,
        Object.fromEntries(
          Object.keys(original).map((key) => [
            key,
            section[key as keyof GenerationSection],
          ]),
        ),
      )
    )
      fail();
    seen.add(section.section_id);
    for (let index = 0; index < section.attempts.length; index++) {
      const attempt = section.attempts[index];
      if (
        !recordObject(attempt) ||
        attempt.attempt !== index + 1 ||
        !executionId(attempt.job_id) ||
        jobs.has(attempt.job_id) ||
        !executionId(attempt.operation_id) ||
        !executionId(attempt.writing_plan_id) ||
        !time(attempt.created_at) ||
        !executionId(attempt.created_by) ||
        ![
          "queued",
          "running",
          "cancel_requested",
          "succeeded",
          "failed",
          "cancelled",
        ].includes(attempt.state) ||
        !["pending", "published", "stale", "failed"].includes(
          attempt.publication_state,
        ) ||
        !nullableId(attempt.action_id) ||
        !nullableSha(attempt.candidate_digest) ||
        (attempt.candidate_url !== null &&
          !text(attempt.candidate_url, 2048)) ||
        (attempt.error_code !== null && !text(attempt.error_code, 200)) ||
        !["held", "sent", "unknown", "settled", "released"].includes(
          attempt.budget_state,
        ) ||
        !integer(attempt.reserved_minor, 1) ||
        (attempt.charged_minor !== null && !integer(attempt.charged_minor)) ||
        typeof attempt.requires_reconciliation !== "boolean" ||
        typeof attempt.retry_allowed !== "boolean" ||
        !blocked(attempt.retry_blocked_reason) ||
        (attempt.publication_state === "published" &&
          (!attempt.action_id ||
            !attempt.candidate_digest ||
            !attempt.candidate_url)) ||
        (attempt.retry_allowed &&
          (!terminalGenerationAttempt(attempt) ||
            publishedGenerationAttempt(attempt) ||
            attempt.requires_reconciliation ||
            !["released", "settled"].includes(attempt.budget_state) ||
            attempt.retry_blocked_reason !== null))
      )
        fail();
      jobs.add(attempt.job_id);
    }
  }
  const limits = sumGenerationLimits(
    batch.sections.map((section) => section.budget_limit_minor),
  );
  if (limits === null || limits > batch.budget.limit_minor) fail();
  if (batch.resolution) {
    validateGenerationReceipt(batch.resolution, scope, undefined, batch);
    if (batch.resolution.batch_state !== batch.state) fail();
  }
  return batch;
}

export function validateGenerationReceipt(
  value: unknown,
  scope: GenerationScope,
  pending?: PendingGeneration,
  batch?: AuthoringGenerationBatch,
): AuthoringGenerationBatchReceipt {
  if (
    !recordObject(value) ||
    value.protocol !== "authoring-generation-batch-command/1" ||
    value.bid_id !== scope.bidId ||
    value.draft_id !== scope.draftId ||
    !executionId(value.batch_id) ||
    !executionSha(value.batch_digest) ||
    !["created", "retried", "applied", "rejected"].includes(
      String(value.kind),
    ) ||
    !["open", "applied", "rejected"].includes(String(value.batch_state)) ||
    !arrayIds(value.created_job_ids) ||
    !arrayIds(value.applied_section_ids) ||
    !arrayIds(value.unselected_section_ids) ||
    !time(value.recorded_at) ||
    !command(value.command)
  )
    fail();
  const result = value as AuthoringGenerationBatchReceipt;
  if (
    pending &&
    (result.command.actor_id !== scope.memberId ||
      result.command.idempotency_key !== pending.key ||
      result.command.if_match !== pending.etag ||
      !sameGenerationValue(result.command.request, pending.body) ||
      (pending.kind !== "create" &&
        (result.batch_id !== pending.batchId ||
          result.batch_digest !== pending.body.batch_digest)))
  )
    fail();
  if (
    batch &&
    (result.batch_id !== batch.batch_id ||
      result.batch_digest !== batch.batch_digest)
  )
    fail();
  const body = result.command.request;
  if (result.kind === "created") {
    if (
      !validGenerationCreate(body) ||
      result.batch_state !== "open" ||
      result.created_job_ids.length !== body.sections.length ||
      result.applied_section_ids.length
    )
      fail();
  } else if (result.kind === "retried") {
    if (
      !validGenerationRetry(body) ||
      result.batch_state !== "open" ||
      result.created_job_ids.length !== 1 ||
      result.applied_section_ids.length
    )
      fail();
  } else {
    if (
      !validGenerationResolve(body) ||
      body.batch_digest !== result.batch_digest ||
      result.kind !== (body.decision === "apply" ? "applied" : "rejected") ||
      result.batch_state !== result.kind ||
      result.created_job_ids.length
    )
      fail();
    const selected = body.selections.map((item) => item.section_id).sort();
    if (!sameGenerationValue([...result.applied_section_ids].sort(), selected))
      fail();
    if (
      batch &&
      !sameGenerationValue(
        [...result.unselected_section_ids].sort(),
        batch.sections
          .map((section) => section.section_id)
          .filter((id) => !selected.includes(id))
          .sort(),
      )
    )
      fail();
  }
  if (
    pending &&
    result.kind !==
      (pending.kind === "create"
        ? "created"
        : pending.kind === "retry"
          ? "retried"
          : pending.body.decision === "apply"
            ? "applied"
            : "rejected")
  )
    fail();
  if (result.kind === "applied") {
    const base = pending?.baseDraftRevision ?? batch?.base_draft_revision;
    if (
      !integer(result.draft_revision, 1) ||
      (base !== undefined && result.draft_revision !== base + 1) ||
      !executionId(result.snapshot_id) ||
      !executionSha(result.snapshot_digest)
    )
      fail();
  } else if (
    result.draft_revision !== null ||
    result.snapshot_id !== null ||
    result.snapshot_digest !== null
  )
    fail();
  return result;
}

export async function validateGenerationCandidate(
  value: unknown,
  scope: GenerationScope,
  batch: AuthoringGenerationBatch,
  section: GenerationSection,
  attempt: GenerationAttempt,
): Promise<AuthoringGenerationBatchCandidate> {
  if (
    !recordObject(value) ||
    value.protocol !== "authoring-generation-candidate/1" ||
    value.generation_mode !== "section_patch_set/1" ||
    value.bid_id !== scope.bidId ||
    value.draft_id !== scope.draftId ||
    value.batch_id !== batch.batch_id ||
    value.batch_digest !== batch.batch_digest ||
    value.section_id !== section.section_id ||
    value.attempt !== attempt.attempt ||
    value.job_id !== attempt.job_id ||
    value.writing_plan_id !== attempt.writing_plan_id ||
    value.action_id !== attempt.action_id ||
    value.candidate_digest !== attempt.candidate_digest ||
    value.base_draft_revision !== batch.base_draft_revision ||
    value.base_section_revision !== section.base_section_revision ||
    value.base_draft_etag !== batch.base_draft_etag ||
    value.before_digest !== section.before_digest ||
    !executionSha(value.after_digest) ||
    !executionSha(value.scope_digest) ||
    !time(value.created_at) ||
    !time(value.expires_at) ||
    !["pending", "executed", "rejected", "expired", "stale", "failed"].includes(
      String(value.state),
    ) ||
    !generationEtag(value.etag) ||
    !recordObject(value.changes) ||
    !stableIds(value.changes.replaced_node_ids) ||
    !integer(value.changes.added_paragraphs) ||
    !Array.isArray(value.changes.insertions) ||
    value.changes.insertions.length > 2000
  )
    fail();
  const candidate = value as AuthoringGenerationBatchCandidate;
  const before = readAuthoringContent(candidate.before, true),
    after = readAuthoringContent(candidate.after, true);
  if (
    (await jsonDigest(candidate.before)) !== candidate.before_digest ||
    (await jsonDigest(candidate.after)) !== candidate.after_digest
  )
    fail();
  const beforeNodes = new Map<string, ReturnType<typeof before.nodeAt>>();
  const afterNodes = new Map<string, ReturnType<typeof before.nodeAt>>();
  before.descendants((node) => {
    if (node.attrs.id) beforeNodes.set(String(node.attrs.id), node);
  });
  after.descendants((node) => {
    if (node.attrs.id) afterNodes.set(String(node.attrs.id), node);
  });
  const replacements = new Set(candidate.changes.replaced_node_ids),
    inserted = new Set<string>();
  for (const identity of replacements) {
    const original = beforeNodes.get(identity),
      replacement = afterNodes.get(identity);
    if (
      !original ||
      !replacement ||
      !["paragraph", "heading"].includes(original.type.name) ||
      replacement.type.name !== original.type.name ||
      !sameGenerationValue(original.attrs, replacement.attrs) ||
      (section.selected_node_ids !== null &&
        !section.selected_node_ids.includes(identity))
    )
      fail();
  }
  const anchors = new Set<string>();
  before.forEach((node) => {
    if (node.attrs.id) anchors.add(String(node.attrs.id));
  });
  for (const insertion of candidate.changes.insertions) {
    if (
      !recordObject(insertion) ||
      (insertion.after_node_id !== null &&
        (!text(insertion.after_node_id, 128) ||
          !anchors.has(insertion.after_node_id))) ||
      !arrayIds(insertion.node_ids, 1000)
    )
      fail();
    for (const identity of insertion.node_ids) {
      if (
        inserted.has(identity) ||
        beforeNodes.has(identity) ||
        afterNodes.get(identity)?.type.name !== "paragraph"
      )
        fail();
      inserted.add(identity);
    }
  }
  if (inserted.size !== candidate.changes.added_paragraphs) fail();
  for (const [identity, node] of beforeNodes) {
    const next = afterNodes.get(identity);
    if (!node || !next || next.type.name !== node.type.name) fail();
    if (
      ["paragraph", "heading", "image", "table"].includes(node.type.name) &&
      !replacements.has(identity) &&
      !sameGenerationValue(node.toJSON(), next.toJSON())
    )
      fail();
  }
  for (const identity of afterNodes.keys())
    if (!beforeNodes.has(identity) && !inserted.has(identity)) fail();
  for (const key of ["title", "ordinal", "rule_ids"])
    if (!sameGenerationValue(before.attrs[key], after.attrs[key])) fail();
  return candidate;
}
