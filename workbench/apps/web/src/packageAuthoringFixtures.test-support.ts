import actual from "./test-fixtures/task-package-authoring-http.json";
import type {
  AssistantAction,
  Bid,
  PackageAuthoringInputContext,
  PackageAuthoringInputPage,
  PackageAuthoringInputView,
  RunView,
  TaskKindPage,
  TemplateVersionView,
  TemplateView,
  Operation,
  TaskDraftView,
  TaskDraftRequest,
  TemplateRequest,
} from "./contracts";
import type {
  TaskPackageCommandRequest,
  TaskPackageScope,
} from "./taskPackageProtocol";

/** Unmodified API response values from isolated PostgreSQL/S3 execution with
 * synthetic originals and a local model HTTP fixture; no paid model request.
 * The source receipt hashes identify extraction, not production qualification.
 */
export function packageAuthoringFixture() {
  return structuredClone(actual) as unknown as {
    member_id: string;
    bid: Bid;
    bid_etag: string;
    input: PackageAuthoringInputView;
    input_page: PackageAuthoringInputPage;
    context: PackageAuthoringInputContext;
    kinds: TaskKindPage;
    template: TemplateView;
    template_etag: string;
    template_version: TemplateVersionView;
    proposal: AssistantAction;
    proposal_etag: string;
    accepted_run: RunView;
    draft: {
      member_id: string;
      bid: Bid;
      bid_etag: string;
      input: PackageAuthoringInputView;
      input_page: PackageAuthoringInputPage;
      context: PackageAuthoringInputContext;
      kinds: TaskKindPage;
      template: TemplateView;
      template_etag: string;
      template_version: TemplateVersionView;
      task_draft_flow: {
        created: NativeCommandResponse<TaskDraftView, TaskDraftRequest>;
        revised: NativeCommandResponse<TaskDraftView, TemplateRequest>;
        saved: NativeCommandResponse<TemplateView, Record<string, never>>;
        final: { body: TaskDraftView; status: number; etag: string };
      };
    };
    runs: Record<
      | "queued"
      | "awaiting-publication"
      | "published"
      | "unknown-fee"
      | "cancelled-before"
      | "cancelled-during_http",
      RunView
    >;
    operations: Record<string, { data: Operation; etag: string }>;
    scenarios: Record<
      string,
      {
        bid: Bid;
        bid_etag: string;
        input: PackageAuthoringInputView;
        context: PackageAuthoringInputContext;
        kinds: TaskKindPage;
        template: TemplateView;
        template_etag: string;
        template_version: TemplateVersionView;
      }
    >;
  };
}
type NativeCommandResponse<T, R> = {
  request: R;
  if_match: string;
  body: T;
  status: number;
  etag: string;
  replay_body: T;
};
export function packageAuthoringCommandFixture() {
  const f = packageAuthoringFixture();
  const common = { memberId: f.member_id, bidId: f.template.bid_id };
  const createScope: TaskPackageScope<"authoring_template"> = {
    ...common,
    kind: "authoring_template",
    identity: "new",
  };
  const runScope: TaskPackageScope<"authoring_run"> = {
    ...common,
    kind: "authoring_run",
    identity: f.template.id,
  };
  const create: TaskPackageCommandRequest = {
    path: `/bids/${common.bidId}/task-definitions`,
    method: "POST",
    etag: f.bid_etag,
    body: f.template.configuration,
    expected: {
      kind: "authoring_template",
      request: f.template.configuration,
      previous: null,
    },
  };
  const run: TaskPackageCommandRequest = {
    path: `/bids/${common.bidId}/task-definitions/${f.template.id}/runs`,
    method: "POST",
    etag: f.template_etag,
    body: { rerun: false },
    expected: { kind: "authoring_run", template: f.template },
  };
  return { f, createScope, runScope, create, run };
}
