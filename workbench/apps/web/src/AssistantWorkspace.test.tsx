import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { AssistantWorkspace } from "./AssistantWorkspace";
import { AssistantActionCard, AssistantJobCard } from "./AssistantActionCard";
import { AssistantSourcePicker } from "./AssistantSourcePicker";
import { setAuth } from "./api";
import type {
  AssistantAction,
  AssistantJob,
  WorkConversationView,
} from "./contracts";

// Explicit component counterexamples. No provider/model quality is represented here.
const conversation: WorkConversationView = {
  id: "conversation",
  bid_id: "project",
  scope: "project",
  is_main: true,
  state: "active",
  revision: 1,
  title: "项目主会话",
  stream_id: null,
  created_at: "2026-01-01T00:00:00Z",
};
const job: AssistantJob = {
  id: "job",
  kind: "answer",
  scope: "project",
  bid_id: "project",
  conversation_id: "conversation",
  user_message_id: "message",
  operation: {
    id: "operation",
    bid_id: "project",
    state: "running",
    scope: "project",
    cancel_requested_at: null,
    handler_version: "assistant/1",
  },
  cancel_requested: false,
  cancellation_terminal: false,
  model_call: { id: "call", state: "unknown", billing_state: "unknown" },
  requires_billing_reconciliation: true,
  publication: null,
  candidate: null,
  formal_scoring_input: false,
  automatic_retry_authorized: false,
  logical_intent: null,
  budget: null,
};
function json(value: unknown, status = 200, etag = '"conversation:1"') {
  return new Response(JSON.stringify(value), {
    status,
    headers: { ETag: etag },
  });
}
function fallback(url: string) {
  const path = new URL(url, window.location.href).pathname;
  if (path === "/api/v1/bids/project")
    return json({ id: "project", title: "自己的合成项目" });
  if (path === "/api/v1/bids")
    return json({ items: [], has_more: false, next_cursor: null });
  if (path.endsWith("/messages"))
    return json({ items: [], has_more: false, before: null });
  if (path.endsWith("/events"))
    return json({
      stream_id: "conversation",
      items: [],
      next_cursor: 0,
      head_cursor: 0,
    });
  if (path === "/api/v1/assistant/jobs") return json({ items: [] });
  return json(conversation);
}
beforeEach(() => {
  sessionStorage.clear();
  window.history.replaceState({}, "", "/assistant?bid=project");
  setAuth({
    member: { id: "member", display_name: "开发夹具", active: true },
    csrf_token: "csrf",
    expires_at: "2099-01-01T00:00:00Z",
  });
});
it("只显式创建同一主会话，保存讨论不请求AI，刷新能恢复服务器消息", async () => {
  const user = userEvent.setup();
  let exists = false;
  let messages: unknown[] = [];
  const writes: { path: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      const path = new URL(url, window.location.href).pathname;
      if (path.endsWith("/conversations/main")) {
        if (options?.method === "POST") {
          exists = true;
          writes.push({ path, body: JSON.parse(String(options.body)) });
          return json(conversation, 201);
        }
        return exists
          ? json(conversation)
          : json({ code: "NOT_FOUND", message: "未创建" }, 404);
      }
      if (path.endsWith("/messages")) {
        if (options?.method === "POST") {
          const body = JSON.parse(String(options.body));
          writes.push({ path, body });
          const value = {
            id: "saved",
            conversation_id: conversation.id,
            bid_id: "project",
            role: "user",
            parts: [{ type: "text", text: body.text }],
            created_by: "member",
            created_at: "2026-01-01T00:00:00Z",
          };
          messages = [value];
          return json(value, 201);
        }
        return json({ items: messages, has_more: false, before: null });
      }
      return fallback(url);
    }),
  );
  const view = render(
    <AssistantWorkspace bidId="project" memberId="member" embedded />,
  );
  await user.click(
    await screen.findByRole("button", { name: "创建并继续主会话" }),
  );
  await user.type(
    await screen.findByLabelText("本次提问"),
    "只记录讨论，不授权执行",
  );
  await user.click(
    screen.getByRole("button", { name: "仅保存讨论，不请求AI" }),
  );
  await screen.findByText("只记录讨论，不授权执行");
  expect(writes).toHaveLength(2);
  expect(writes[0].body).toEqual({});
  expect(writes[1].path.endsWith("/messages")).toBe(true);
  expect(screen.getByLabelText("本次提问")).toHaveValue("");
  view.unmount();
  render(<AssistantWorkspace bidId="project" memberId="member" embedded />);
  await screen.findByText("只记录讨论，不授权执行");
  expect(writes).toHaveLength(2);
});
it("412保留草稿，重新读取真实修订后明确继续，不能用旧ETag重发", async () => {
  const user = userEvent.setup();
  let conflict = true,
    revision = 1;
  const sends: RequestInit[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      const path = new URL(url, window.location.href).pathname;
      if (path.endsWith("/messages") && options?.method === "POST") {
        sends.push(options);
        if (conflict) {
          revision = 2;
          return json(
            { code: "PRECONDITION_FAILED", message: "基准已变" },
            412,
          );
        }
        return json({
          id: "message",
          conversation_id: "conversation",
          bid_id: "project",
        });
      }
      if (path.includes("conversations") && !path.endsWith("messages"))
        return json(
          { ...conversation, revision },
          200,
          `"conversation:${revision}"`,
        );
      return fallback(url);
    }),
  );
  render(<AssistantWorkspace bidId="project" memberId="member" embedded />);
  await user.type(await screen.findByLabelText("本次提问"), "保留输入");
  await user.click(
    screen.getByRole("button", { name: "仅保存讨论，不请求AI" }),
  );
  await screen.findByText(/会话或来源已变化/);
  expect(screen.getByLabelText("本次提问")).toHaveValue("保留输入");
  expect(screen.getByRole("button", { name: "发送给助手" })).toBeDisabled();
  conflict = false;
  await user.click(
    screen.getByRole("button", { name: "已核对会话，按当前修订继续" }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "发送给助手" })).toBeEnabled(),
  );
  await user.click(
    screen.getByRole("button", { name: "仅保存讨论，不请求AI" }),
  );
  await waitFor(() => expect(sends).toHaveLength(2));
  expect(new Headers(sends[0].headers).get("If-Match")).toBe(
    '"conversation:1"',
  );
  expect(new Headers(sends[1].headers).get("If-Match")).toBe(
    '"conversation:2"',
  );
  expect(JSON.parse(String(sends[0].body)).client_message_id).toEqual(
    JSON.parse(String(sends[1].body)).client_message_id,
  );
});
it("全局主会话保持null项目与私有范围，不提供项目讨论写入", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      url.includes("global-conversations/main")
        ? json({ ...conversation, scope: "global", bid_id: null })
        : fallback(url),
    ),
  );
  render(<AssistantWorkspace bidId={null} memberId="member" />);
  await screen.findByLabelText("本次提问");
  expect(screen.getByText(/这段讨论仅你可见/)).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "仅保存讨论，不请求AI" }),
  ).not.toBeInTheDocument();
});
it("unknown费用不展示候选回答或提供重复启动，取消受理不能冒取消完成", async () => {
  const user = userEvent.setup();
  let current = job;
  const posts: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (url.includes("/assistant/jobs/job")) {
        if (options?.method === "POST") {
          posts.push(url);
          current = {
            ...job,
            cancel_requested: true,
            operation: { ...job.operation, state: "cancel_requested" },
          };
          return json(current, 202);
        }
        return json(current);
      }
      return fallback(url);
    }),
  );
  render(
    <AssistantJobCard
      id="job"
      bidId="project"
      conversationId="conversation"
      memberId="member"
    />,
  );
  await screen.findByText("调用／费用待核对");
  await user.click(screen.getByRole("button", { name: "请求取消这次处理" }));
  await screen.findByText(/尚未到实际取消终态/);
  expect(screen.queryByText("服务端已记录取消终态。")).not.toBeInTheDocument();
  expect(posts).toHaveLength(1);
  expect(
    screen.queryByRole("button", { name: "请求取消这次处理" }),
  ).not.toBeInTheDocument();
});
it("可信来源只接受服务器指定版本，其他项目与不可用项不可误选", async () => {
  const user = userEvent.setup();
  const changed = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      url.includes("/assistant/sources")
        ? json({
            items: [
              {
                title: "真实原件页",
                available: true,
                reasons: [],
                bid_id: "project",
                formal_scoring_input: false,
                reference: {
                  kind: "document",
                  id: "doc",
                  version: "opaque-server-version",
                  trace_id: null,
                  physical_page: 1,
                },
              },
              {
                title: "别人的项目",
                available: true,
                reasons: [],
                bid_id: "foreign",
                reference: {
                  kind: "document",
                  id: "other",
                  version: "do-not-use",
                  trace_id: null,
                },
              },
              {
                title: "撤回原件",
                available: false,
                reasons: ["SOURCE_WITHDRAWN"],
                bid_id: "project",
                reference: null,
              },
            ],
            coverage: "partial",
            notice: "只读来源",
          })
        : fallback(url),
    ),
  );
  render(
    <AssistantSourcePicker
      bidId="project"
      selected={[]}
      onChange={changed}
      disabled={false}
    />,
  );
  await user.click(await screen.findByLabelText(/真实原件页/));
  expect(changed).toHaveBeenCalledWith([
    {
      title: "真实原件页",
      bidId: "project",
      reference: {
        kind: "document",
        id: "doc",
        version: "opaque-server-version",
        trace_id: null,
        physical_page: 1,
      },
    },
  ]);
  expect(screen.queryByText("别人的项目")).not.toBeInTheDocument();
  expect(screen.getByLabelText(/撤回原件/)).toBeDisabled();
});
it("操作卡只有明确按钮执行一次，服务端已执行后第二入口不能再确认", async () => {
  const user = userEvent.setup();
  let current = {
    action_id: "action",
    target_bid_id: "project",
    tool: "knowledge.candidate",
    state: "pending",
    preview: {
      kind: "knowledge_candidate",
      effect: "建立候选不发布",
      title: "候选",
      content: "明确的候选内容",
      scope: "限合成项目",
      source_version_ids: [],
    },
    base_revision: 1,
    request_digest: "digest",
    expires_at: "2099-01-01T00:00:00Z",
    resolved_by: null,
    result: null,
  } as unknown as AssistantAction;
  let writes = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (url.includes("/assistant/actions/action")) {
        if (options?.method === "POST") {
          writes++;
          expect(JSON.parse(String(options.body))).toEqual({
            decision: "confirm",
          });
          current = { ...current, state: "executed", resolved_by: "member" };
        }
        return json(current, 200, '"action:1"');
      }
      return fallback(url);
    }),
  );
  const view = render(<AssistantActionCard id="action" memberId="member" />);
  await user.click(
    await screen.findByRole("button", { name: "确认建立知识候选" }),
  );
  await screen.findByText("已执行并留存结果");
  expect(writes).toBe(1);
  view.unmount();
  render(<AssistantActionCard id="action" memberId="second" />);
  await screen.findByText("已执行并留存结果");
  expect(
    screen.queryByRole("button", { name: "确认建立知识候选" }),
  ).not.toBeInTheDocument();
  expect(writes).toBe(1);
});
it("归档不能直接激活，先恢复为已结束；会话状态改变不请求取消任务", async () => {
  const user = userEvent.setup();
  let current = {
    ...conversation,
    state: "hidden" as WorkConversationView["state"],
  };
  const states: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (url.includes("/conversations/") && !url.includes("/messages")) {
        if (options?.method === "POST") {
          const body = JSON.parse(String(options.body));
          states.push(body.state);
          current = { ...current, state: body.state };
        }
        return json(current);
      }
      return fallback(url);
    }),
  );
  render(<AssistantWorkspace bidId="project" memberId="member" embedded />);
  await user.click(
    await screen.findByRole("button", { name: "会话显示与结束" }),
  );
  expect(
    screen.queryByRole("button", { name: "继续这条会话" }),
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "恢复为已结束会话" }));
  await user.click(await screen.findByRole("button", { name: "继续这条会话" }));
  await waitFor(() => expect(states).toEqual(["closed", "active"]));
});
it("不同项目消息不混入当前主会话", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      url.includes("/messages")
        ? json({
            items: [
              {
                id: "foreign",
                bid_id: "other",
                conversation_id: "conversation",
                role: "user",
                parts: [{ type: "text", text: "不能串入的内容" }],
                created_at: "2026-01-01T00:00:00Z",
              },
            ],
            has_more: false,
            before: null,
          })
        : fallback(url),
    ),
  );
  render(<AssistantWorkspace bidId="project" memberId="member" embedded />);
  await screen.findByText(/会话消息范围不一致/);
  expect(screen.queryByText("不能串入的内容")).not.toBeInTheDocument();
  await act(async () => {});
});
it("会话过期收起侧栏保留草稿，不把键盘困在后台助手或请求取消", async () => {
  const onClose = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => fallback(url)),
  );
  const { AssistantDrawer } = await import("./AssistantDrawer");
  render(
    <AssistantDrawer bidId="project" memberId="member" onClose={onClose} />,
  );
  await screen.findByLabelText("本次提问");
  act(() => window.dispatchEvent(new Event("session-expired")));
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(fetch).not.toHaveBeenCalledWith(
    expect.stringContaining("/cancel"),
    expect.anything(),
  );
});
