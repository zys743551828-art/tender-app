import type {
  AssistantAction,
  ExactPackageAuthoringSelection,
  RunView,
  TaskPackageAuthoringResult,
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
import { historicalSame as same } from "./historicalImportProtocol";
import { readAuthoringContent } from "./richEditorSchema";
import {
  authoringInputFailure as fail,
  authoringInteger as integer,
  authoringText as text,
  authoringTimestamp as timestamp,
  isPackageAuthoringSelection,
  validateAuthoringScope,
  validateAuthoringTarget,
  type AuthoringBusinessScope,
} from "./packageAuthoringInputProtocol";
import type { PackageAuthoringInputRequest } from "./contracts";
import type {
  PendingTaskPackageCommand,
  TaskPackageScope,
} from "./taskPackageProtocol";

export type PackageAuthoringConfiguration = TemplateRequest & {
  task_kind: "chapter_suggestion";
  section_id: string;
  source_selection: ExactPackageAuthoringSelection;
  trigger: { mode: "manual"; cron: null; timezone: string };
};
export type PackageAuthoringTemplateView = TemplateView & {
  purpose: "assist";
  configuration: PackageAuthoringConfiguration;
  next_run_at: null;
};
export type PackageAuthoringExpected =
  | {
      kind: "authoring_template";
      request: TemplateRequest;
      previous: TemplateView | null;
    }
  | { kind: "authoring_run"; template: TemplateView };
export const authoringTemplateEtag = (id: string, revision: number) =>
  `"task-template:${id}:${revision}"`;
export function isExactPackageAuthoring(
  configuration: TemplateRequest,
): configuration is TemplateRequest & {
  source_selection: ExactPackageAuthoringSelection;
} {
  return configuration.source_selection?.mode === "exact_package_authoring";
}
export function samePackageAuthoringSource(
  a: TemplateRequest,
  b: TemplateRequest,
) {
  return (
    isExactPackageAuthoring(a) &&
    isExactPackageAuthoring(b) &&
    a.section_id === b.section_id &&
    same(a.source_selection, b.source_selection)
  );
}
export function claimsPackageAuthoringRun(value: RunView) {
  const f = value.frozen_manifest;
  return (
    object(f) &&
    (f.schema === "task-package-authoring-run/1" ||
      (object(f.configuration) &&
        object(f.configuration.source_selection) &&
        f.configuration.source_selection.mode === "exact_package_authoring") ||
      (object(value.result) &&
        (value.result.schema === "task-package-authoring-result/1" ||
          value.result.source_scope === "exact_package_context")))
  );
}
export function normalizePackageAuthoringRequest(
  value: unknown,
): PackageAuthoringConfiguration {
  if (
    !object(value) ||
    Object.keys(value).some(
      (k) =>
        ![
          "name",
          "task_kind",
          "instructions",
          "section_id",
          "source_selection",
          "trigger",
        ].includes(k),
    ) ||
    !text(value.name, 200) ||
    !text(value.instructions, 8000) ||
    value.task_kind !== "chapter_suggestion" ||
    !uuid(value.section_id) ||
    !object(value.source_selection) ||
    !exactKeys(value.source_selection, ["mode", "input"]) ||
    value.source_selection.mode !== "exact_package_authoring" ||
    !isPackageAuthoringSelection(value.source_selection.input)
  )
    fail("固定整包编写模板缺少明确目标或固定输入。");
  const t = value.trigger === undefined ? {} : value.trigger;
  if (
    !object(t) ||
    Object.keys(t).some((k) => !["mode", "cron", "timezone"].includes(k)) ||
    (t.mode !== undefined && t.mode !== "manual") ||
    (t.cron !== undefined && t.cron !== null) ||
    (t.timezone !== undefined && !text(t.timezone, 100))
  )
    fail("固定整包编写目前只支持明确手动运行。");
  const timezone = (t.timezone ?? "Asia/Shanghai") as string;
  try {
    new Intl.DateTimeFormat("en", { timeZone: timezone });
  } catch {
    fail("模板时区无法核对。");
  }
  return {
    name: value.name,
    task_kind: "chapter_suggestion",
    instructions: value.instructions,
    section_id: value.section_id,
    source_selection: {
      mode: "exact_package_authoring",
      input: { ...value.source_selection.input },
    },
    trigger: { mode: "manual", cron: null, timezone },
  };
}
function templateShape(
  value: unknown,
  bidId: string,
  id?: string,
): PackageAuthoringTemplateView {
  if (
    !object(value) ||
    !exactKeys(value, [
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
    ]) ||
    !uuid(value.id) ||
    value.bid_id !== bidId ||
    !uuid(bidId) ||
    (id !== undefined && id !== value.id) ||
    !uuid(value.version_id) ||
    !integer(value.revision) ||
    !sha(value.digest) ||
    value.purpose !== "assist" ||
    typeof value.paused !== "boolean" ||
    value.next_run_at !== null ||
    value.run_created !== false ||
    value.active_runs_cancelled !== false ||
    !same(
      normalizePackageAuthoringRequest(value.configuration),
      value.configuration,
    )
  )
    fail("固定整包编写模板回执不完整或身份不符。");
  return value as unknown as PackageAuthoringTemplateView;
}
export async function validatePackageAuthoringTemplate(
  value: unknown,
  etag: string | null,
  bidId: string,
  id?: string,
) {
  const item = templateShape(value, bidId, id);
  if (
    etag !== authoringTemplateEtag(item.id, item.revision) ||
    item.digest !==
      (await jsonDigest({
        schema: "task-template/1",
        definition: item.configuration,
        paused: item.paused,
        formal_decisions_allowed: false,
      }))
  )
    fail("模板全文、修订和摘要不一致；保留原请求。");
  return item;
}
export function validatePackageAuthoringPending(
  value: unknown,
  scope: TaskPackageScope,
): PendingTaskPackageCommand {
  if (
    !object(value) ||
    !exactKeys(value, ["path", "method", "body", "etag", "expected", "key"]) ||
    !uuid(value.key) ||
    typeof value.etag !== "string" ||
    !object(value.expected) ||
    value.expected.kind !== scope.kind
  )
    fail();
  const e = value.expected,
    base = `/bids/${scope.bidId}/task-definitions`;
  if (e.kind === "authoring_template") {
    if (
      !exactKeys(e, ["kind", "request", "previous"]) ||
      !same(value.body, e.request)
    )
      fail();
    normalizePackageAuthoringRequest(e.request);
    if (e.previous === null) {
      if (
        scope.identity !== "new" ||
        value.path !== base ||
        value.method !== "POST" ||
        !new RegExp(`^"bid:${scope.bidId}:[0-9a-f]{64}"$`).test(value.etag)
      )
        fail();
    } else {
      const previous = templateShape(e.previous, scope.bidId, scope.identity);
      if (
        value.path !== `${base}/${previous.id}` ||
        value.method !== "PUT" ||
        value.etag !== authoringTemplateEtag(previous.id, previous.revision) ||
        !samePackageAuthoringSource(
          normalizePackageAuthoringRequest(e.request),
          previous.configuration,
        )
      )
        fail("修改模板须保留已绑定的编写输入；更换来源请另建模板。");
    }
  } else if (e.kind === "authoring_run") {
    if (
      !exactKeys(e, ["kind", "template"]) ||
      !object(value.body) ||
      !exactKeys(value.body, ["rerun"]) ||
      value.body.rerun !== false
    )
      fail();
    const template = templateShape(e.template, scope.bidId, scope.identity);
    if (
      template.paused ||
      value.path !== `${base}/${template.id}/runs` ||
      value.method !== "POST" ||
      value.etag !== authoringTemplateEtag(template.id, template.revision)
    )
      fail();
  } else fail();
  return value as unknown as PendingTaskPackageCommand;
}
export async function verifyPackageAuthoringPending(
  value: unknown,
  scope: TaskPackageScope,
) {
  const pending = validatePackageAuthoringPending(value, scope);
  const previous =
    pending.expected.kind === "authoring_template"
      ? pending.expected.previous
      : pending.expected.kind === "authoring_run"
        ? pending.expected.template
        : null;
  if (previous)
    await validatePackageAuthoringTemplate(
      previous,
      authoringTemplateEtag(previous.id, previous.revision),
      scope.bidId,
      scope.identity,
    );
  return pending;
}
export async function validatePackageAuthoringTemplateACK(
  value: unknown,
  etag: string | null,
  pending: PendingTaskPackageCommand,
  scope: TaskPackageScope,
) {
  await verifyPackageAuthoringPending(pending, scope);
  if (pending.expected.kind !== "authoring_template") fail();
  const { previous, request } = pending.expected;
  const item = await validatePackageAuthoringTemplate(
    value,
    etag,
    scope.bidId,
    previous?.id,
  );
  if (
    item.revision !== (previous ? previous.revision + 1 : 1) ||
    item.paused !== (previous?.paused ?? false) ||
    (previous && item.version_id === previous.version_id) ||
    !same(item.configuration, normalizePackageAuthoringRequest(request))
  )
    fail("保存回执没有对应完整原输入，恢复记录继续保留。");
  return item;
}
export type PackageAuthoringRunView = Omit<
  RunView,
  "frozen_manifest" | "result"
> & {
  frozen_manifest: {
    schema: "task-package-authoring-run/1";
    definition_id: string;
    definition_version_id: string;
    configuration_digest: string;
    configuration: PackageAuthoringConfiguration;
    task_kind: "chapter_suggestion";
    purpose: "assist";
    actor_id: string;
    request_id: string;
    context: {
      input: ExactPackageAuthoringSelection["input"];
      context_digest: string;
      target: PackageAuthoringInputRequest["target_section"];
      scope: AuthoringBusinessScope;
      source_scope: "exact_package_context";
    };
    input_digest: string;
    fee_scope: string;
    trigger: "manual";
    trigger_event_id: null;
    scheduled_at: null;
    accepted_at: string;
    formal_decisions_allowed: false;
    assistant_job_id: string;
    authoring_binding: {
      job_input_digest: string;
      writing_plan_id: string;
      writing_plan_digest: string;
      operation_id: string;
    };
  };
  result: TaskPackageAuthoringResult;
};
export async function validatePackageAuthoringRun(
  value: unknown,
  bidId: string,
  id: string,
): Promise<PackageAuthoringRunView> {
  if (
    !object(value) ||
    !exactKeys(value, [
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
    ]) ||
    value.id !== id ||
    value.bid_id !== bidId ||
    ![
      value.id,
      value.bid_id,
      value.definition_version_id,
      value.root_operation_id,
    ].every(uuid) ||
    value.final_operation_id !== null ||
    value.stage !== "execution" ||
    value.formal_decisions_created !== false ||
    value.coverage !== "not_formal_score" ||
    !(value.error_code === null || text(value.error_code, 200)) ||
    !object(value.frozen_manifest)
  )
    fail("固定整包编写运行身份或边界不一致，未采用返回结果。");
  const f = value.frozen_manifest;
  if (
    !exactKeys(f, [
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
      "assistant_job_id",
      "authoring_binding",
    ]) ||
    f.schema !== "task-package-authoring-run/1" ||
    ![f.definition_id, f.actor_id, f.request_id, f.assistant_job_id].every(
      uuid,
    ) ||
    f.definition_version_id !== value.definition_version_id ||
    ![f.configuration_digest, f.input_digest, f.fee_scope].every(sha) ||
    f.task_kind !== "chapter_suggestion" ||
    f.purpose !== "assist" ||
    f.trigger !== "manual" ||
    f.trigger_event_id !== null ||
    f.scheduled_at !== null ||
    !timestamp(f.accepted_at) ||
    f.formal_decisions_allowed !== false ||
    !object(f.context) ||
    !object(f.authoring_binding)
  )
    fail();
  const config = normalizePackageAuthoringRequest(f.configuration),
    c = f.context,
    b = f.authoring_binding;
  if (
    !same(config, f.configuration) ||
    !exactKeys(c, [
      "input",
      "context_digest",
      "target",
      "scope",
      "source_scope",
    ]) ||
    !same(c.input, config.source_selection.input) ||
    !sha(c.context_digest) ||
    c.source_scope !== "exact_package_context" ||
    !exactKeys(b, [
      "job_input_digest",
      "writing_plan_id",
      "writing_plan_digest",
      "operation_id",
    ]) ||
    !sha(b.job_input_digest) ||
    !uuid(b.writing_plan_id) ||
    !sha(b.writing_plan_digest) ||
    b.operation_id !== value.root_operation_id
  )
    fail();
  validateAuthoringScope(c.scope, bidId);
  const target = validateAuthoringTarget(c.target);
  if (
    config.section_id !== target.section_id ||
    f.configuration_digest !==
      (await jsonDigest({
        schema: "task-template/1",
        definition: config,
        paused: false,
        formal_decisions_allowed: false,
      })) ||
    f.input_digest !==
      (await jsonDigest({
        schema: "task-package-authoring-run/1",
        definition_version_id: f.definition_version_id,
        configuration_digest: f.configuration_digest,
        context: c,
      }))
  )
    fail("冻结模板和完整输入摘要不一致。");
  const r = value.result;
  if (
    !object(r) ||
    !exactKeys(r, [
      "schema",
      "job_id",
      "job_input_digest",
      "writing_plan_id",
      "operation_id",
      "job_ref",
      "section_id",
      "base_section_revision",
      "authoring_input_id",
      "authoring_input_digest",
      "context_digest",
      "publication_state",
      "candidate_digest",
      "action_id",
      "action_ref",
      "source_scope",
      "automatic_apply",
      "apply_available",
      "build_available",
    ]) ||
    r.schema !== "task-package-authoring-result/1" ||
    r.job_id !== f.assistant_job_id ||
    r.job_input_digest !== b.job_input_digest ||
    r.writing_plan_id !== b.writing_plan_id ||
    r.operation_id !== b.operation_id ||
    r.job_ref !== `/api/v1/assistant/jobs/${r.job_id}` ||
    r.section_id !== target.section_id ||
    r.base_section_revision !== target.base_section_revision ||
    r.authoring_input_id !== config.source_selection.input.authoring_input_id ||
    r.authoring_input_digest !==
      config.source_selection.input.authoring_input_digest ||
    r.context_digest !== c.context_digest ||
    r.source_scope !== "exact_package_context" ||
    r.automatic_apply !== false ||
    r.apply_available !== false ||
    r.build_available !== false ||
    !(r.candidate_digest === null || sha(r.candidate_digest))
  )
    fail("章节提案与固定输入的关联未通过核验。");
  const states: Record<string, string[]> = {
    pending: [
      "queued",
      "running",
      "cancel_requested",
      "cancelled",
      "failed",
      "reconciliation_required",
      "awaiting_publication",
    ],
    published: ["succeeded", "reconciliation_required"],
    stale: ["superseded", "reconciliation_required"],
    failed: ["failed", "reconciliation_required"],
  };
  if (
    typeof r.publication_state !== "string" ||
    !Object.hasOwn(states, r.publication_state) ||
    typeof value.state !== "string" ||
    !states[r.publication_state].includes(value.state) ||
    ((r.publication_state !== "pending" ||
      value.state === "awaiting_publication") &&
      !sha(r.candidate_digest)) ||
    (r.publication_state === "published"
      ? !uuid(r.action_id) ||
        r.action_ref !== `/api/v1/assistant/actions/${r.action_id}`
      : r.action_id !== null || r.action_ref !== null)
  )
    fail("候选、发布和任务状态不一致，未当作已完成。");
  return value as unknown as PackageAuthoringRunView;
}
export async function validatePackageAuthoringRunACK(
  value: unknown,
  etag: string | null,
  pending: PendingTaskPackageCommand,
  scope: TaskPackageScope,
) {
  await verifyPackageAuthoringPending(pending, scope);
  if (
    pending.expected.kind !== "authoring_run" ||
    etag !== null ||
    !object(value) ||
    !uuid(value.id)
  )
    fail();
  const run = await validatePackageAuthoringRun(value, scope.bidId, value.id),
    template = pending.expected.template,
    f = run.frozen_manifest;
  if (
    f.definition_id !== template.id ||
    f.definition_version_id !== template.version_id ||
    f.configuration_digest !== template.digest ||
    !same(f.configuration, template.configuration)
  )
    fail("运行受理回执未对应原模板和输入，原请求仍保留。");
  return run;
}
type PackageAction = AssistantAction & {
  preview: Extract<
    AssistantAction["preview"],
    { kind: "package_authoring_patch" }
  >;
};
export function claimsPackageAuthoringAction(value: unknown) {
  return (
    object(value) &&
    object(value.preview) &&
    (value.preview.kind === "package_authoring_patch" ||
      value.preview.source_scope === "exact_package_context" ||
      "authoring_input_id" in value.preview ||
      "authoring_input_digest" in value.preview)
  );
}
export function readPackageAuthoringProposal(
  value: unknown,
  bidId: string,
  expected?: TaskPackageAuthoringResult,
): PackageAction {
  if (
    !object(value) ||
    !exactKeys(value, [
      "action_id",
      "job_id",
      "target_bid_id",
      "tool",
      "state",
      "revision",
      "request_digest",
      "base_revision",
      "expires_at",
      "preview",
      "result",
      "resolved_by",
      "error_code",
      "formal_scoring_input",
    ]) ||
    !uuid(value.action_id) ||
    !uuid(value.job_id) ||
    value.target_bid_id !== bidId ||
    !uuid(bidId) ||
    value.tool !== "authoring.apply_patch" ||
    !["pending", "executed", "rejected", "expired", "stale", "failed"].includes(
      String(value.state),
    ) ||
    !integer(value.revision) ||
    !integer(value.base_revision) ||
    !sha(value.request_digest) ||
    !timestamp(value.expires_at) ||
    value.formal_scoring_input !== false ||
    !(value.resolved_by === null || uuid(value.resolved_by)) ||
    !(value.error_code === null || text(value.error_code, 200)) ||
    !object(value.preview)
  )
    fail("固定整包候选卡片身份不完整。");
  const p = value.preview;
  if (
    !exactKeys(p, [
      "before",
      "after",
      "kind",
      "section_id",
      "base_section_revision",
      "authoring_input_id",
      "authoring_input_digest",
      "source_scope",
      "apply_available",
      "build_available",
      "effect",
    ]) ||
    p.kind !== "package_authoring_patch" ||
    !uuid(p.section_id) ||
    !integer(p.base_section_revision) ||
    !uuid(p.authoring_input_id) ||
    !sha(p.authoring_input_digest) ||
    p.source_scope !== "exact_package_context" ||
    typeof p.apply_available !== "boolean" ||
    typeof p.build_available !== "boolean" ||
    !text(p.effect, 8000) ||
    !object(p.before) ||
    !object(p.after)
  )
    fail("候选正文或固定输入边界不一致。");
  readAuthoringContent(p.before, true);
  readAuthoringContent(p.after, true);
  if (
    expected &&
    (value.action_id !== expected.action_id ||
      value.job_id !== expected.job_id ||
      p.section_id !== expected.section_id ||
      p.base_section_revision !== expected.base_section_revision ||
      p.authoring_input_id !== expected.authoring_input_id ||
      p.authoring_input_digest !== expected.authoring_input_digest)
  )
    fail("此候选不属于选中的运行与正文基准。");
  return value as unknown as PackageAction;
}
