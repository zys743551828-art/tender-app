import { ApiError } from "./api";
import type {
  Bid,
  PackageReviewSelection,
  RunView,
  TemplateRequest,
  TemplateView,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  exactKeys,
  executionId as uuid,
  executionSha as sha,
  recordObject as object,
} from "./executionInputValidation";
import {
  historicalDateTime,
  historicalSame as same,
} from "./historicalImportProtocol";

export type TaskPackageKind = "template" | "run";
export type TaskPackageScope<K extends TaskPackageKind = TaskPackageKind> = {
  kind: K;
  memberId: string;
  bidId: string;
  identity: string;
};
export type TaskPackageConfiguration = TemplateRequest & {
  task_kind: "denial_check";
  section_id: null;
  source_selection: {
    mode: "exact_package_review";
    input: PackageReviewSelection;
  };
  trigger: { mode: "manual"; cron: null; timezone: string };
};
export type TaskPackageTemplateView = TemplateView & {
  purpose: "compliance";
  configuration: TaskPackageConfiguration;
  next_run_at: null;
};
export type TaskPackageTemplateExpected = {
  kind: "template";
  request: TemplateRequest;
  previous: TemplateView | null;
};
export type TaskPackageRunExpected = { kind: "run"; template: TemplateView };
export type TaskPackageCommandRequest = {
  path: string;
  method: "POST" | "PUT";
  body: TemplateRequest | { rerun: false };
  etag: string;
  expected: TaskPackageTemplateExpected | TaskPackageRunExpected;
};
export type PendingTaskPackageCommand = TaskPackageCommandRequest & {
  key: string;
};

export type TaskPackageContext = {
  subject: {
    kind: "bid_package";
    bid_id: string;
    package_id: string;
    revision_id: string;
    inventory_id: string;
  };
  selection: PackageReviewSelection;
  review_input_digest: string;
  model_input_digest: string;
  limitations: string[];
  overall_coverage: "partial";
  formal_scoring_eligible: false;
  submission_eligible: false;
};
export type TaskPackageManifest = {
  schema: "task-package-run/1";
  definition_id: string;
  definition_version_id: string;
  configuration_digest: string;
  configuration: TaskPackageConfiguration;
  task_kind: "denial_check";
  purpose: "compliance";
  actor_id: string;
  request_id: string;
  context: TaskPackageContext;
  input_digest: string;
  fee_scope: string;
  trigger: "manual";
  trigger_event_id: null;
  scheduled_at: null;
  accepted_at: string;
  formal_decisions_allowed: false;
  package_review: {
    run_id: string;
    operation_id: string;
    start_command_id: string;
    input_digest: string;
    method_digest: string;
    run_ref: string;
  };
};
export type TaskPackageResult = {
  kind: "declared_package_scope_review";
  run_id: string;
  run_ref: string;
  input_digest: string;
  result_digest: string;
  overall_coverage: "partial";
  formal_scoring_eligible: false;
  submission_eligible: false;
};
export type TaskPackageRunView = Omit<
  RunView,
  "frozen_manifest" | "result" | "stage" | "coverage"
> & {
  stage: "review";
  coverage: "not_formal_score";
  frozen_manifest: TaskPackageManifest;
  result: TaskPackageResult | null;
};

const selectionIds = [
  "package_id",
  "revision_id",
  "inventory_id",
  "frozen_input_id",
  "execution_input_id",
  "dependency_plan_id",
] as const;
const selectionDigests = [
  "frozen_input_digest",
  "execution_input_digest",
  "dependency_plan_digest",
  "method_digest",
] as const;
const configurationKeys = [
  "name",
  "task_kind",
  "instructions",
  "section_id",
  "source_selection",
  "trigger",
];
const templateKeys = [
  "id",
  "bid_id",
  "revision",
  "version_id",
  "digest",
  "purpose",
  "paused",
  "configuration",
  "next_run_at",
  "run_created",
  "active_runs_cancelled",
];
const manifestKeys = [
  "schema",
  "definition_id",
  "definition_version_id",
  "configuration_digest",
  "configuration",
  "task_kind",
  "purpose",
  "actor_id",
  "request_id",
  "context",
  "input_digest",
  "fee_scope",
  "trigger",
  "trigger_event_id",
  "scheduled_at",
  "accepted_at",
  "formal_decisions_allowed",
  "package_review",
];
const runKeys = [
  "id",
  "bid_id",
  "definition_version_id",
  "root_operation_id",
  "final_operation_id",
  "state",
  "stage",
  "frozen_manifest",
  "result",
  "error_code",
  "formal_decisions_created",
  "coverage",
];
const nativeStates = [
  "queued",
  "running",
  "cancel_requested",
  "succeeded",
  "failed",
  "cancelled",
  "reconciliation_required",
];
const limitation = "INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED";

function fail(
  message = "整包任务的身份、原输入、摘要或回执边界不符，未确认操作成功；原请求仍保留。",
): never {
  throw new Error(message);
}
function text(value: unknown, maximum: number): value is string {
  return (
    typeof value === "string" &&
    /\S/u.test(value) &&
    Array.from(value).length <= maximum &&
    !/[\uD800-\uDFFF]/u.test(value)
  );
}
function integer(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 1;
}
function timezone(value: unknown): value is string {
  if (typeof value !== "string" || value.length > 100) return false;
  try {
    new Intl.DateTimeFormat("en", { timeZone: value });
    return true;
  } catch {
    return false;
  }
}
function timestamp(value: unknown) {
  try {
    historicalDateTime(value);
    return true;
  } catch {
    return false;
  }
}
export function isTaskPackageSelection(
  value: unknown,
): value is PackageReviewSelection {
  return (
    object(value) &&
    exactKeys(value, [...selectionIds, ...selectionDigests]) &&
    selectionIds.every((key) => uuid(value[key])) &&
    selectionDigests.every((key) => sha(value[key]))
  );
}

/** Explicit exact mode is mandatory. Only the server's ordinary optional defaults are filled. */
export function normalizeTaskPackageRequest(
  value: unknown,
): TaskPackageConfiguration {
  if (
    !object(value) ||
    Object.keys(value).some((key) => !configurationKeys.includes(key)) ||
    !text(value.name, 200) ||
    !text(value.instructions, 8000) ||
    value.task_kind !== "denial_check" ||
    (value.section_id !== undefined && value.section_id !== null)
  )
    fail();
  const source = value.source_selection;
  if (
    !object(source) ||
    !exactKeys(source, ["mode", "input"]) ||
    source.mode !== "exact_package_review" ||
    !isTaskPackageSelection(source.input)
  )
    fail();
  const trigger = value.trigger === undefined ? {} : value.trigger;
  if (
    !object(trigger) ||
    Object.keys(trigger).some(
      (key) => !["mode", "cron", "timezone"].includes(key),
    ) ||
    (trigger.mode !== undefined && trigger.mode !== "manual") ||
    (trigger.cron !== undefined && trigger.cron !== null) ||
    !timezone(
      trigger.timezone === undefined ? "Asia/Shanghai" : trigger.timezone,
    )
  )
    fail();
  return {
    name: value.name,
    task_kind: "denial_check",
    instructions: value.instructions,
    section_id: null,
    source_selection: {
      mode: "exact_package_review",
      input: { ...source.input },
    },
    trigger: {
      mode: "manual",
      cron: null,
      timezone: (trigger.timezone ?? "Asia/Shanghai") as string,
    },
  };
}
export const taskPackageTemplateEtag = (id: string, revision: number) =>
  `"task-template:${id}:${revision}"`;
export function isTaskPackageCreationIdentity(identity: string) {
  const parts = identity.split(":");
  return (
    identity === "new" ||
    (parts.length === 3 && parts[0] === "package" && parts.slice(1).every(uuid))
  );
}
export function assertTaskPackageScope(scope: TaskPackageScope) {
  if (
    !object(scope) ||
    !exactKeys(scope, ["kind", "memberId", "bidId", "identity"]) ||
    !uuid(scope.memberId) ||
    !uuid(scope.bidId) ||
    !["template", "run"].includes(scope.kind) ||
    typeof scope.identity !== "string" ||
    !(
      uuid(scope.identity) ||
      (scope.kind === "template" &&
        isTaskPackageCreationIdentity(scope.identity))
    )
  )
    fail("整包任务恢复范围无效，未发送请求。");
}
function templateShape(
  value: unknown,
  bidId: string,
  definitionId?: string,
): TaskPackageTemplateView {
  if (
    !object(value) ||
    !exactKeys(value, templateKeys) ||
    !uuid(value.id) ||
    value.bid_id !== bidId ||
    !uuid(bidId) ||
    (definitionId !== undefined && value.id !== definitionId) ||
    !uuid(value.version_id) ||
    !integer(value.revision) ||
    !sha(value.digest) ||
    value.purpose !== "compliance" ||
    typeof value.paused !== "boolean" ||
    value.next_run_at !== null ||
    value.run_created !== false ||
    value.active_runs_cancelled !== false
  )
    fail();
  const configuration = normalizeTaskPackageRequest(value.configuration);
  if (!same(configuration, value.configuration)) fail();
  return value as unknown as TaskPackageTemplateView;
}
async function templateDigest(
  configuration: TaskPackageConfiguration,
  paused: boolean,
) {
  return jsonDigest({
    schema: "task-template/1",
    definition: configuration,
    paused,
    formal_decisions_allowed: false,
  });
}
export async function validateTaskPackageTemplate(
  value: unknown,
  etag: string | null,
  bidId: string,
  definitionId?: string,
): Promise<TaskPackageTemplateView> {
  const item = templateShape(value, bidId, definitionId);
  if (
    etag !== taskPackageTemplateEtag(item.id, item.revision) ||
    item.digest !== (await templateDigest(item.configuration, item.paused))
  )
    fail();
  return item;
}

/** Structural validation runs before storage or transport; persisted expectations are never replaced by current UI props. */
export function validateTaskPackagePending(
  value: unknown,
  scope: TaskPackageScope,
): PendingTaskPackageCommand {
  assertTaskPackageScope(scope);
  if (
    !object(value) ||
    !exactKeys(value, ["path", "method", "body", "etag", "expected", "key"]) ||
    !uuid(value.key) ||
    typeof value.etag !== "string" ||
    !object(value.expected)
  )
    fail();
  const expected = value.expected;
  const base = `/bids/${scope.bidId}/task-definitions`;
  if (expected.kind !== scope.kind) fail();
  if (expected.kind === "template") {
    if (
      !exactKeys(expected, ["kind", "request", "previous"]) ||
      !same(value.body, expected.request)
    )
      fail();
    const configuration = normalizeTaskPackageRequest(expected.request);
    if (expected.previous === null) {
      if (
        !isTaskPackageCreationIdentity(scope.identity) ||
        value.path !== base ||
        value.method !== "POST" ||
        !new RegExp(`^"bid:${scope.bidId}:[0-9a-f]{64}"$`).test(value.etag)
      )
        fail();
      if (
        scope.identity !== "new" &&
        scope.identity !==
          `package:${configuration.source_selection.input.execution_input_id}:${configuration.source_selection.input.dependency_plan_id}`
      )
        fail();
    } else {
      const previous = templateShape(
        expected.previous,
        scope.bidId,
        scope.identity,
      );
      if (
        !uuid(scope.identity) ||
        value.path !== `${base}/${previous.id}` ||
        value.method !== "PUT" ||
        value.etag !== taskPackageTemplateEtag(previous.id, previous.revision)
      )
        fail();
    }
  } else if (expected.kind === "run") {
    if (
      !exactKeys(expected, ["kind", "template"]) ||
      !object(value.body) ||
      !exactKeys(value.body, ["rerun"]) ||
      value.body.rerun !== false
    )
      fail();
    const template = templateShape(
      expected.template,
      scope.bidId,
      scope.identity,
    );
    if (
      !uuid(scope.identity) ||
      template.paused ||
      value.path !== `${base}/${template.id}/runs` ||
      value.method !== "POST" ||
      value.etag !== taskPackageTemplateEtag(template.id, template.revision)
    )
      fail();
  } else fail();
  return value as unknown as PendingTaskPackageCommand;
}
export async function verifyTaskPackagePending(
  value: unknown,
  scope: TaskPackageScope,
) {
  const pending = validateTaskPackagePending(value, scope);
  const prior =
    pending.expected.kind === "template"
      ? pending.expected.previous
      : pending.expected.template;
  if (prior)
    await validateTaskPackageTemplate(
      prior,
      taskPackageTemplateEtag(prior.id, prior.revision),
      scope.bidId,
      scope.identity,
    );
  return pending;
}

export async function validateTemplateACK(
  value: unknown,
  etag: string | null,
  pending: PendingTaskPackageCommand,
  scope: TaskPackageScope,
): Promise<TaskPackageTemplateView> {
  await verifyTaskPackagePending(pending, scope);
  if (pending.expected.kind !== "template") fail();
  const { previous, request } = pending.expected;
  const item = await validateTaskPackageTemplate(
    value,
    etag,
    scope.bidId,
    previous?.id,
  );
  if (
    item.revision !== (previous ? previous.revision + 1 : 1) ||
    item.paused !== (previous?.paused ?? false) ||
    (previous && item.version_id === previous.version_id) ||
    !same(item.configuration, normalizeTaskPackageRequest(request))
  )
    fail();
  return item;
}

export function taskPackageNativeRunRef(
  bidId: string,
  selection: PackageReviewSelection,
  runId: string,
) {
  return `/api/v1/bids/${bidId}/packages/${selection.package_id}/revisions/${selection.revision_id}/requirement-inventories/${selection.inventory_id}/frozen-review-inputs/${selection.frozen_input_id}/execution-inputs/${selection.execution_input_id}/review-runs/${runId}`;
}
async function validateRun(
  value: unknown,
  bidId: string,
): Promise<TaskPackageRunView> {
  if (
    !object(value) ||
    !exactKeys(value, runKeys) ||
    !uuid(bidId) ||
    value.bid_id !== bidId ||
    ![
      value.id,
      value.definition_version_id,
      value.root_operation_id,
      value.final_operation_id,
    ].every(uuid) ||
    value.root_operation_id !== value.final_operation_id ||
    typeof value.state !== "string" ||
    !nativeStates.includes(value.state) ||
    value.stage !== "review" ||
    value.coverage !== "not_formal_score" ||
    value.formal_decisions_created !== false ||
    !(value.error_code === null || text(value.error_code, 200))
  )
    fail();
  const m = value.frozen_manifest;
  if (
    !object(m) ||
    !exactKeys(m, manifestKeys) ||
    m.schema !== "task-package-run/1" ||
    ![m.definition_id, m.definition_version_id, m.actor_id, m.request_id].every(
      uuid,
    ) ||
    m.definition_version_id !== value.definition_version_id ||
    ![m.configuration_digest, m.input_digest, m.fee_scope].every(sha) ||
    m.task_kind !== "denial_check" ||
    m.purpose !== "compliance" ||
    m.trigger !== "manual" ||
    m.trigger_event_id !== null ||
    m.scheduled_at !== null ||
    m.formal_decisions_allowed !== false ||
    !timestamp(m.accepted_at)
  )
    fail();
  const configuration = normalizeTaskPackageRequest(m.configuration);
  if (!same(configuration, m.configuration)) fail();
  const context = m.context,
    selected = configuration.source_selection.input;
  if (
    !object(context) ||
    !exactKeys(context, [
      "subject",
      "selection",
      "review_input_digest",
      "model_input_digest",
      "limitations",
      "overall_coverage",
      "formal_scoring_eligible",
      "submission_eligible",
    ]) ||
    !object(context.subject) ||
    !exactKeys(context.subject, [
      "kind",
      "bid_id",
      "package_id",
      "revision_id",
      "inventory_id",
    ]) ||
    !same(context.subject, {
      kind: "bid_package",
      bid_id: bidId,
      package_id: selected.package_id,
      revision_id: selected.revision_id,
      inventory_id: selected.inventory_id,
    }) ||
    !same(context.selection, selected) ||
    ![context.review_input_digest, context.model_input_digest].every(sha) ||
    !same(context.limitations, [limitation]) ||
    context.overall_coverage !== "partial" ||
    context.formal_scoring_eligible !== false ||
    context.submission_eligible !== false
  )
    fail();
  const native = m.package_review;
  if (
    !object(native) ||
    !exactKeys(native, [
      "run_id",
      "operation_id",
      "start_command_id",
      "input_digest",
      "method_digest",
      "run_ref",
    ]) ||
    ![native.run_id, native.operation_id, native.start_command_id].every(
      uuid,
    ) ||
    native.operation_id !== value.root_operation_id ||
    native.input_digest !== context.review_input_digest ||
    native.method_digest !== selected.method_digest ||
    native.run_ref !==
      taskPackageNativeRunRef(bidId, selected, native.run_id as string)
  )
    fail();
  if (
    (value.state === "succeeded") !== (value.result !== null) ||
    (value.state === "succeeded" && value.error_code !== null) ||
    (value.state === "reconciliation_required" &&
      value.error_code !== "MODEL_CALL_REQUIRES_RECONCILIATION")
  )
    fail();
  if (value.result !== null) {
    const result = value.result;
    if (
      !object(result) ||
      !exactKeys(result, [
        "kind",
        "run_id",
        "run_ref",
        "input_digest",
        "result_digest",
        "overall_coverage",
        "formal_scoring_eligible",
        "submission_eligible",
      ]) ||
      result.kind !== "declared_package_scope_review" ||
      result.run_id !== native.run_id ||
      result.run_ref !== native.run_ref ||
      result.input_digest !== native.input_digest ||
      !sha(result.result_digest) ||
      result.overall_coverage !== "partial" ||
      result.formal_scoring_eligible !== false ||
      result.submission_eligible !== false
    )
      fail();
  }
  const [configurationDigest, inputDigest, feeScope] = await Promise.all([
    templateDigest(configuration, false),
    jsonDigest({
      schema: "task-package-run/1",
      definition_version_id: m.definition_version_id,
      configuration_digest: m.configuration_digest,
      context,
    }),
    jsonDigest({
      schema: "task-package-fee-scope/1",
      bid_id: bidId,
      purpose: "prebid_compliance",
      model_input_digest: context.model_input_digest,
    }),
  ]);
  if (
    m.configuration_digest !== configurationDigest ||
    m.input_digest !== inputDigest ||
    m.fee_scope !== feeScope
  )
    fail();
  // Opaque native review/model/result digests are bound here; their private payloads
  // and original byte proofs remain server-owned and are never claimed reverified.
  return value as unknown as TaskPackageRunView;
}

export async function validateRunACK(
  value: unknown,
  etag: string | null,
  pending: PendingTaskPackageCommand,
  scope: TaskPackageScope,
): Promise<TaskPackageRunView> {
  await verifyTaskPackagePending(pending, scope);
  if (pending.expected.kind !== "run" || etag !== null) fail();
  const item = await validateRun(value, scope.bidId),
    template = pending.expected.template;
  if (
    item.frozen_manifest.definition_id !== template.id ||
    item.definition_version_id !== template.version_id ||
    item.frozen_manifest.configuration_digest !== template.digest ||
    !same(item.frozen_manifest.configuration, template.configuration) ||
    item.state === "reconciliation_required"
  )
    fail();
  // A new template may explicitly reuse an already completed native run. The ACK
  // itself is immutable; it is never replaced with a later GET during recovery.
  return item;
}

/** Current GET/page validation is deliberately separate from command acknowledgement. */
export async function validateCurrentRun(
  value: unknown,
  bidId: string,
  runId: string,
  originalAck?: RunView,
): Promise<TaskPackageRunView> {
  const item = await validateRun(value, bidId);
  if (!uuid(runId) || item.id !== runId) fail();
  if (originalAck) {
    const original = await validateRun(originalAck, bidId);
    if (
      original.id !== item.id ||
      original.root_operation_id !== item.root_operation_id ||
      !same(original.frozen_manifest, item.frozen_manifest)
    )
      fail();
  }
  return item;
}

export async function validateTaskPackageBasis(
  value: unknown,
  etag: string | null,
  scope: TaskPackageScope,
): Promise<Bid | TaskPackageTemplateView> {
  assertTaskPackageScope(scope);
  if (uuid(scope.identity))
    return validateTaskPackageTemplate(
      value,
      etag,
      scope.bidId,
      scope.identity,
    );
  if (
    !object(value) ||
    value.id !== scope.bidId ||
    !integer(value.revision) ||
    typeof etag !== "string" ||
    !new RegExp(`^"bid:${scope.bidId}:[0-9a-f]{64}"$`).test(etag)
  )
    fail("项目的新修订基准无法核对，仍保留冲突与原输入。");
  return value as unknown as Bid;
}

const definitiveCodes = new Set([
  "REVISION_CONFLICT",
  "VALIDATION_ERROR",
  "INVALID_REQUEST",
  "TASK_TEMPLATE_PAUSED",
  "TASK_PACKAGE_TEMPLATE_CHANGED",
  "TASK_PACKAGE_SELECTION_CHANGED",
  "TASK_PACKAGE_METHOD_CHANGED",
  "TASK_PACKAGE_REQUEST_INVALID",
  "TASK_PACKAGE_SELECTION_INVALID",
  "TASK_PACKAGE_REPREPARE_REQUIRED",
  "TASK_PACKAGE_BINDING_INVALID",
  "MODEL_CALL_REQUIRES_RECONCILIATION",
  "BID_ARCHIVED",
  "BID_WORK_NOT_WRITABLE",
  "SOURCE_NOT_CURRENT",
  "SOURCE_CHANGED",
]);
export const definitiveTaskPackageFailure = (error: unknown) =>
  error instanceof ApiError &&
  !error.retryable &&
  [409, 412, 422].includes(error.status) &&
  definitiveCodes.has(error.code);
