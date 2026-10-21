import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { setAuth } from "./api";
import { TaskTemplateEditor } from "./TaskTemplateEditor";
import { TaskTemplateCard } from "./TaskTemplateCard";
import {
  TaskPackageTriggerDetail,
  TaskPackageTriggerPanel,
} from "./TaskPackageTriggerPanel";
import { TaskPanel } from "./TaskPanel";
import { TaskDraftPanel } from "./TaskDraftPanel";
import { ExactPackageTaskDraftStart } from "./ExactPackageTaskDraftStart";
import { jsonDigest } from "./editorSchema";
import { taskTriggerFixtures } from "./taskTriggerFixtures.test-support";
import { taskPackageStorageKey } from "./useTaskPackageCommand";
import type { TaskPackageHTTPFixture } from "./taskPackageFixtures.test-support";
import type {
  TaskDraftRequest,
  TaskDraftView,
  TemplateRequest,
} from "./taskTriggerContracts";

const f = taskTriggerFixtures();
const memberId = String(f["event-succeeded-run"].data.frozen_manifest.actor_id);
function json(
  value: unknown,
  status = 200,
  headers: Record<string, string> = {},
) {
  return new Response(JSON.stringify(value), { status, headers });
}
function reply(
  record: TaskPackageHTTPFixture<unknown>,
  status = record.status,
) {
  return json(record.data, status, record.headers);
}
function transport(
  read: (url: URL) => Response,
  write?: (url: URL, init: RequestInit) => Response | Promise<Response>,
) {
  const requests: { url: URL; init: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init: RequestInit = {}) => {
      const url = new URL(path, window.location.href);
      requests.push({ url, init });
      if (init.method && init.method !== "GET")
        return write
          ? write(url, init)
          : json({ code: "UNEXPECTED_WRITE" }, 500);
      if (url.pathname.endsWith("/task-kinds")) return reply(f["task-kinds"]);
      return read(url);
    }),
  );
  return requests;
}
beforeEach(() => {
  sessionStorage.clear();
  window.history.replaceState(
    {},
    "",
    `/bids/${f["event-template"].data.bid_id}/tasks`,
  );
  setAuth({
    member: { id: memberId, display_name: "合成触发验收", active: true },
    csrf_token: "synthetic",
    expires_at: "2099-01-01T00:00:00Z",
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it.each([
  ["material_updated", "event-template"],
  ["schedule", "schedule-template"],
] as const)(
  "explicitly opts into %s after the fixed input, and saves only a template",
  async (mode, name) => {
    const record = f[name],
      template = record.data,
      config = template.configuration;
    const source = config.source_selection!;
    if (!("input" in source) || source.mode === "exact_package_authoring")
      throw new Error("fixture exact review source");
    const initial: TemplateRequest = {
      ...config,
      source_selection: { mode: "exact_package_review", input: source.input },
      trigger: { mode: "manual", cron: null, timezone: "Asia/Shanghai" },
    };
    const requests = transport(
      () => json({ code: "UNEXPECTED_READ" }, 404),
      () => reply(record),
    );
    const onSaved = vi.fn(),
      user = userEvent.setup();
    render(
      <TaskTemplateEditor
        bidId={template.bid_id}
        memberId={memberId}
        template={null}
        etag={record.request.headers!["if-match"]}
        initialConfiguration={initial}
        formIdentity={`package:${source.input.execution_input_id}:${source.input.dependency_plan_id}`}
        onSaved={onSaved}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("触发方式")).toHaveValue("manual");
    await waitFor(() =>
      expect(
        screen.getByRole("option", { name: "按计划核对这份输入" }),
      ).toBeEnabled(),
    );
    await user.selectOptions(screen.getByLabelText("触发方式"), mode);
    if (mode === "schedule") {
      expect(screen.getByLabelText("定时表达式")).toHaveValue("0 9 * * *");
      expect(screen.getByLabelText("计划时区")).toHaveValue("Asia/Shanghai");
    }
    expect(
      screen.queryByRole("combobox", { name: "来源范围" }),
    ).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "保存任务模板，不运行" }),
    );
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(template));
    const writes = requests.filter(({ init }) => init.method !== "GET");
    expect(writes).toHaveLength(1);
    expect(JSON.parse(String(writes[0].init.body))).toEqual(config);
    expect(
      requests.some(({ url }) => /\/(materials|runs)$/.test(url.pathname)),
    ).toBe(false);
  },
);

it("shows an automatic template as an exact input and exposes no new manual run action", async () => {
  const template = f["event-template"].data;
  const requests = transport(() => reply(f["event-template"], 200));
  render(
    <TaskTemplateCard
      bidId={template.bid_id}
      memberId={memberId}
      id={template.id}
      kinds={f["task-kinds"].data}
      onChanged={vi.fn()}
      onRun={vi.fn()}
    />,
  );
  await screen.findByText(/只唤醒本模板已保存的确切输入/);
  expect(
    screen.queryByRole("button", { name: /手动运行/ }),
  ).not.toBeInTheDocument();
  await userEvent.click(
    screen.getByRole("button", { name: "修改并保存新版本" }),
  );
  expect(await screen.findByLabelText("触发方式")).toHaveValue(
    "material_updated",
  );
  expect(requests.every(({ init }) => init.method === "GET")).toBe(true);
});

it("recovers a lost cancel ACK after remount with the original body, key and ETag while current GET is already cancelled", async () => {
  const pending = f["cancel-pending"],
    cancelled = f.cancelled;
  let current = pending,
    attempts = 0;
  const writes: RequestInit[] = [];
  transport(
    () => json(current.data, 200, pending.headers),
    async (_url, init) => {
      writes.push(init);
      attempts++;
      if (attempts === 1) {
        current = cancelled;
        throw new Error("synthetic ACK lost");
      }
      return reply(cancelled);
    },
  );
  const props = {
    bidId: pending.data.bid_id,
    memberId,
    id: pending.data.id,
    onRun: vi.fn(),
    onChanged: vi.fn(),
  };
  const key = taskPackageStorageKey({
    kind: "trigger_cancel",
    memberId,
    bidId: props.bidId,
    identity: props.id,
  });
  const view = render(<TaskPackageTriggerDetail {...props} />);
  await userEvent.type(
    await screen.findByLabelText("取消本次触发的原因"),
    "明确取消这次原输入触发",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "取消这次尚未运行的触发" }),
  );
  await screen.findByRole("button", { name: "恢复原取消请求结果" });
  expect(sessionStorage.getItem(key)).not.toBeNull();
  view.unmount();
  render(<TaskPackageTriggerDetail {...props} />);
  await screen.findByText("已取消本次触发");
  await userEvent.click(
    await screen.findByRole("button", { name: "恢复原取消请求结果" }),
  );
  await waitFor(() => expect(sessionStorage.getItem(key)).toBeNull());
  expect(writes).toHaveLength(2);
  expect(writes[1].body).toBe(writes[0].body);
  expect(new Headers(writes[1].headers).get("Idempotency-Key")).toBe(
    new Headers(writes[0].headers).get("Idempotency-Key"),
  );
  expect(new Headers(writes[1].headers).get("If-Match")).toBe(
    pending.headers.etag,
  );
  expect(props.onChanged).toHaveBeenCalledTimes(1);
  expect(props.onRun).not.toHaveBeenCalled();
});

it("retains an uncertain cancellation when the response fails the terminal ACK contract", async () => {
  const pending = f["cancel-pending"];
  const requests = transport(
    () => reply(pending),
    () => json(pending.data),
  );
  const key = taskPackageStorageKey({
    kind: "trigger_cancel",
    memberId,
    bidId: pending.data.bid_id,
    identity: pending.data.id,
  });
  const onChanged = vi.fn();
  render(
    <TaskPackageTriggerDetail
      bidId={pending.data.bid_id}
      memberId={memberId}
      id={pending.data.id}
      onRun={vi.fn()}
      onChanged={onChanged}
    />,
  );
  await userEvent.type(
    await screen.findByLabelText("取消本次触发的原因"),
    "明确取消原触发",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "取消这次尚未运行的触发" }),
  );
  await screen.findByRole("button", { name: "恢复原取消请求结果" });
  expect(sessionStorage.getItem(key)).not.toBeNull();
  expect(onChanged).not.toHaveBeenCalled();
  expect(requests.filter(({ init }) => init.method === "POST")).toHaveLength(1);
});

it("keeps the old read-only snapshot and blocks writes if a later intent read changes its fixed source", async () => {
  const pending = f["cancel-pending"];
  let current = structuredClone(pending.data);
  transport(() => json(current, 200, pending.headers));
  render(
    <TaskPackageTriggerDetail
      bidId={pending.data.bid_id}
      memberId={memberId}
      id={pending.data.id}
      onRun={vi.fn()}
      onChanged={vi.fn()}
    />,
  );
  await userEvent.type(
    await screen.findByLabelText("取消本次触发的原因"),
    "核对中的原输入",
  );
  current = {
    ...current,
    selection: { ...current.selection, revision_id: crypto.randomUUID() },
  };
  await act(async () => {
    window.dispatchEvent(new Event("server-snapshot-change"));
  });
  await screen.findByText(/原触发输入或已记录终态发生变化/);
  expect(
    screen.getByRole("button", { name: "取消这次尚未运行的触发" }),
  ).toBeDisabled();
});

it("continues the server cursor when a later intent UUID is smaller, without sending work", async () => {
  const items = f["event-intents"].data.items;
  const requests = transport((url) =>
    json(
      url.searchParams.has("after")
        ? { items: [items[1]], next_after: null }
        : { items: [items[0]], next_after: items[0].id },
    ),
  );
  render(
    <TaskPackageTriggerPanel
      bidId={items[0].bid_id}
      memberId={memberId}
      onRun={vi.fn()}
    />,
  );
  expect(requests).toHaveLength(0);
  await userEvent.click(
    screen.getByRole("button", { name: "整包事件与定时触发记录" }),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "加载更多触发记录" }),
  );
  await waitFor(() =>
    expect(
      screen.getAllByRole("button", { name: /资料事件 · 已关联原生运行/ }),
    ).toHaveLength(2),
  );
  expect(requests[1].url.searchParams.get("after")).toBe(items[0].id);
  expect(requests.every(({ init }) => init.method === "GET")).toBe(true);
});

it("renders skipped exact schedules as reconfirmation and offers no current/latest package run shortcut", async () => {
  const template = f["schedule-template"].data,
    bidId = template.bid_id;
  window.history.replaceState({}, "", `/bids/${bidId}/tasks`);
  const requests = transport((url) => {
    if (url.pathname.endsWith(`/task-definitions/${template.id}`))
      return reply(f["schedule-template"], 200);
    if (url.pathname.endsWith("/task-schedule-recoveries"))
      return reply(f["schedule-missed"]);
    if (url.pathname.endsWith(`/bids/${bidId}`))
      return json({ id: bidId }, 200, {
        etag: f["schedule-template"].request.headers!["if-match"],
      });
    return json({
      items: [],
      has_more: false,
      next_cursor: null,
      next_after: null,
      run_current_once_supported: true,
    });
  });
  render(<TaskPanel bidId={bidId} memberId={memberId} />);
  await userEvent.click(
    screen.getByRole("button", { name: "漏时与计划恢复记录" }),
  );
  await screen.findByText(
    /请核对原模板的确切输入，明确保存为手动模式后再运行一次/,
  );
  expect(
    screen.getByRole("link", { name: "重新核对这份模板的确切输入" }),
  ).toHaveAttribute(
    "href",
    `/bids/${bidId}/tasks?task_template=${template.id}`,
  );
  await act(async () => {
    window.history.pushState(
      {},
      "",
      `/bids/${bidId}/tasks?task_template=${template.id}`,
    );
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await screen.findByText(/只唤醒本模板已保存的确切输入/);
  expect(
    screen.queryByRole("button", { name: /手动运行/ }),
  ).not.toBeInTheDocument();
  expect(requests.every(({ init }) => init.method === "GET")).toBe(true);
});

it("keeps an exact automatic private draft through its explicit update then template-save commands", async () => {
  const template = f["event-template"].data,
    config = template.configuration;
  const id = crypto.randomUUID(),
    bidId = template.bid_id;
  const interpretation = {
    interpreter: "bounded-zh-task-draft/1" as const,
    raw_request: "资料入库后核对这份已选择的整包",
    name: config.name,
    task_kind: config.task_kind,
    instructions: config.instructions,
    section_id: null,
    source_selection: config.source_selection!,
    trigger: config.trigger!,
    target_description: "所选精确投标包、冻结输入、执行准备与依赖计划",
    output_description: "声明范围内核对",
    unresolved: [],
    ready_for_template_form: true,
    template_saved: false as const,
    run_created: false as const,
    formal_decisions_allowed: false as const,
  };
  let draft: TaskDraftView = {
    id,
    bid_id: bidId,
    created_by: memberId,
    revision: 1,
    created_at: "2026-10-21T00:00:00Z",
    updated_at: "2026-10-21T00:00:00Z",
    interpretation,
    configuration_digest: await jsonDigest(interpretation),
    explicitly_edited: false,
    saved_template_id: null,
  };
  window.history.replaceState({}, "", `/bids/${bidId}/tasks?task_draft=${id}`);
  const requests = transport(
    (url) => {
      if (url.pathname.endsWith(`/task-definition-drafts/${id}`))
        return json(draft, 200, {
          etag: `"task-draft:${id}:${draft.revision}"`,
        });
      if (url.pathname.endsWith(`/task-definitions/${template.id}`))
        return reply(f["event-template"], 200);
      return json({ items: [], has_more: false, next_cursor: null });
    },
    (url, init) => {
      if (
        init.method === "PUT" &&
        url.pathname.endsWith(`/task-definition-drafts/${id}`)
      ) {
        expect(JSON.parse(String(init.body))).toEqual(config);
        draft = { ...draft, revision: 2, explicitly_edited: true };
        return json(draft, 200, { etag: `"task-draft:${id}:2"` });
      }
      if (url.pathname.endsWith(`/task-definition-drafts/${id}/save`)) {
        expect(new Headers(init.headers).get("If-Match")).toBe(
          `"task-draft:${id}:2"`,
        );
        draft = { ...draft, revision: 3, saved_template_id: template.id };
        return reply(f["event-template"]);
      }
      throw new Error("unexpected draft write");
    },
  );
  const onSaved = vi.fn();
  render(
    <TaskDraftPanel
      bidId={bidId}
      memberId={memberId}
      bidEtag={f["event-template"].request.headers!["if-match"]}
      onSaved={onSaved}
    />,
  );
  expect(await screen.findByLabelText("触发方式")).toHaveValue(
    "material_updated",
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "保存任务模板，不运行" }),
    ).toBeEnabled(),
  );
  await userEvent.click(
    screen.getByRole("button", { name: "保存任务模板，不运行" }),
  );
  await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
  expect(
    requests
      .filter(({ init }) => init.method !== "GET")
      .map(({ init }) => init.method),
  ).toEqual(["PUT", "POST"]);
  expect(
    requests.some(({ url }) => /\/(materials|runs)$/.test(url.pathname)),
  ).toBe(false);
});

it.each(["valid", "lost-ack", "changed-source"] as const)(
  "creates a private draft only from the original package selection: %s",
  async (mode) => {
    const record = f["event-template"],
      template = record.data;
    const source = template.configuration.source_selection!;
    if (!("input" in source) || source.mode === "exact_package_authoring")
      throw new Error("fixture review source");
    const identity = `package:${source.input.execution_input_id}:${source.input.dependency_plan_id}`;
    const props = {
      bidId: template.bid_id,
      memberId,
      identity,
      configuration: template.configuration,
      etag: record.request.headers!["if-match"],
    };
    const id = crypto.randomUUID(),
      writes: RequestInit[] = [];
    let attempt = 0;
    const requests = transport(
      () => json({ code: "UNEXPECTED_READ" }, 404),
      async (url, init) => {
        expect(url.pathname).toBe(
          `/api/v1/bids/${template.bid_id}/task-definition-drafts`,
        );
        writes.push(init);
        attempt++;
        const body = JSON.parse(String(init.body)) as TaskDraftRequest;
        expect(body).toEqual({
          request: "核查这份整包的否决项",
          section_id: null,
          source_selection: {
            mode: "exact_package_review",
            input: source.input,
          },
        });
        if (mode === "lost-ack" && attempt === 1)
          throw new Error("synthetic ACK lost after draft commit");
        const interpretation = {
          interpreter: "bounded-zh-task-draft/1" as const,
          raw_request: body.request,
          name: "否决核对",
          task_kind: "denial_check" as const,
          instructions: body.request,
          section_id: null,
          source_selection: body.source_selection!,
          trigger: {
            mode: "manual" as const,
            cron: null,
            timezone: "Asia/Shanghai",
          },
          target_description: "所选精确投标包、冻结输入、执行准备与依赖计划",
          output_description: "否决及强制项核对结果与证据",
          unresolved: [],
          ready_for_template_form: true,
          template_saved: false as const,
          run_created: false as const,
          formal_decisions_allowed: false as const,
        };
        if (
          mode === "changed-source" &&
          "input" in interpretation.source_selection &&
          interpretation.source_selection.mode !== "exact_package_authoring"
        )
          interpretation.source_selection.input.frozen_input_id =
            crypto.randomUUID();
        const draft: TaskDraftView = {
          id,
          bid_id: template.bid_id,
          created_by: memberId,
          revision: 1,
          created_at: "2026-10-21T00:00:00Z",
          updated_at: "2026-10-21T00:00:00Z",
          interpretation,
          configuration_digest: await jsonDigest(interpretation),
          explicitly_edited: false,
          saved_template_id: null,
        };
        return json(draft, 201, { etag: `"task-draft:${id}:1"` });
      },
    );
    const user = userEvent.setup();
    const view = render(<ExactPackageTaskDraftStart {...props} />);
    expect(requests).toHaveLength(0);
    await user.click(
      screen.getByRole("button", { name: "先用文字拟定私有草案" }),
    );
    await user.type(
      screen.getByLabelText("这份整包想反复核对什么"),
      "核查这份整包的否决项",
    );
    await user.click(
      screen.getByRole("button", { name: "生成这份输入的私有草案" }),
    );
    if (mode === "lost-ack") {
      await screen.findByRole("button", { name: "恢复原整包草案请求" });
      view.unmount();
      render(<ExactPackageTaskDraftStart {...props} />);
      await user.click(
        await screen.findByRole("button", { name: "恢复原整包草案请求" }),
      );
      expect(writes).toHaveLength(2);
      expect(writes[1].body).toBe(writes[0].body);
      for (const header of ["If-Match", "Idempotency-Key"])
        expect(new Headers(writes[1].headers).get(header)).toBe(
          new Headers(writes[0].headers).get(header),
        );
    }
    if (mode === "changed-source") {
      await screen.findByText(/草案回执与原成员、请求或确切整包输入不一致/);
      expect(
        screen.getByRole("button", { name: "恢复原整包草案请求" }),
      ).toBeEnabled();
      expect(
        screen.queryByRole("link", { name: "打开草案并明确触发方式" }),
      ).not.toBeInTheDocument();
    } else {
      expect(
        await screen.findByRole("link", { name: "打开草案并明确触发方式" }),
      ).toHaveAttribute(
        "href",
        `/bids/${template.bid_id}/tasks?task_draft=${id}`,
      );
    }
    expect(
      requests.every(({ url }) =>
        url.pathname.endsWith("/task-definition-drafts"),
      ),
    ).toBe(true);
  },
);
