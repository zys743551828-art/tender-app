import actual from "./test-fixtures/task-package-http.json";
import type {
  PackageDependencyPlanView,
  PackageExecutionInputView,
  PackageRequirementInventoryView,
  PackageReviewFrozenInputView,
  PackageReviewRunView,
  RunPage,
  RunView,
  TaskKindPage,
  TaskNotificationPage,
  TemplatePage,
  TemplateVersionView,
  TemplateView,
  TemplateRequest,
} from "./contracts";
import type {
  PendingTaskPackageCommand,
  TaskPackageCommandRequest,
  TaskPackageScope,
} from "./taskPackageProtocol";

export type TaskPackageHTTPFixture<T> = {
  request: {
    method: string;
    path: string;
    body?: unknown;
    headers?: Record<string, string>;
  };
  status: number;
  headers: Record<string, string>;
  data: T;
};

type TaskPackageFixtures = {
  kinds: TaskPackageHTTPFixture<TaskKindPage>;
  frozen: TaskPackageHTTPFixture<PackageReviewFrozenInputView>;
  prepared: TaskPackageHTTPFixture<PackageExecutionInputView>;
  plan: TaskPackageHTTPFixture<PackageDependencyPlanView>;
  inventory: TaskPackageHTTPFixture<PackageRequirementInventoryView>;
  created: TaskPackageHTTPFixture<TemplateView>;
  revised: TaskPackageHTTPFixture<TemplateView>;
  createdVersion: TaskPackageHTTPFixture<TemplateVersionView>;
  revisedVersion: TaskPackageHTTPFixture<TemplateVersionView>;
  queued: TaskPackageHTTPFixture<RunView>;
  completed: TaskPackageHTTPFixture<RunView>;
  replay: TaskPackageHTTPFixture<RunView>;
  native: TaskPackageHTTPFixture<PackageReviewRunView>;
  templates: TaskPackageHTTPFixture<TemplatePage>;
  runs: TaskPackageHTTPFixture<RunPage>;
  notifications: TaskPackageHTTPFixture<TaskNotificationPage>;
};

/** Actual HTTP responses from isolated PostgreSQL and Worker with synthetic originals.
 * Requests exclude session cookies and CSRF tokens. No production data or model call.
 * Digests and timestamps are retained byte for byte; never recompute a fixture to pass.
 */
export function taskPackageFixture(): TaskPackageFixtures {
  return structuredClone(actual) as unknown as TaskPackageFixtures;
}

export function taskPackageCommandFixture() {
  const f = taskPackageFixture();
  const base = {
    memberId: f.queued.data.frozen_manifest.actor_id as string,
    bidId: f.created.data.bid_id,
  };
  const createScope: TaskPackageScope<"template"> = {
    ...base,
    kind: "template",
    identity: "new",
  };
  const reviseScope: TaskPackageScope<"template"> = {
    ...base,
    kind: "template",
    identity: f.created.data.id,
  };
  const runScope: TaskPackageScope<"run"> = {
    ...base,
    kind: "run",
    identity: f.created.data.id,
  };
  const create: TaskPackageCommandRequest = {
    path: f.created.request.path.replace(/^\/api\/v1/, ""),
    method: "POST",
    body: f.created.request.body as TemplateRequest,
    etag: f.created.request.headers!["if-match"],
    expected: {
      kind: "template",
      request: f.created.request.body as TemplateRequest,
      previous: null,
    },
  };
  const revise: TaskPackageCommandRequest = {
    path: f.revised.request.path.replace(/^\/api\/v1/, ""),
    method: "PUT",
    body: f.revised.request.body as TemplateRequest,
    etag: f.revised.request.headers!["if-match"],
    expected: {
      kind: "template",
      request: f.revised.request.body as TemplateRequest,
      previous: f.created.data,
    },
  };
  const run: TaskPackageCommandRequest = {
    path: f.queued.request.path.replace(/^\/api\/v1/, ""),
    method: "POST",
    body: { rerun: false },
    etag: f.queued.request.headers!["if-match"],
    expected: { kind: "run", template: f.created.data },
  };
  return {
    f,
    createScope,
    reviseScope,
    runScope,
    create,
    revise,
    run,
    pendingCreate: {
      ...create,
      key: f.created.request.headers!["idempotency-key"],
    } as PendingTaskPackageCommand,
    pendingRevise: {
      ...revise,
      key: f.revised.request.headers!["idempotency-key"],
    } as PendingTaskPackageCommand,
    pendingRun: {
      ...run,
      key: f.queued.request.headers!["idempotency-key"],
    } as PendingTaskPackageCommand,
  };
}
