import { ApiError } from "./api";
import type { Bid, PackageReviewSelection, RunView } from "./contracts";
import type {
  PackageTriggerIntentPage,
  PackageTriggerIntentView,
  TemplateRequest,
  TemplateView,
} from "./taskTriggerContracts";
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
import {
  validatePackageAuthoringPending,
  verifyPackageAuthoringPending,
  validatePackageAuthoringTemplate,
  type PackageAuthoringExpected,
  type PackageAuthoringTemplateView,
} from "./taskPackageAuthoringProtocol";

export type TaskPackageKind =
  | "template"
  | "run"
  | "trigger_cancel"
  | "authoring_template"
  | "authoring_run";
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
    mode: "exact_package_review" | "exact_package_trigger";
    input: PackageReviewSelection;
  };
  trigger: {
    mode: "manual" | "material_updated" | "schedule";
    cron: string | null;
    timezone: string;
  };
};
export type TaskPackageTemplateView = TemplateView & {
  purpose: "compliance";
  configuration: TaskPackageConfiguration;
  next_run_at: string | null;
};
export type TaskPackageTemplateExpected = {
  kind: "template";
  request: TemplateRequest;
  previous: TemplateView | null;
};
export type TaskPackageRunExpected = { kind: "run"; template: TemplateView };
export type TaskPackageTriggerCancelExpected = {
  kind: "trigger_cancel";
  intent: PackageTriggerIntentView;
};
export type TaskPackageCommandRequest = {
  path: string;
  method: "POST" | "PUT";
  body: TemplateRequest | { rerun: false } | { reason: string };
  etag: string;
  expected:
    | TaskPackageTemplateExpected
    | TaskPackageRunExpected
    | TaskPackageTriggerCancelExpected
    | PackageAuthoringExpected;
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
  schema: "task-package-run/1" | "task-package-trigger-run/1";
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
  trigger: "manual" | "material_updated" | "schedule";
  trigger_event_id: string | null;
  scheduled_at: string | null;
  trigger_intent_id?: string;
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

export const taskTriggerIntentEtag = (item: PackageTriggerIntentView) =>
  `"task-package-trigger-intent:${item.id}:${item.input_digest}"`;

/** The manifest digest is server-owned; validate the complete exposed identity without pretending to recompute it. */
export function validateTaskTriggerIntent(
  value: unknown,
  bidId: string,
  identity?: string,
  original?: PackageTriggerIntentView,
): PackageTriggerIntentView {
  if (
    !object(value) ||
    !exactKeys(value, [
      "id",
      "bid_id",
      "definition_id",
      "definition_version_id",
      "trigger",
      "trigger_event_id",
      "scheduled_at",
      "created_at",
      "selection",
      "input_digest",
      "state",
      "error_code",
      "run_id",
      "run_ref",
      "reused",
      "automatic_input_selection",
    ]) ||
    ![
      value.id,
      value.bid_id,
      value.definition_id,
      value.definition_version_id,
    ].every(uuid) ||
    value.bid_id !== bidId ||
    (identity !== undefined && value.id !== identity) ||
    !sha(value.input_digest) ||
    !isTaskPackageSelection(value.selection) ||
    !timestamp(value.created_at) ||
    typeof value.reused !== "boolean" ||
    value.automatic_input_selection !== false ||
    (value.trigger === "material_updated"
      ? !uuid(value.trigger_event_id) || value.scheduled_at !== null
      : value.trigger !== "schedule" ||
        value.trigger_event_id !== null ||
        !timestamp(value.scheduled_at)) ||
    (value.state === "accepted"
      ? !uuid(value.run_id) ||
        value.run_ref !== `/api/v1/bids/${bidId}/task-runs/${value.run_id}` ||
        value.error_code !== null
      : !["pending", "blocked", "cancelled"].includes(String(value.state)) ||
        value.run_id !== null ||
        value.run_ref !== null ||
        value.reused ||
        (value.state === "pending"
          ? value.error_code !== null
          : !text(value.error_code, 200)) ||
        (value.state === "cancelled" &&
          value.error_code !== "TASK_TRIGGER_CANCELLED"))
  )
    fail("触发记录的固定输入、事件或运行身份不一致，未采用。");
  if (original) {
    const current = value as unknown as PackageTriggerIntentView;
    const keys = [
      "id",
      "bid_id",
      "definition_id",
      "definition_version_id",
      "trigger",
      "trigger_event_id",
      "scheduled_at",
      "created_at",
      "selection",
      "input_digest",
      "automatic_input_selection",
    ] as const;
    if (
      keys.some((key) => !same(current[key], original[key])) ||
      (original.state !== "pending" && !same(current, original))
    )
      fail("原触发输入或已记录终态发生变化，保留原记录。 ");
  }
  return value as unknown as PackageTriggerIntentView;
}

export function validateTaskTriggerPage(
  value: unknown,
  bidId: string,
): PackageTriggerIntentPage {
  if (
    !object(value) ||
    !exactKeys(value, ["items", "next_after"]) ||
    !Array.isArray(value.items) ||
    value.items.length > 100
  )
    fail();
  const items = value.items.map((item) =>
    validateTaskTriggerIntent(item, bidId),
  );
  if (
    new Set(items.map((item) => item.id)).size !== items.length ||
    (value.next_after !== null &&
      (value.next_after !== items.at(-1)?.id || !uuid(value.next_after)))
  )
    fail();
  return { items, next_after: value.next_after as string | null };
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
    !["exact_package_review", "exact_package_trigger"].includes(
      String(source.mode),
    ) ||
    !isTaskPackageSelection(source.input)
  )
    fail();
  const trigger = value.trigger === undefined ? {} : value.trigger;
  const automatic = source.mode === "exact_package_trigger";
  if (
    !object(trigger) ||
    Object.keys(trigger).some(
      (key) => !["mode", "cron", "timezone"].includes(key),
    ) ||
    (automatic
      ? !["material_updated", "schedule"].includes(String(trigger.mode))
      : trigger.mode !== undefined && trigger.mode !== "manual") ||
    (trigger.mode === "schedule"
      ? !text(trigger.cron, 200) ||
        trigger.cron.trim().split(/\s+/u).length !== 5
      : trigger.cron !== undefined && trigger.cron !== null) ||
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
      mode: automatic ? "exact_package_trigger" : "exact_package_review",
      input: { ...source.input },
    },
    trigger: {
      mode: (trigger.mode ??
        "manual") as TaskPackageConfiguration["trigger"]["mode"],
      cron:
        trigger.mode === "schedule"
          ? String(trigger.cron).trim().split(/\s+/u).join(" ")
          : null,
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
    ![
      "template",
      "run",
      "trigger_cancel",
      "authoring_template",
      "authoring_run",
    ].includes(scope.kind) ||
    typeof scope.identity !== "string" ||
    !(
      uuid(scope.identity) ||
      (scope.kind === "template" &&
        isTaskPackageCreationIdentity(scope.identity)) ||
      (scope.kind === "authoring_template" && scope.identity === "new")
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
    !(value.next_run_at === null || timestamp(value.next_run_at)) ||
    value.run_created !== false ||
    value.active_runs_cancelled !== false
  )
    fail();
  const configuration = normalizeTaskPackageRequest(value.configuration);
  if (
    !same(configuration, value.configuration) ||
    (configuration.trigger.mode === "schedule" && !value.paused
      ? value.next_run_at === null
      : value.next_run_at !== null)
  )
    fail();
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
  if (scope.kind === "authoring_template" || scope.kind === "authoring_run")
    return validatePackageAuthoringPending(value, scope);
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
      template.configuration.source_selection.mode !== "exact_package_review" ||
      template.configuration.trigger.mode !== "manual" ||
      value.path !== `${base}/${template.id}/runs` ||
      value.method !== "POST" ||
      value.etag !== taskPackageTemplateEtag(template.id, template.revision)
    )
      fail();
  } else if (expected.kind === "trigger_cancel") {
    if (
      !exactKeys(expected, ["kind", "intent"]) ||
      !object(value.body) ||
      !exactKeys(value.body, ["reason"]) ||
      !text(value.body.reason, 1000)
    )
      fail();
    const intent = validateTaskTriggerIntent(
      expected.intent,
      scope.bidId,
      scope.identity,
    );
    if (
      intent.state !== "pending" ||
      value.method !== "POST" ||
      value.path !==
        `/bids/${scope.bidId}/task-package-trigger-intents/${scope.identity}/cancel` ||
      value.etag !== taskTriggerIntentEtag(intent)
    )
      fail();
  } else fail();
  return value as unknown as PendingTaskPackageCommand;
}
export async function verifyTaskPackagePending(
  value: unknown,
  scope: TaskPackageScope,
) {
  if (scope.kind === "authoring_template" || scope.kind === "authoring_run") {
    assertTaskPackageScope(scope);
    return verifyPackageAuthoringPending(value, scope);
  }
  const pending = validateTaskPackagePending(value, scope);
  const prior =
    pending.expected.kind === "template"
      ? pending.expected.previous
      : pending.expected.kind === "run"
        ? pending.expected.template
        : null;
  if (prior)
    await validateTaskPackageTemplate(
      prior,
      taskPackageTemplateEtag(prior.id, prior.revision),
      scope.bidId,
      scope.identity,
    );
  return pending;
}

export async function validateTaskTriggerCancelACK(
  value: unknown,
  etag: string | null,
  pending: PendingTaskPackageCommand,
  scope: TaskPackageScope,
): Promise<PackageTriggerIntentView> {
  await verifyTaskPackagePending(pending, scope);
  if (pending.expected.kind !== "trigger_cancel" || etag !== null) fail();
  const item = validateTaskTriggerIntent(
    value,
    scope.bidId,
    scope.identity,
    pending.expected.intent,
  );
  if (!["cancelled", "blocked"].includes(item.state))
    fail("取消尚未取得可信终态回执，保留原请求。");
  return item;
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
  const automatic = object(m) && m.schema === "task-package-trigger-run/1";
  if (
    !object(m) ||
    !exactKeys(
      m,
      automatic ? [...manifestKeys, "trigger_intent_id"] : manifestKeys,
    ) ||
    (!automatic && m.schema !== "task-package-run/1") ||
    ![m.definition_id, m.definition_version_id, m.actor_id, m.request_id].every(
      uuid,
    ) ||
    m.definition_version_id !== value.definition_version_id ||
    ![m.configuration_digest, m.input_digest, m.fee_scope].every(sha) ||
    m.task_kind !== "denial_check" ||
    m.purpose !== "compliance" ||
    (automatic
      ? !uuid(m.trigger_intent_id) ||
        (m.trigger === "material_updated"
          ? !uuid(m.trigger_event_id) || m.scheduled_at !== null
          : m.trigger !== "schedule" ||
            m.trigger_event_id !== null ||
            !timestamp(m.scheduled_at))
      : m.trigger !== "manual" ||
        m.trigger_event_id !== null ||
        m.scheduled_at !== null) ||
    m.formal_decisions_allowed !== false ||
    !timestamp(m.accepted_at)
  )
    fail();
  const configuration = normalizeTaskPackageRequest(m.configuration);
  if (
    !same(configuration, m.configuration) ||
    configuration.source_selection.mode !==
      (automatic ? "exact_package_trigger" : "exact_package_review") ||
    configuration.trigger.mode !== m.trigger
  )
    fail();
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
      schema: automatic ? "task-package-trigger-run/1" : "task-package-run/1",
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
    item.frozen_manifest.schema !== "task-package-run/1" ||
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
): Promise<Bid | TaskPackageTemplateView | PackageAuthoringTemplateView> {
  assertTaskPackageScope(scope);
  if (scope.kind === "trigger_cancel")
    fail("触发输入固定，取消请求不能自动更换修订条件。");
  if (
    uuid(scope.identity) &&
    (scope.kind === "authoring_template" || scope.kind === "authoring_run")
  )
    return validatePackageAuthoringTemplate(
      value,
      etag,
      scope.bidId,
      scope.identity,
    );
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
  "TASK_TRIGGER_ALREADY_ACCEPTED",
  "TASK_PACKAGE_TRIGGER_EXPLICIT_WAKEUP_REQUIRED",
  "MODEL_CALL_REQUIRES_RECONCILIATION",
  "BID_ARCHIVED",
  "BID_WORK_NOT_WRITABLE",
  "SOURCE_NOT_CURRENT",
  "SOURCE_CHANGED",
]);
const authoringRunRefusals = new Set([
  "AUTHORING_PACKAGE_ORIGINAL_JOB_REQUIRED",
  "AUTHORING_PACKAGE_RERUN_NOT_SUPPORTED",
  "AUTHORING_PACKAGE_TEMPLATE_CHANGED",
  "AUTHORING_PACKAGE_INPUT_CHANGED",
  "ORIGINAL_NOT_AVAILABLE",
  "ORIGINAL_BYTES_CORRUPTED",
  "ASSISTANT_INDEPENDENCE_UNPROVEN",
  "ASSISTANT_ORIGINAL_REFERENCE_AMBIGUOUS",
  "ASSISTANT_ORIGINAL_REFERENCE_REQUIRED",
  "ASSISTANT_PRICE_UNAVAILABLE",
  "ASSISTANT_SYNTHETIC_PRICE_FORBIDDEN",
  "ASSISTANT_INPUT_TOO_LARGE",
  "AUTHORING_PACKAGE_CONTEXT_TOO_LARGE",
]);
export const definitiveTaskPackageFailure = (
  error: unknown,
  kind?: TaskPackageKind,
) =>
  error instanceof ApiError &&
  !error.retryable &&
  [409, 412, 422].includes(error.status) &&
  (!kind?.startsWith("authoring_") ||
    !error.code.endsWith("_BINDING_INVALID")) &&
  (definitiveCodes.has(error.code) ||
    (kind === "authoring_run" &&
      [409, 422].includes(error.status) &&
      authoringRunRefusals.has(error.code)));
