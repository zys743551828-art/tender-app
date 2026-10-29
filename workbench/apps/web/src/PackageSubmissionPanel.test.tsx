import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { PackageSubmissionPanel } from "./PackageSubmissionPanel";
import { SubmissionPanel } from "./SubmissionPanel";
import { workContextFixture } from "../qa-previews/frozen-inputs/workContext";
import { jsonDigest } from "./editorSchema";
import type {
  PackageSubmissionAppliedView,
  PackageSubmissionRequest,
  SubmissionView,
} from "./contracts";
import { clearRecordedCommands } from "./recordedCommandStorage";
import { submissionPreflightFixture } from "./packageSubmissionPreflightFixtures.test-support";
import {
  packageSubmissionBase,
  submissionRunPath,
  type PendingPackageSubmission,
} from "./packageSubmissionProtocol";
import {
  packageSubmissionStorageKey,
  readPackageSubmissionRecovery,
} from "./packageSubmissionRecovery";
import {
  submissionFixture,
  submissionReceipt,
  submissionScope,
  submissionEtag,
  submissionId as id,
  singleSubmission,
  submissionRunFixture,
  type SubmissionFixture,
} from "./packageSubmissionFixtures.test-support";
const response = (
  value: unknown,
  status = 200,
  headers: Record<string, string> = {},
) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
type Write = { path: string; body: PackageSubmissionRequest; headers: Headers };
async function setup(fixture?: SubmissionFixture) {
  const f = fixture ?? (await submissionFixture());
  const base = `/api/v1${packageSubmissionBase(submissionScope.bidId, f.body.selection)}`;
  const server = {
    f,
    base,
    reads: [] as string[],
    writes: [] as Write[],
    previews: [] as unknown[],
    records: [] as SubmissionView[],
    preview: structuredClone(f.preview),
    onWrite: null as ((w: Write) => Promise<Response>) | null,
    onPreview: null as
      | ((body: unknown, count: number) => Promise<Response>)
      | null,
    onRead: null as ((path: string) => Response | null) | null,
  };
  const receipts = new Map<string, PackageSubmissionAppliedView>();
  async function accept(w: Write) {
    const key = w.headers.get("Idempotency-Key")!;
    let ack = receipts.get(key);
    if (!ack) {
      const pending: PendingPackageSubmission = {
        key,
        body: w.body,
        etag: w.headers.get("If-Match")!,
        supersedesId: w.body.expected_head?.id ?? null,
      };
      ack = await submissionReceipt(f, pending, 100 + receipts.size * 2);
      receipts.set(key, ack);
      server.records = [
        ack.submission,
        ...server.records.map((s) => ({ ...s, current: false })),
      ];
    }
    return response(ack, 201, { "X-Bid-ETag": submissionEtag(2) });
  }
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const path = String(input);
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        if (path.endsWith("/submission-preview")) {
          server.previews.push(body);
          return server.onPreview
            ? server.onPreview(body, server.previews.length)
            : response(server.preview);
        }
        const w = { path, body, headers: new Headers(init.headers) };
        server.writes.push(w);
        return server.onWrite ? server.onWrite(w) : accept(w);
      }
      server.reads.push(path);
      const overridden = server.onRead?.(path);
      if (overridden) return overridden;
      if (path.includes("/submission-documents"))
        return response({ items: [f.doc], has_more: false, next_cursor: null });
      if (
        path ===
        `/api/v1/bids/${submissionScope.bidId}/packages?kind=bid&limit=20`
      )
        return response({
          items: [
            {
              id: f.target.manifest.package_id,
              bid_id: submissionScope.bidId,
              kind: "bid",
              revision_id: f.target.manifest.revision_id,
              revision: 1,
              digest: f.target.digest,
            },
          ],
          has_more: false,
          next_cursor: null,
        });
      if (
        path ===
        `/api/v1/bids/${submissionScope.bidId}/packages/${f.target.manifest.package_id}/revisions?limit=20`
      )
        return response({
          items: [
            {
              id: f.target.manifest.revision_id,
              package_id: f.target.manifest.package_id,
              revision: 1,
              digest: f.target.digest,
              created_at: "2025-01-01T00:00:00Z",
            },
          ],
          has_more: false,
          next_cursor: null,
        });
      if (path === base) return response(f.target);
      if (path === base + "/requirement-inventories")
        return response({
          items: f.selection.inventory
            ? [
                {
                  id: f.selection.inventory.manifest.id,
                  digest: f.selection.inventory.digest,
                  created_at: "2025-01-01T00:00:00Z",
                },
              ]
            : [],
          current_inventory_id: f.selection.inventory?.manifest.id ?? null,
          has_more: false,
          next_cursor: null,
        });
      if (
        path ===
        base + `/requirement-inventories/${f.selection.inventory?.manifest.id}`
      )
        return response(f.selection.inventory);
      if (path.endsWith("/coverage-attempts"))
        return response({ items: [], has_more: false, next_cursor: null });
      if (path.includes("/knowledge-reference-targets"))
        return response({
          bid_id: submissionScope.bidId,
          items: [],
          next_offset: null,
          reference_only: true,
          changes_frozen_result: false,
          formal_score_allowed: false,
        });
      if (path.endsWith("/submission-gate"))
        return response({
          allowed: false,
          bid_revision: 1,
          body_version_id: null,
          blockers: [],
          review_id: null,
          material_revision: 1,
          current_identity_digest: "a".repeat(64),
          current_review_manifest_digest: null,
          pending_core_rule_ids: [],
          blocking_finding_ids: [],
          warnings: [],
        });
      if (path === `/api/v1/bids/${submissionScope.bidId}/submissions?limit=20`)
        return response({
          items: server.records,
          has_more: false,
          next_cursor: null,
        });
      const record = server.records.find(
        (s) => path === `/api/v1/submissions/${s.id}`,
      );
      if (record) return response(record);
      throw new Error(`Unexpected GET ${path}`);
    }),
  );
  return { ...server, server, accept };
}
const props = () => ({
  bidId: submissionScope.bidId,
  memberId: submissionScope.memberId,
  disabled: false,
  hasCurrent: false,
  request: null,
  onLock: vi.fn(),
  onSaved: vi.fn(),
});
async function choosePackage(f: SubmissionFixture) {
  const user = userEvent.setup();
  await user.selectOptions(
    await screen.findByLabelText("投标资料包"),
    f.target.manifest.package_id,
  );
  await waitFor(() =>
    expect(
      screen.getByRole("option", { name: /修订 1 ·/ }),
    ).toBeInTheDocument(),
  );
  await user.selectOptions(
    screen.getByLabelText("固定包修订"),
    f.target.manifest.revision_id,
  );
  await screen.findByText("已选修订 1");
  if (f.selection.inventory) {
    await waitFor(() =>
      expect(
        within(screen.getByLabelText("关联需求清单")).getByRole("option", {
          name: /清单 20000000/,
        }),
      ).toBeInTheDocument(),
    );
    await user.selectOptions(
      screen.getByLabelText("关联需求清单"),
      f.selection.inventory.manifest.id,
    );
  }
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "读取所选整包的提交检查" }),
    ).toBeEnabled(),
  );
}
async function prepareForm(f: SubmissionFixture, open = true) {
  const user = userEvent.setup();
  if (open)
    await user.click(
      screen.getByRole("button", { name: "检查并登记整包线下事实" }),
    );
  await choosePackage(f);
  await user.click(
    screen.getByRole("button", { name: "读取所选整包的提交检查" }),
  );
  await screen.findByRole("heading", { name: "3. 据实登记已发生的提交" });
  fireEvent.change(screen.getByLabelText("真实提交时间（ISO 格式，含时区）"), {
    target: { value: f.body.submitted_at },
  });
  await user.selectOptions(
    screen.getByLabelText("本项目提交声明附件"),
    f.doc.document_version_id,
  );
  fireEvent.change(
    screen.getByLabelText("未经过完整检查的原因与已发生事实依据"),
    { target: { value: f.body.explanation } },
  );
}
async function agree() {
  await userEvent
    .setup()
    .click(screen.getByRole("checkbox", { name: /我已核对固定整包/ }));
}
beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("在实际整包表单触发原件复核但不登记事实，重读检查清除旧回执", async () => {
  const f = await submissionFixture(true);
  const proof = await submissionPreflightFixture(false);
  const s = await setup(f),
    p = props();
  s.server.onWrite = async (w) => {
    expect(w.path).toBe(s.base + "/submission-preflight");
    expect(w.headers.get("If-Match")).toBe(s.f.preview.bid_etag);
    expect(w.body).toEqual({
      selection: s.f.preview.selection_request,
      input_digest: s.f.preview.input_digest,
    });
    return response(proof.result);
  };
  render(<PackageSubmissionPanel {...p} />);
  await prepareForm(s.f);
  expect(s.server.writes).toHaveLength(0);
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "核验所选整包原件" }));
  await screen.findByText("本次原件核验已完成");
  expect(s.server.writes).toHaveLength(1);
  expect(s.server.records).toHaveLength(0);
  expect(p.onSaved).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "标准登记不可用" })).toBeDisabled();
  expect(
    within(
      screen.getByRole("region", { name: "原件与运行依据复核" }),
    ).getByText("标准登记仍未获准。清单语义完整性与核查质量仍需证明。"),
  ).toBeVisible();
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "读取所选整包的提交检查" }));
  await waitFor(() =>
    expect(screen.queryByText("本次原件核验已完成")).not.toBeInTheDocument(),
  );
  expect(s.server.writes).toHaveLength(1);
  expect(s.server.records).toHaveLength(0);
  expect(
    await screen.findByLabelText("真实提交时间（ISO 格式，含时区）"),
  ).toHaveValue(s.f.body.submitted_at);
  expect(screen.queryByText("本次原件核验已完成")).not.toBeInTheDocument();
});

it("确切包四门检查后只能明确线下登记；保存前重读并使用原head条件", async () => {
  const s = await setup(),
    p = props();
  render(<PackageSubmissionPanel {...p} />);
  await prepareForm(s.f);
  expect(s.server.writes).toHaveLength(0);
  expect(s.server.previews).toHaveLength(1);
  expect(screen.getByRole("button", { name: "标准登记不可用" })).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "确认登记整包线下事实" }),
  ).toBeDisabled();
  expect(screen.getByText("当前输入与来源")).toBeVisible();
  expect(screen.getByText("全项目已知阻断风险")).toBeVisible();
  await agree();
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "确认登记整包线下事实" }));
  await waitFor(() => expect(p.onSaved).toHaveBeenCalledTimes(1));
  expect(s.server.previews).toHaveLength(2);
  expect(s.server.writes).toHaveLength(1);
  expect(s.server.writes[0].headers.get("If-Match")).toBe(submissionEtag());
  expect(s.server.writes[0].body).toEqual(s.f.body);
  expect(readPackageSubmissionRecovery(submissionScope).pending).toBeNull();
});
it("保存前头变化不发登记，不悄悄采用新ETag，输入保留", async () => {
  const s = await setup();
  s.server.onPreview = async (_, count) =>
    response({
      ...s.f.preview,
      bid_etag: count > 1 ? submissionEtag(3) : submissionEtag(),
    });
  render(<PackageSubmissionPanel {...props()} />);
  await prepareForm(s.f);
  await agree();
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "确认登记整包线下事实" }));
  await screen.findByText(/保存前项目、来源或实交头发生变化/);
  expect(s.server.writes).toHaveLength(0);
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "读取所选整包的提交检查" }));
  await waitFor(() =>
    expect(
      screen.getByLabelText("真实提交时间（ISO 格式，含时区）"),
    ).toHaveValue(s.f.body.submitted_at),
  );
  expect(
    screen.getByRole("checkbox", { name: /我已核对固定整包/ }),
  ).not.toBeChecked();
});
it("提交已成功但ACK丢失，刷新后仍用同一body/key/etag恢复，不以历史取代回执", async () => {
  const s = await setup(),
    p = props();
  let lost = false;
  s.server.onWrite = async (w) => {
    const r = await s.accept(w);
    if (!lost) {
      lost = true;
      throw new Error("lost ACK");
    }
    return r;
  };
  const v = render(<PackageSubmissionPanel {...p} />);
  await prepareForm(s.f);
  await agree();
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "确认登记整包线下事实" }));
  await screen.findByText("整包登记结果尚未核对");
  expect(readPackageSubmissionRecovery(submissionScope).pending).not.toBeNull();
  expect(p.onSaved).not.toHaveBeenCalled();
  const first = s.server.writes[0];
  v.unmount();
  render(<PackageSubmissionPanel {...p} hasCurrent />);
  expect(
    screen.getByRole("button", { name: "读取所选整包的提交检查" }),
  ).toBeDisabled();
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "恢复原整包登记结果" }));
  await waitFor(() => expect(p.onSaved).toHaveBeenCalledTimes(1));
  expect(s.server.writes).toHaveLength(2);
  expect(s.server.writes[1].body).toEqual(first.body);
  expect(s.server.writes[1].headers.get("Idempotency-Key")).toBe(
    first.headers.get("Idempotency-Key"),
  );
  expect(s.server.writes[1].headers.get("If-Match")).toBe(
    first.headers.get("If-Match"),
  );
  expect(s.server.previews).toHaveLength(2);
  expect(readPackageSubmissionRecovery(submissionScope).pending).toBeNull();
});
it.each(["wrong-actor", "missing-header", "generic-422"])(
  "%s 保留原命令并锁住新登记",
  async (mode) => {
    const s = await setup(),
      p = props();
    s.server.onWrite = async (w) => {
      if (mode === "generic-422")
        return response(
          { code: "PACKAGE_SUBMISSION_INVALID", message: "未知校验" },
          422,
        );
      const r = await s.accept(w),
        value = await r.json();
      if (mode === "wrong-actor") value.command.actor_id = id(999);
      return response(
        value,
        201,
        mode === "missing-header" ? {} : { "X-Bid-ETag": submissionEtag(2) },
      );
    };
    render(<PackageSubmissionPanel {...p} />);
    await prepareForm(s.f);
    await agree();
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "确认登记整包线下事实" }));
    await screen.findByText("整包登记结果尚未核对");
    expect(
      readPackageSubmissionRecovery(submissionScope).pending,
    ).not.toBeNull();
    expect(p.onSaved).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "收起整包登记" })).toBeDisabled();
  },
);
it("本地恢复记录写不下时不发送登记，表单不丢失", async () => {
  const s = await setup();
  render(<PackageSubmissionPanel {...props()} />);
  await prepareForm(s.f);
  await agree();
  const original = Storage.prototype.setItem;
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (
    this: Storage,
    k,
    v,
  ) {
    if (k.includes("package-submission")) throw new Error("quota");
    return original.call(this, k, v);
  });
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "确认登记整包线下事实" }));
  await screen.findByText(/浏览器无法保存整包登记恢复记录/);
  expect(s.server.writes).toHaveLength(0);
  expect(
    screen.getByLabelText("未经过完整检查的原因与已发生事实依据"),
  ).toHaveValue(s.f.body.explanation);
});
it("明确CAS拒绝结束pending但保留输入，新检查需重新确认", async () => {
  const s = await setup();
  s.server.onWrite = async () =>
    response({ code: "REVISION_CONFLICT", message: "实交头已变化" }, 412);
  render(<PackageSubmissionPanel {...props()} />);
  await prepareForm(s.f);
  await agree();
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "确认登记整包线下事实" }));
  await screen.findByText(/服务已明确拒绝本次登记/);
  expect(readPackageSubmissionRecovery(submissionScope).pending).toBeNull();
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "读取所选整包的提交检查" }));
  await waitFor(() =>
    expect(
      screen.getByLabelText("未经过完整检查的原因与已发生事实依据"),
    ).toHaveValue(s.f.body.explanation),
  );
  expect(
    screen.getByRole("checkbox", { name: /我已核对固定整包/ }),
  ).not.toBeChecked();
  expect(s.server.writes).toHaveLength(1);
});
it("原恢复记录损坏时阻止新写，不当作空白登记", () => {
  sessionStorage.setItem(
    packageSubmissionStorageKey(submissionScope),
    "{broken",
  );
  render(<PackageSubmissionPanel {...props()} />);
  expect(screen.getByText(/本地整包提交恢复记录损坏/)).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "检查并登记整包线下事实" }),
  ).not.toBeInTheDocument();
});
it("未知ACK在退出后的迟到响应不会重建已清除的账户恢复记录", async () => {
  const s = await setup(),
    p = props();
  let complete: ((r: Response) => void) | undefined;
  let originalResponse: Response | undefined;
  s.server.onWrite = async (w) => {
    originalResponse = await s.accept(w);
    return new Promise<Response>((resolve) => {
      complete = resolve;
    });
  };
  const v = render(<PackageSubmissionPanel {...p} />);
  await prepareForm(s.f);
  await agree();
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "确认登记整包线下事实" }));
  await waitFor(() => expect(complete).toBeTypeOf("function"));
  v.unmount();
  clearRecordedCommands();
  await act(async () => {
    complete!(originalResponse!);
    await new Promise((r) => setTimeout(r, 0));
  });
  expect(
    sessionStorage.getItem(packageSubmissionStorageKey(submissionScope)),
  ).toBeNull();
  expect(p.onSaved).not.toHaveBeenCalled();
});
it("运行目录能继续分页，只显示匹配清单并读取确切frozen/prepared运行", async () => {
  const f = await submissionFixture(true),
    s = await setup(f),
    { run, target } = submissionRunFixture(f);
  const other = { ...target, id: id(200), inventory_id: id(201) };
  s.server.onRead = (path) => {
    if (path.includes("knowledge-reference-targets"))
      return response({
        bid_id: submissionScope.bidId,
        items: path.includes("offset=1") ? [target] : [other],
        next_offset: path.includes("offset=1") ? null : 1,
        reference_only: true,
        changes_frozen_result: false,
        formal_score_allowed: false,
      });
    if (path === `/api/v1${submissionRunPath(submissionScope.bidId, target)}`)
      return response(run);
    return null;
  };
  render(<PackageSubmissionPanel {...props()} />);
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "检查并登记整包线下事实" }));
  await choosePackage(f);
  await screen.findByText(/已读取页面中尚无匹配运行/);
  expect(
    within(screen.getByLabelText("关联整包核查")).getAllByRole("option"),
  ).toHaveLength(1);
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "加载更多核查运行" }));
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("关联整包核查")).getAllByRole("option"),
    ).toHaveLength(2),
  );
  await userEvent
    .setup()
    .selectOptions(screen.getByLabelText("关联整包核查"), run.id);
  await screen.findByText("核对核查的固定输入链");
  expect(screen.getByText(/所选运行尚无完整报告/)).toBeInTheDocument();
  expect(
    s.server.reads.some((path) => path.includes("/package-next-actions/")),
  ).toBe(false);
  expect(s.server.reads).toContain(
    `/api/v1${submissionRunPath(submissionScope.bidId, target)}`,
  );
  expect(s.server.writes).toHaveLength(0);
});
it("混入另一个原输入的run响应不开放登记检查", async () => {
  const f = await submissionFixture(true),
    s = await setup(f),
    { run, target } = submissionRunFixture(f);
  s.server.onRead = (path) =>
    path.includes("knowledge-reference-targets")
      ? response({
          bid_id: submissionScope.bidId,
          items: [target],
          next_offset: null,
          reference_only: true,
          changes_frozen_result: false,
          formal_score_allowed: false,
        })
      : path.includes("/review-runs/")
        ? response({ ...run, execution_input_id: id(999) })
        : null;
  render(<PackageSubmissionPanel {...props()} />);
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "检查并登记整包线下事实" }));
  await choosePackage(f);
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("关联整包核查")).getAllByRole("option"),
    ).toHaveLength(2),
  );
  await userEvent
    .setup()
    .selectOptions(screen.getByLabelText("关联整包核查"), run.id);
  await screen.findByText(/整包提交的项目、固定来源、摘要或原操作回执不一致/);
  expect(
    screen.getByRole("button", { name: "读取所选整包的提交检查" }),
  ).toBeDisabled();
  expect(s.server.previews).toHaveLength(0);
});
it("完整报告的明确选择显示同源待办，取消关联立即收起且不发送登记", async () => {
  const f = await submissionFixture(true),
    s = await setup(f);
  const run = (await workContextFixture()).completed;
  run.scope = submissionRunFixture(f).run.scope;
  run.result!.manifest.scope = run.scope;
  run.result!.digest = await jsonDigest(run.result!.manifest);
  const target = {
    ...submissionRunFixture(f).target,
    id: run.id,
    input_digest: run.input_digest,
    execution_input_id: run.execution_input_id,
    frozen_input_id: run.frozen_input_id,
    state: run.operation.state,
    result_digest: run.result!.digest,
  };
  const actionPath = `/api/v1/bids/${submissionScope.bidId}/package-next-actions/${run.id}?expected_input_digest=${run.input_digest}`;
  s.server.onRead = (path) => {
    if (path.includes("knowledge-reference-targets"))
      return response({
        bid_id: submissionScope.bidId,
        items: [target],
        next_offset: null,
        reference_only: true,
        changes_frozen_result: false,
        formal_score_allowed: false,
      });
    if (path === `/api/v1${submissionRunPath(submissionScope.bidId, target)}`)
      return response(run);
    if (path === actionPath)
      return response({
        version: "package-next-actions/1",
        binding: {
          scope: run.scope,
          run_id: run.id,
          input_digest: run.input_digest,
          result_digest: run.result!.digest,
          frozen_input_id: run.frozen_input_id,
          frozen_input_digest: run.frozen_input_digest,
          execution_input_id: run.execution_input_id,
          execution_input_digest: run.execution_input_digest,
          dependency_plan_id: run.dependency_plan_id,
          dependency_plan_digest: run.dependency_plan_digest,
          method_digest: run.method_digest,
        },
        method_digest: "a".repeat(64),
        confirmation_digest: "b".repeat(64),
        basis_digest: "c".repeat(64),
        observation_digest: "d".repeat(64),
        observed_at: "2026-10-23T12:00:00Z",
        basis_status: "matched",
        basis_issues: [],
        current_scope_counts: {
          critical: 1,
          suggestions: 0,
          pending_critical_rules: 0,
        },
        historical_scope_counts: { critical: 1, suggestions: 0 },
        primary: {
          level: 3,
          key: "inspect_critical_risks",
          title: "检查本次所选报告的问题",
          item_count: 1,
          requirement_ids: [run.result!.manifest.matrix[1].requirement_id],
        },
        other_actions: [],
        remaining_critical_count: 0,
        remaining_suggestion_count: 0,
        action_mode: "navigation_only",
        perspective: "selected_declared_scope",
        original_bytes_reverified: false,
        inventory_complete: false,
        formal_scoring_eligible: false,
        submission_eligible: false,
      });
    return null;
  };
  render(<PackageSubmissionPanel {...props()} />);
  const user = userEvent.setup();
  await user.click(
    screen.getByRole("button", { name: "检查并登记整包线下事实" }),
  );
  await choosePackage(f);
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("关联整包核查")).getAllByRole("option"),
    ).toHaveLength(2),
  );
  await user.selectOptions(screen.getByLabelText("关联整包核查"), run.id);
  await screen.findByRole("button", { name: "检查本次所选报告的问题（1项）" });
  expect(s.server.reads).toContain(actionPath);
  await user.selectOptions(screen.getByLabelText("关联整包核查"), "");
  await waitFor(() =>
    expect(
      screen.queryByRole("region", { name: "本次登记所选核查的下一步" }),
    ).not.toBeInTheDocument(),
  );
  expect(s.server.writes).toHaveLength(0);
});
it("统一历史保留无subject_kind旧单稿，明确整包更正走新路由与统一head", async () => {
  const f = await submissionFixture(false, {
      id: id(120),
      revision: 3,
      subject_kind: "single_body",
    }),
    s = await setup(f);
  s.server.records = [singleSubmission(f)];
  render(
    <SubmissionPanel
      bidId={submissionScope.bidId}
      memberId={submissionScope.memberId}
      onNavigate={vi.fn()}
      onChanged={vi.fn()}
    />,
  );
  await screen.findByText("旧单稿实际提交.pdf");
  expect(
    screen.getByRole("button", { name: "检查并登记整包线下事实" }),
  ).toBeDisabled();
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "按完整整包追加更正" }));
  await prepareForm(f, false);
  fireEvent.change(screen.getByLabelText("本次追加更正理由"), {
    target: { value: f.body.correction_reason },
  });
  await agree();
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "确认追加整包更正" }));
  await screen.findByText("整包实际提交 · 修订 1");
  expect(s.server.writes[0].path).toBe(
    `/api/v1/submissions/${id(120)}/package-corrections`,
  );
  expect(s.server.writes[0].body.expected_head).toEqual({
    id: id(120),
    revision: 3,
  });
  expect(screen.getByText("旧单稿实际提交.pdf")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "追加更正此实交记录" }),
  ).not.toBeInTheDocument();
});
it("整包历史不使用null正文下载入口，挂载共享实交结果且与旧编辑统一互锁", async () => {
  const f = await submissionFixture(),
    s = await setup(f),
    pending = {
      key: id(77),
      body: f.body,
      etag: submissionEtag(),
      supersedesId: null,
    };
  const ack = await submissionReceipt(f, pending);
  s.server.records = [ack.submission];
  render(
    <SubmissionPanel
      bidId={submissionScope.bidId}
      memberId={submissionScope.memberId}
      onNavigate={vi.fn()}
      onChanged={vi.fn()}
    />,
  );
  await screen.findByText("整包实际提交 · 修订 1");
  expect(
    screen.queryByRole("button", { name: "下载此记录的实际提交稿" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "登记／查看此实交的实际结果" }),
  ).toBeInTheDocument();
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "追加更正此整包实交记录" }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "补录线下已发生的提交" }),
    ).toBeDisabled(),
  );
  expect(screen.getByLabelText("投标资料包")).toHaveValue(
    f.body.selection.package_id,
  );
});
