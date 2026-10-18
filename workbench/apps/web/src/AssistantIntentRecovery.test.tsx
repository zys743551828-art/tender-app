import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { useState } from "react";
import {
  AssistantIntentRecovery,
  type AssistantRecoverySelection,
} from "./AssistantIntentRecovery";
import { AssistantWorkspace } from "./AssistantWorkspace";
import type {
  AssistantJob,
  Bid,
  FindingPage,
  RuleSetView,
  WorkConversationView,
} from "./contracts";
import type { SelectedAssistantSource } from "./assistantState";
import { setAuth } from "./api";

const bidId = "00000000-0000-4000-8000-000000000001";
const jobId = "00000000-0000-4000-8000-000000000002";
const conversationId = "00000000-0000-4000-8000-000000000003";
const ruleId = "00000000-0000-4000-8000-000000000004";
const sectionId = "00000000-0000-4000-8000-000000000005";
const reviewId = "00000000-0000-4000-8000-000000000006";
const project = {
  id: bidId,
  title: "已登记的道路工程",
  current_review_id: reviewId,
} as Bid;
const conversation: WorkConversationView = {
  id: conversationId,
  bid_id: bidId,
  scope: "project",
  is_main: true,
  state: "active",
  revision: 1,
  title: "项目主会话",
  stream_id: null,
  created_at: "2026-01-01T00:00:00Z",
};
const unknown: AssistantJob = {
  id: jobId,
  kind: "answer",
  scope: "project",
  bid_id: bidId,
  conversation_id: conversationId,
  user_message_id: null,
  operation: {
    id: "operation",
    bid_id: bidId,
    state: "failed",
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
const ruleSet = {
  id: "rules",
  bid_id: bidId,
  rules: [
    {
      id: ruleId,
      statement: "核对实际条款的要求范围",
      scope: { bid_id: bidId },
    },
    { id: "foreign", statement: "其他项目条款", scope: { bid_id: "foreign" } },
  ],
} as RuleSetView;
const projectSource: SelectedAssistantSource = {
  title: project.title,
  bidId,
  reference: {
    kind: "project",
    id: bidId,
    version: "a".repeat(64),
    trace_id: null,
  },
};
const sectionSource: SelectedAssistantSource = {
  title: "已保存的施工准备章节",
  bidId,
  reference: {
    kind: "section",
    id: sectionId,
    version: "b".repeat(64),
    trace_id: null,
  },
};

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { ETag: '"conversation:1"' },
  });
}
function get(url: string) {
  const path = new URL(url, window.location.href).pathname;
  if (path === `/api/v1/bids/${bidId}/rules`) return json(ruleSet);
  if (path === `/api/v1/bids/${bidId}`) return json(project);
  if (path === "/api/v1/bids")
    return json({ items: [project], has_more: false, next_cursor: null });
  if (path === "/api/v1/assistant/jobs") return json({ items: [unknown] });
  if (path === `/api/v1/assistant/jobs/${jobId}`) return json(unknown);
  if (path.endsWith("/messages"))
    return json({ items: [], has_more: false, before: null });
  if (path.endsWith("/events"))
    return json({
      items: [],
      next_cursor: 0,
      head_cursor: 0,
      stream_id: conversationId,
    });
  return json(conversation);
}

function Recovery({
  bid = bidId,
  sources = [] as SelectedAssistantSource[],
}: {
  bid?: string | null;
  sources?: SelectedAssistantSource[];
}) {
  const [selection, setSelection] = useState<AssistantRecoverySelection>({
    active: false,
    intent: null,
  });
  return (
    <>
      <AssistantIntentRecovery
        bidId={bid}
        jobs={[unknown]}
        sources={sources}
        disabled={false}
        onInteract={() => undefined}
        onChange={setSelection}
      />
      <output data-testid="selection">{JSON.stringify(selection)}</output>
    </>
  );
}
function selection() {
  return JSON.parse(screen.getByTestId("selection").textContent || "null");
}
async function chooseRule(user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(
    screen.getByLabelText("本次请求方式"),
    "new_question",
  );
  await user.selectOptions(screen.getByLabelText("新问题所属项目"), bidId);
  await waitFor(() =>
    expect(screen.getByLabelText("新问题作用对象")).toBeEnabled(),
  );
  await user.selectOptions(screen.getByLabelText("新问题作用对象"), "rule");
  await screen.findByRole("option", { name: "核对实际条款的要求范围" });
  await user.selectOptions(screen.getByLabelText("具体业务对象"), ruleId);
}
beforeEach(() => {
  sessionStorage.clear();
  window.history.replaceState({}, "", `/assistant?bid=${bidId}`);
  setAuth({
    member: { id: "member", display_name: "合成成员", active: true },
    csrf_token: "csrf",
    expires_at: "2099-01-01T00:00:00Z",
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => get(url)),
  );
});

it("unknown默认没有原任务或新对象，只有显式原引用才能形成continue", async () => {
  const user = userEvent.setup();
  render(<Recovery />);
  expect(selection()).toEqual({ active: false, intent: null });
  expect(screen.getByLabelText("本次请求方式")).toHaveValue("");
  await user.selectOptions(screen.getByLabelText("本次请求方式"), "continue");
  expect(selection()).toEqual({ active: true, intent: null });
  expect(screen.getByLabelText("原待核对任务")).toHaveValue("");
  await user.selectOptions(screen.getByLabelText("原待核对任务"), jobId);
  await waitFor(() =>
    expect(selection()).toEqual({
      active: true,
      intent: { request_mode: "continue", related_job_id: jobId },
    }),
  );
  expect(
    screen.queryByRole("button", { name: /核清|放款|重发模型/ }),
  ).not.toBeInTheDocument();
});

it("真实对象及允许用途明确选择，其他项目条款不能成为本项目目标", async () => {
  const user = userEvent.setup();
  render(<Recovery />);
  await chooseRule(user);
  await waitFor(() =>
    expect(selection().intent).toEqual({
      request_mode: "new_question",
      target: { kind: "rule", id: ruleId },
      intent_purpose: "rule_explanation",
    }),
  );
  expect(
    screen.queryByRole("option", { name: "其他项目条款" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText(/本次用途：要求条款解释/)).toBeVisible();
  await user.selectOptions(screen.getByLabelText("新问题作用对象"), "project");
  await waitFor(() =>
    expect(selection().intent).toEqual({
      request_mode: "new_question",
      target: { kind: "project", id: bidId },
      intent_purpose: "project_reference",
    }),
  );
});

it("global章节目标还须明确选择所属项目来源，来源移除后目标失效而不暗换", async () => {
  const user = userEvent.setup();
  const view = render(<Recovery bid={null} sources={[sectionSource]} />);
  await user.selectOptions(
    screen.getByLabelText("本次请求方式"),
    "new_question",
  );
  expect(screen.getByLabelText("新问题所属项目")).toHaveValue("");
  expect(
    screen.queryByRole("option", { name: project.title }),
  ).not.toBeInTheDocument();
  expect(selection().intent).toBeNull();
  view.rerender(
    <Recovery bid={null} sources={[projectSource, sectionSource]} />,
  );
  expect(screen.getByLabelText("新问题所属项目")).toHaveValue("");
  await user.selectOptions(screen.getByLabelText("新问题所属项目"), bidId);
  await waitFor(() =>
    expect(screen.getByLabelText("新问题作用对象")).toBeEnabled(),
  );
  await user.selectOptions(screen.getByLabelText("新问题作用对象"), "section");
  await user.selectOptions(screen.getByLabelText("具体业务对象"), sectionId);
  await waitFor(() =>
    expect(selection().intent).toEqual({
      request_mode: "new_question",
      target: { kind: "section", id: sectionId },
      intent_purpose: "section_reference",
    }),
  );
  view.rerender(<Recovery bid={null} sources={[sectionSource]} />);
  await waitFor(() => expect(selection().intent).toBeNull());
  expect(screen.getByLabelText("新问题作用对象")).toHaveValue("section");
});

it("只列真实当前评审的问题，未知或其他轮次问题不成为目标", async () => {
  const user = userEvent.setup();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      url.includes(`/reviews/${reviewId}/findings`)
        ? json({
            items: [
              {
                id: "finding",
                review_id: reviewId,
                statement: "当前轮次的实际问题",
              },
              { id: "other", review_id: "other", statement: "其他评审的问题" },
            ],
            has_more: false,
            next_cursor: null,
          } as FindingPage)
        : get(url),
    ),
  );
  render(<Recovery />);
  await user.selectOptions(
    screen.getByLabelText("本次请求方式"),
    "new_question",
  );
  await user.selectOptions(screen.getByLabelText("新问题所属项目"), bidId);
  await waitFor(() =>
    expect(screen.getByLabelText("新问题作用对象")).toBeEnabled(),
  );
  await user.selectOptions(screen.getByLabelText("新问题作用对象"), "finding");
  await screen.findByRole("option", { name: "当前轮次的实际问题" });
  expect(
    screen.queryByRole("option", { name: "其他评审的问题" }),
  ).not.toBeInTheDocument();
  await user.selectOptions(screen.getByLabelText("具体业务对象"), "finding");
  await waitFor(() =>
    expect(selection().intent?.intent_purpose).toBe("finding_explanation"),
  );
});

it("关联原job只读回状态并保留草稿，普通发送仍禁且不自动触发", async () => {
  const user = userEvent.setup();
  const posts: { body: Record<string, unknown>; headers?: HeadersInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === "POST" && url.endsWith("/turns")) {
        posts.push({
          body: JSON.parse(String(options.body)),
          headers: options.headers,
        });
        return json(unknown, 202);
      }
      return get(url);
    }),
  );
  render(<AssistantWorkspace bidId={bidId} memberId="member" />);
  await screen.findByLabelText("本次提问");
  await user.type(screen.getByLabelText("本次提问"), "保留我的未另存草稿");
  expect(screen.getByRole("button", { name: "发送给助手" })).toBeDisabled();
  expect(posts).toHaveLength(0);
  await user.selectOptions(screen.getByLabelText("本次请求方式"), "continue");
  await user.selectOptions(screen.getByLabelText("原待核对任务"), jobId);
  await user.click(
    screen.getByRole("button", { name: "关联原任务并查看状态" }),
  );
  await screen.findByText(/已读回原处理状态/);
  expect(posts).toHaveLength(1);
  expect(posts[0].body).toMatchObject({
    request_mode: "continue",
    related_job_id: jobId,
    text: "查看原任务状态",
    source_selection: [],
  });
  expect(posts[0].body).not.toHaveProperty("target");
  expect(new Headers(posts[0].headers).get("if-match")).toBe(
    '"conversation:1"',
  );
  expect(screen.getByLabelText("本次提问")).toHaveValue("保留我的未另存草稿");
});

it("空草稿也可显式读回原任务，读回后不自动转为新问题", async () => {
  const user = userEvent.setup();
  const bodies: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === "POST" && url.endsWith("/turns")) {
        bodies.push(JSON.parse(String(options.body)));
        return json(unknown, 202);
      }
      return get(url);
    }),
  );
  render(<AssistantWorkspace bidId={bidId} memberId="member" />);
  await screen.findByRole("option", { name: "关联原任务，查看既有状态" });
  await user.selectOptions(screen.getByLabelText("本次请求方式"), "continue");
  await user.selectOptions(screen.getByLabelText("原待核对任务"), jobId);
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "关联原任务并查看状态" }),
    ).toBeEnabled(),
  );
  await user.click(
    screen.getByRole("button", { name: "关联原任务并查看状态" }),
  );
  await screen.findByText(/已读回原处理状态/);
  expect(bodies[0].text).toBe("查看原任务状态");
  expect(screen.getByLabelText("本次提问")).toHaveValue("");
  expect(screen.getByLabelText("本次请求方式")).toHaveValue("continue");
});

it("服务端复用原job时保留草稿并明确没有创建新任务", async () => {
  const user = userEvent.setup();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) =>
      options?.method === "POST" && url.endsWith("/turns")
        ? json(unknown, 202)
        : get(url),
    ),
  );
  render(<AssistantWorkspace bidId={bidId} memberId="member" />);
  await screen.findByLabelText("本次提问");
  await user.type(screen.getByLabelText("本次提问"), "相同对象是否仍归原请求");
  await chooseRule(user);
  await user.click(screen.getByRole("button", { name: "提交明确的新问题" }));
  await screen.findByText(/未创建新任务或模型调用/);
  expect(screen.getByLabelText("本次提问")).toHaveValue(
    "相同对象是否仍归原请求",
  );
});

it("新问题受理答复丢失后只恢复同一请求和幂等键，不重选目标", async () => {
  const user = userEvent.setup();
  const requests: { body: unknown; key: string | null }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === "POST" && url.endsWith("/turns")) {
        requests.push({
          body: JSON.parse(String(options.body)),
          key: new Headers(options.headers).get("idempotency-key"),
        });
        if (requests.length === 1)
          throw new TypeError("explicit lost acknowledgement");
        return json(unknown, 202);
      }
      return get(url);
    }),
  );
  render(<AssistantWorkspace bidId={bidId} memberId="member" />);
  await screen.findByLabelText("本次提问");
  await user.type(screen.getByLabelText("本次提问"), "保留确切请求与目标");
  await chooseRule(user);
  await user.click(screen.getByRole("button", { name: "提交明确的新问题" }));
  await screen.findByRole("button", { name: "恢复原提问受理结果" });
  expect(screen.getByLabelText("本次请求方式")).toBeDisabled();
  expect(requests).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "恢复原提问受理结果" }));
  await screen.findByText(/未创建新任务或模型调用/);
  expect(requests).toHaveLength(2);
  expect(requests[1]).toEqual(requests[0]);
  expect(screen.getByLabelText("本次提问")).toHaveValue("保留确切请求与目标");
});

it("选择新对象后出现真实在途任务，硬门立即恢复且不发送", async () => {
  const user = userEvent.setup();
  let running = false;
  const writes: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === "POST") writes.push(url);
      if (
        running &&
        new URL(url, window.location.href).pathname === "/api/v1/assistant/jobs"
      )
        return json({
          items: [
            {
              ...unknown,
              operation: { ...unknown.operation, state: "running" },
            },
          ],
        });
      return get(url);
    }),
  );
  render(<AssistantWorkspace bidId={bidId} memberId="member" />);
  await screen.findByLabelText("本次提问");
  await user.type(screen.getByLabelText("本次提问"), "等待最新状态核对");
  await chooseRule(user);
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "提交明确的新问题" }),
    ).toBeEnabled(),
  );
  running = true;
  act(() => window.dispatchEvent(new Event("server-snapshot-change")));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "提交明确的新问题" }),
    ).toBeDisabled(),
  );
  expect(screen.getByLabelText("本次请求方式")).toBeDisabled();
  expect(writes).toHaveLength(0);
});

it("global明确新项目时保留该项目版本来源，不自动切会话或添加原任务引用", async () => {
  const user = userEvent.setup();
  window.history.replaceState({}, "", "/assistant");
  const globalConversation = { ...conversation, scope: "global", bid_id: null };
  const globalJob = {
    ...unknown,
    scope: "global",
    bid_id: null,
    operation: { ...unknown.operation, scope: "global", bid_id: null },
  };
  const requests: Record<string, unknown>[] = [];
  sessionStorage.setItem(
    `tender:knowledge:member:${conversationId}:assistant-compose:sources`,
    JSON.stringify([projectSource]),
  );
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === "POST" && url.endsWith("/turns")) {
        requests.push(JSON.parse(String(options.body)));
        return json(
          {
            code: "ASSISTANT_TARGET_IDENTITY_UNPROVEN",
            message: "服务端仍须核对原页身份依据",
          },
          409,
        );
      }
      const path = new URL(url, window.location.href).pathname;
      if (path.endsWith("global-conversations/main"))
        return json(globalConversation);
      if (path === "/api/v1/assistant/jobs")
        return json({ items: [globalJob] });
      if (path === `/api/v1/assistant/jobs/${jobId}`) return json(globalJob);
      return get(url);
    }),
  );
  render(<AssistantWorkspace bidId={null} memberId="member" />);
  await screen.findByLabelText("本次提问");
  await user.type(
    screen.getByLabelText("本次提问"),
    "说明这个明确选择的新工程",
  );
  await user.selectOptions(
    screen.getByLabelText("本次请求方式"),
    "new_question",
  );
  await user.selectOptions(screen.getByLabelText("新问题所属项目"), bidId);
  await waitFor(() =>
    expect(screen.getByLabelText("新问题作用对象")).toBeEnabled(),
  );
  await user.selectOptions(screen.getByLabelText("新问题作用对象"), "project");
  await user.click(screen.getByRole("button", { name: "提交明确的新问题" }));
  await screen.findByText(/服务端仍须核对原页身份依据/);
  expect(requests[0]).toMatchObject({
    request_mode: "new_question",
    target: { kind: "project", id: bidId },
    intent_purpose: "project_reference",
    source_selection: [projectSource.reference],
  });
  expect(requests[0]).not.toHaveProperty("related_job_id");
  expect(screen.getByLabelText("本次提问")).toHaveValue(
    "说明这个明确选择的新工程",
  );
  expect(window.location.search).toBe("");
});

it("关联原job收到其他job回包时保留输入且不宣称已读原处理", async () => {
  const user = userEvent.setup();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) =>
      options?.method === "POST" && url.endsWith("/turns")
        ? json({ ...unknown, id: "other-job" }, 202)
        : get(url),
    ),
  );
  render(<AssistantWorkspace bidId={bidId} memberId="member" />);
  await screen.findByLabelText("本次提问");
  await user.type(screen.getByLabelText("本次提问"), "保留未另存输入");
  await user.selectOptions(screen.getByLabelText("本次请求方式"), "continue");
  await user.selectOptions(screen.getByLabelText("原待核对任务"), jobId);
  await user.click(
    screen.getByRole("button", { name: "关联原任务并查看状态" }),
  );
  await screen.findByText(/返回的处理不是所选原任务/);
  expect(screen.getByLabelText("本次提问")).toHaveValue("保留未另存输入");
  expect(screen.queryByText(/已读回原处理状态/)).not.toBeInTheDocument();
});

it("目标项目读取失败时不退回普通请求或沿用缓存身份", async () => {
  const user = userEvent.setup();
  let projectReads = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (
        new URL(url, window.location.href).pathname ===
          `/api/v1/bids/${bidId}` &&
        ++projectReads > 1
      )
        return json(
          { code: "TEMPORARY_FAILURE", message: "目标项目暂不能核对" },
          503,
        );
      return get(url);
    }),
  );
  render(<Recovery />);
  await user.selectOptions(
    screen.getByLabelText("本次请求方式"),
    "new_question",
  );
  await screen.findByRole("option", { name: project.title });
  await user.selectOptions(screen.getByLabelText("新问题所属项目"), bidId);
  await screen.findByText(/目标项目暂不能核对/);
  expect(screen.getByLabelText("新问题作用对象")).toBeDisabled();
  expect(selection()).toEqual({ active: true, intent: null });
});

it("提交新rule只发送所选对象/用途，服务端不独立拒绝保留草稿且不自动改目标", async () => {
  const user = userEvent.setup();
  const bodies: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === "POST" && url.endsWith("/turns")) {
        bodies.push(JSON.parse(String(options.body)));
        return json(
          {
            code: "ASSISTANT_INDEPENDENCE_UNPROVEN",
            message: "暂不能证明这是独立请求，输入保留",
          },
          409,
        );
      }
      return get(url);
    }),
  );
  render(<AssistantWorkspace bidId={bidId} memberId="member" />);
  await screen.findByLabelText("本次提问");
  await user.type(screen.getByLabelText("本次提问"), "解释选择的真实条款");
  await chooseRule(user);
  await user.click(screen.getByRole("button", { name: "提交明确的新问题" }));
  await screen.findByText(/暂不能证明这是独立请求/);
  expect(bodies).toHaveLength(1);
  expect(bodies[0]).toMatchObject({
    request_mode: "new_question",
    target: { kind: "rule", id: ruleId },
    intent_purpose: "rule_explanation",
  });
  expect(bodies[0]).not.toHaveProperty("related_job_id");
  expect(screen.getByLabelText("本次提问")).toHaveValue("解释选择的真实条款");
  expect(screen.getByLabelText("具体业务对象")).toHaveValue(ruleId);
});

it.each(["running", "error", "foreign", "loading"])(
  "%s硬门不能被显式新对象流程解除",
  async (state) => {
    const user = userEvent.setup();
    const posts: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, options?: RequestInit) => {
        if (options?.method === "POST") posts.push(url);
        if (
          new URL(url, window.location.href).pathname ===
          "/api/v1/assistant/jobs"
        ) {
          if (state === "loading")
            return new Promise<Response>(() => undefined);
          if (state === "error")
            return json(
              { code: "TEMPORARY_FAILURE", message: "列表未取得" },
              503,
            );
          return json({
            items: [
              state === "foreign"
                ? { ...unknown, bid_id: "foreign" }
                : {
                    ...unknown,
                    operation: { ...unknown.operation, state: "running" },
                  },
            ],
          });
        }
        return get(url);
      }),
    );
    render(<AssistantWorkspace bidId={bidId} memberId="member" />);
    await screen.findByLabelText("本次提问");
    await user.type(screen.getByLabelText("本次提问"), "不能绕过硬门");
    expect(screen.getByLabelText("本次请求方式")).toBeDisabled();
    expect(screen.getByRole("button", { name: "发送给助手" })).toBeDisabled();
    expect(posts).toHaveLength(0);
  },
);
