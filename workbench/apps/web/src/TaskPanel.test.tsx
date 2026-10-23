import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { setAuth } from "./api";
import { TaskTemplateEditor } from "./TaskTemplateEditor";
import { TaskTemplateCard } from "./TaskTemplateCard";
import { TaskDraftPanel } from "./TaskDraftPanel";
import { TaskRunCard } from "./TaskRunCard";
import { newTaskConfiguration } from "./taskState";
import type {
  TaskDraftView,
  TaskKindPage,
  TemplateView,
} from "./taskTriggerContracts";

const template: TemplateView = {
  id: "template",
  bid_id: "bid",
  revision: 1,
  version_id: "version1",
  digest: "d".repeat(64),
  purpose: "assist",
  paused: false,
  configuration: {
    ...newTaskConfiguration(),
    name: "我的任务",
    instructions: "只核已登记关系",
  },
  next_run_at: null,
  run_created: false,
  active_runs_cancelled: false,
};
const kinds: TaskKindPage = {
  items: [
    {
      task_kind: "supplement_impact",
      name: "登记关系",
      purpose: "assist",
      execution: "partial",
    },
    {
      task_kind: "scoring_review",
      name: "评分",
      purpose: "compliance",
      execution: "unavailable",
      reason: "TASK_SCORING_NOT_QUALIFIED",
    },
  ],
  default_trigger: "manual",
  saving_preset_creates_run: false,
};
const draft: TaskDraftView = {
  id: "draft",
  bid_id: "bid",
  created_by: "member",
  revision: 1,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  interpretation: {
    interpreter: "bounded-zh-task-draft/1",
    raw_request: "每天帮我做点事",
    name: "待明确任务",
    task_kind: null,
    instructions: "待明确工作",
    section_id: null,
    source_selection: { mode: "current_project", version_ids: [] },
    trigger: { mode: "manual", cron: null, timezone: "Asia/Shanghai" },
    target_description: "本项目",
    output_description: "待明确",
    unresolved: [
      { field: "task_kind", reason: "明确任务类型" },
      { field: "trigger", reason: "时间不明确，保留手动" },
    ],
    ready_for_template_form: false,
  },
  configuration_digest: "d".repeat(64),
  explicitly_edited: false,
  saved_template_id: null,
};
function json(value: unknown, status = 200, etag = '"base:1"') {
  return new Response(JSON.stringify(value), {
    status,
    headers: { ETag: etag },
  });
}
function fallback(url: string) {
  const path = new URL(url, window.location.href).pathname;
  if (path.endsWith("/materials"))
    return json({
      bid_id: "bid",
      documents: [
        { id: "document", filename: "可信PDF.pdf", file_revision: 1 },
      ],
    });
  if (path === "/api/v1/bids/bid") return json({ id: "bid" });
  if (path === "/api/v1/task-kinds") return json(kinds);
  if (path.endsWith("/task-definitions/template")) return json(template);
  if (path.endsWith("/task-definition-drafts"))
    return json({ items: [draft], has_more: false, next_cursor: null });
  if (path.endsWith("/assistant/sources"))
    return json({ items: [], coverage: "partial", notice: "可信来源" });
  return json({});
}
beforeEach(() => {
  sessionStorage.clear();
  window.history.replaceState({}, "", "/bids/bid/tasks");
  setAuth({
    member: { id: "member", display_name: "组件夹具", active: true },
    csrf_token: "csrf",
    expires_at: "2099-01-01T00:00:00Z",
  });
});
it("保存模板默认manual，明确保存只创建模板不运行，也不把补遗语义检查说成已完成", async () => {
  const user = userEvent.setup();
  const writes: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === "POST") {
        writes.push({ path: url, body: JSON.parse(String(options.body)) });
        return json(template, 201);
      }
      return fallback(url);
    }),
  );
  render(
    <TaskTemplateEditor
      bidId="bid"
      memberId="member"
      template={null}
      etag='"bid:1"'
      onSaved={vi.fn()}
      onClose={vi.fn()}
    />,
  );
  await user.type(screen.getByLabelText("模板名称"), "一次保存");
  await user.type(screen.getByLabelText("任务说明"), "核对已登记关系");
  expect(screen.getByLabelText("触发方式")).toHaveValue("manual");
  expect(
    screen.queryByText("已汇总已登记关系，语义影响尚未检查。"),
  ).not.toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: "保存任务模板，不运行" }),
  );
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toEqual({
    path: "/api/v1/bids/bid/task-definitions",
    body: {
      ...newTaskConfiguration(),
      name: "一次保存",
      instructions: "核对已登记关系",
    },
  });
});
it("PUT失响应刷新恢复，仍用同一方法、请求体、ETag与幂等键，不用新头重试", async () => {
  const user = userEvent.setup();
  const sends: RequestInit[] = [];
  let fail = true;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === "PUT") {
        sends.push(options);
        if (fail) throw new TypeError("lost ack");
        return json({ ...template, revision: 2, version_id: "version2" });
      }
      return fallback(url);
    }),
  );
  const props = {
    bidId: "bid",
    memberId: "member",
    template,
    etag: '"template:1"',
    onSaved: vi.fn(),
    onClose: vi.fn(),
  };
  const view = render(<TaskTemplateEditor {...props} />);
  await user.clear(screen.getByLabelText("任务说明"));
  await user.type(screen.getByLabelText("任务说明"), "新版本保留我的修改");
  await user.click(
    screen.getByRole("button", { name: "保存任务模板，不运行" }),
  );
  await screen.findByRole("button", { name: "恢复原模板保存结果" });
  view.unmount();
  fail = false;
  render(<TaskTemplateEditor {...props} etag='"template:3"' />);
  expect(screen.getByLabelText("任务说明")).toHaveValue("新版本保留我的修改");
  await user.click(screen.getByRole("button", { name: "恢复原模板保存结果" }));
  await waitFor(() => expect(props.onSaved).toHaveBeenCalledTimes(1));
  expect(sends).toHaveLength(2);
  expect(sends[1].method).toBe("PUT");
  expect(sends[1].body).toBe(sends[0].body);
  expect(new Headers(sends[1].headers).get("If-Match")).toBe('"template:1"');
  expect(new Headers(sends[1].headers).get("Idempotency-Key")).toBe(
    new Headers(sends[0].headers).get("Idempotency-Key"),
  );
});
it("章节和选定来源缺项可见，未输入真实目标不能保存，定时只有明确选择才出现", async () => {
  const user = userEvent.setup();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => fallback(url)),
  );
  render(
    <TaskTemplateEditor
      bidId="bid"
      memberId="member"
      template={null}
      etag='"bid:1"'
      onSaved={vi.fn()}
      onClose={vi.fn()}
    />,
  );
  await user.selectOptions(
    screen.getByLabelText("任务类型"),
    "chapter_suggestion",
  );
  expect(screen.getByRole("status")).toHaveTextContent("真实目标章节");
  await user.selectOptions(
    screen.getByLabelText("来源范围"),
    "selected_versions",
  );
  expect(screen.getByRole("status")).toHaveTextContent("至少一份明确来源");
  await screen.findByLabelText(/可信PDF.pdf/);
  expect(
    screen.getByRole("button", { name: "保存任务模板，不运行" }),
  ).toBeDisabled();
  expect(screen.queryByLabelText(/定时表达式/)).not.toBeInTheDocument();
  await user.selectOptions(screen.getByLabelText("触发方式"), "schedule");
  expect(screen.getByLabelText(/定时表达式/)).toHaveValue("");
  expect(screen.getByRole("status")).toHaveTextContent("明确的定时表达式");
});
it("不具正式评分资格拒运行；unknown费用不能借当前模板启动第二次", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      url.endsWith("template")
        ? json({
            ...template,
            configuration: {
              ...template.configuration,
              task_kind: "scoring_review",
            },
          })
        : fallback(url),
    ),
  );
  const view = render(
    <TaskTemplateCard
      bidId="bid"
      memberId="member"
      id="template"
      kinds={kinds}
      onChanged={vi.fn()}
      onRun={vi.fn()}
    />,
  );
  await screen.findByText(/评分尚未具备正式资格/);
  expect(
    screen.getByRole("button", { name: "手动运行当前版本" }),
  ).toBeDisabled();
  view.unmount();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => fallback(url)),
  );
  render(
    <TaskTemplateCard
      bidId="bid"
      memberId="member"
      id="template"
      kinds={kinds}
      executionBlocked
      onChanged={vi.fn()}
      onRun={vi.fn()}
    />,
  );
  await screen.findByText(/已有运行费用待核对/);
  expect(
    screen.getByRole("button", { name: "手动运行当前版本" }),
  ).toBeDisabled();
});
it("NL未明确草案不锁死编辑，一次保存按钮串行PUT ACK后原子save，只有一个模板", async () => {
  window.history.replaceState({}, "", "/bids/bid/tasks?task_draft=draft");
  const user = userEvent.setup();
  let current = draft;
  const writes: { method: string; path: string; tag: string | null }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (url.endsWith("/task-definition-drafts/draft")) {
        if (options?.method === "PUT") {
          writes.push({
            method: "PUT",
            path: url,
            tag: new Headers(options.headers).get("If-Match"),
          });
          const input = JSON.parse(String(options.body));
          current = {
            ...draft,
            revision: 2,
            explicitly_edited: true,
            interpretation: {
              ...draft.interpretation,
              ...input,
              unresolved: [],
              ready_for_template_form: true,
            },
          };
          return json(current, 200, '"draft:2"');
        }
        return json(current, 200, '"draft:1"');
      }
      if (url.endsWith("/draft/save")) {
        writes.push({
          method: "POST",
          path: url,
          tag: new Headers(options?.headers).get("If-Match"),
        });
        current = { ...current, saved_template_id: "template" };
        return json(template, 201);
      }
      return fallback(url);
    }),
  );
  render(
    <TaskDraftPanel
      bidId="bid"
      memberId="member"
      bidEtag='"bid:1"'
      onSaved={vi.fn()}
    />,
  );
  await screen.findByText(/仍需明确，可直接在下方修改/);
  expect(screen.getByLabelText("任务说明")).toBeEnabled();
  expect(screen.getByLabelText("任务类型")).toHaveValue("");
  await user.selectOptions(
    screen.getByLabelText("任务类型"),
    "supplement_impact",
  );
  await user.click(
    screen.getByRole("button", { name: "保存任务模板，不运行" }),
  );
  await screen.findByText(/此草案已一次保存为以下模板/);
  expect(writes).toEqual([
    {
      method: "PUT",
      path: "/api/v1/bids/bid/task-definition-drafts/draft",
      tag: '"draft:1"',
    },
    {
      method: "POST",
      path: "/api/v1/bids/bid/task-definition-drafts/draft/save",
      tag: '"draft:2"',
    },
  ]);
  expect(writes.some((item) => item.path.endsWith("/runs"))).toBe(false);
});
it("仅保存草案失响应后的恢复不能变成保存模板", async () => {
  window.history.replaceState({}, "", "/bids/bid/tasks?task_draft=draft");
  const user = userEvent.setup();
  let fail = true;
  let saves = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (url.endsWith("/task-definition-drafts/draft")) {
        if (options?.method === "PUT") {
          if (fail) throw new TypeError("lost");
          return json(
            {
              ...draft,
              revision: 2,
              interpretation: {
                ...draft.interpretation,
                task_kind: "supplement_impact",
                unresolved: [],
                ready_for_template_form: true,
              },
            },
            200,
            '"draft:2"',
          );
        }
        return json(draft, 200, '"draft:1"');
      }
      if (url.endsWith("/save")) {
        saves++;
        return json(template, 201);
      }
      return fallback(url);
    }),
  );
  const props = {
    bidId: "bid",
    memberId: "member",
    bidEtag: '"bid:1"',
    onSaved: vi.fn(),
  };
  const view = render(<TaskDraftPanel {...props} />);
  await screen.findByLabelText("任务类型");
  await user.selectOptions(
    screen.getByLabelText("任务类型"),
    "supplement_impact",
  );
  await user.click(
    screen.getByRole("button", { name: "仅保存草案，不建模板" }),
  );
  await screen.findByRole("button", {
    name: "恢复原草案更新结果（保留原保存意图）",
  });
  view.unmount();
  fail = false;
  render(<TaskDraftPanel {...props} />);
  await user.click(
    await screen.findByRole("button", {
      name: "恢复原草案更新结果（保留原保存意图）",
    }),
  );
  await waitFor(() =>
    expect(
      screen.queryByRole("button", {
        name: "恢复原草案更新结果（保留原保存意图）",
      }),
    ).not.toBeInTheDocument(),
  );
  expect(saves).toBe(0);
});
it("补遗本地处理成功仍明确语义未检查，不能把取消请求说成取消终态", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      url.includes("task-runs")
        ? json({
            id: "run",
            bid_id: "bid",
            definition_version_id: "version1",
            root_operation_id: "operation",
            final_operation_id: null,
            state: "succeeded",
            stage: "execution",
            frozen_manifest: { definition_id: "template" },
            result: { impacts: [] },
            error_code: null,
            formal_decisions_created: false,
            coverage: "registered_effectivity_only_semantic_unknown",
          })
        : url.includes("/versions/")
          ? json({
              id: "version1",
              bid_id: "bid",
              definition_id: "template",
              revision: 1,
              instructions: "关系汇总",
              config: {
                schema: "task-template/1",
                definition: template.configuration,
                paused: false,
                formal_decisions_allowed: false,
              },
              digest: "d".repeat(64),
            })
          : url.includes("/operations/")
            ? json({ id: "operation", bid_id: "bid", state: "succeeded" })
            : fallback(url),
    ),
  );
  render(<TaskRunCard bidId="bid" memberId="member" id="run" />);
  await screen.findByText(/已汇总已登记关系，语义影响尚未检查/);
  expect(screen.queryByText("补遗影响全部检查完成")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "取消本次在途处理" }),
  ).not.toBeInTheDocument();
});
it("已成功保存的编辑草稿不保留旧CAS基准，下一次编辑按当前暂停修订", async () => {
  const user = userEvent.setup();
  const requests: RequestInit[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === "PUT") {
        requests.push(options);
        return json({ ...template, revision: 2, version_id: "version2" });
      }
      return fallback(url);
    }),
  );
  const props = {
    bidId: "bid",
    memberId: "member",
    onSaved: vi.fn(),
    onClose: vi.fn(),
  };
  const view = render(
    <TaskTemplateEditor {...props} template={template} etag='"template:1"' />,
  );
  await user.click(
    screen.getByRole("button", { name: "保存任务模板，不运行" }),
  );
  await waitFor(() => expect(props.onSaved).toHaveBeenCalledTimes(1));
  view.unmount();
  const current = {
    ...template,
    revision: 3,
    version_id: "version3",
    paused: true,
    configuration: {
      ...template.configuration,
      trigger: {
        mode: "material_updated" as const,
        cron: null,
        timezone: "Asia/Shanghai",
      },
    },
  };
  render(
    <TaskTemplateEditor {...props} template={current} etag='"template:3"' />,
  );
  expect(screen.getByLabelText("触发方式")).toHaveValue("material_updated");
  await user.click(
    screen.getByRole("button", { name: "保存任务模板，不运行" }),
  );
  await waitFor(() => expect(requests).toHaveLength(2));
  expect(new Headers(requests[1].headers).get("If-Match")).toBe('"template:3"');
});
it("保存ACK后等当前模板快照读取完成，不能使用旧头提前暂停", async () => {
  const user = userEvent.setup();
  let reads = 0;
  let release: (value: Response) => void = () => {};
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (url.endsWith("/task-definitions/template")) {
        if (options?.method === "PUT")
          return json(
            { ...template, revision: 2, version_id: "version2" },
            200,
            '"template:2"',
          );
        reads++;
        if (reads > 1)
          return new Promise<Response>((resolve) => {
            release = resolve;
          });
        return json(template, 200, '"template:1"');
      }
      return fallback(url);
    }),
  );
  render(
    <TaskTemplateCard
      bidId="bid"
      memberId="member"
      id="template"
      kinds={kinds}
      onChanged={vi.fn()}
      onRun={vi.fn()}
    />,
  );
  await user.click(
    await screen.findByRole("button", { name: "修改并保存新版本" }),
  );
  await user.click(
    screen.getByRole("button", { name: "保存任务模板，不运行" }),
  );
  await waitFor(() => expect(reads).toBeGreaterThan(1));
  expect(screen.getByRole("button", { name: "暂停后续触发" })).toBeDisabled();
  release(
    json(
      { ...template, revision: 2, version_id: "version2" },
      200,
      '"template:2"',
    ),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "暂停后续触发" })).toBeEnabled(),
  );
});
