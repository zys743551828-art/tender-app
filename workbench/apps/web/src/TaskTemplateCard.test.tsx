import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { TaskTemplateCard } from "./TaskTemplateCard";
import { newTaskConfiguration } from "./taskState";
import type { TaskKindPage, TemplateView } from "./taskTriggerContracts";

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
    name: "合成手动任务",
    instructions: "仅本地合成测试",
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
  ],
  default_trigger: "manual",
  saving_preset_creates_run: false,
};
const json = (data: unknown, status = 200, etag = '"version:1"') =>
  new Response(JSON.stringify(data), { status, headers: { ETag: etag } });
const button = () => screen.getByRole("button", { name: "手动运行当前版本" });
beforeEach(() => sessionStorage.clear());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it.each([200, 412])(
  "后台读取不吞掉明确运行点击，固定显示ETag，%i回执不自动重试",
  async (status) => {
    let reads = 0;
    let release!: (response: Response) => void;
    const posts: RequestInit[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, options?: RequestInit) => {
        if (options?.method === "POST") {
          posts.push(options);
          return status === 200
            ? json({ id: "run", bid_id: "bid" })
            : json(
                { code: "PRECONDITION_FAILED", message: "版本已变化" },
                status,
              );
        }
        reads++;
        return reads === 1
          ? json(template)
          : new Promise<Response>((resolve) => {
              release = resolve;
            });
      }),
    );
    const onRun = vi.fn();
    render(
      <TaskTemplateCard
        bidId="bid"
        memberId="member"
        id="template"
        kinds={kinds}
        onChanged={vi.fn()}
        onRun={onRun}
      />,
    );
    await screen.findByRole("button", { name: "手动运行当前版本" });
    fireEvent.pointerDown(button());
    act(() => window.dispatchEvent(new Event("server-snapshot-change")));
    await waitFor(() => expect(reads).toBe(2));
    expect(button()).toBeEnabled();
    fireEvent.pointerUp(button());
    fireEvent.click(button(), { detail: 1 });
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(new Headers(posts[0].headers).get("If-Match")).toBe('"version:1"');
    expect(JSON.parse(String(posts[0].body))).toEqual({ rerun: false });
    await act(async () =>
      release(
        json(
          { ...template, revision: 2, version_id: "version2" },
          200,
          '"version:2"',
        ),
      ),
    );
    expect(posts).toHaveLength(1);
    if (status === 200) expect(onRun).toHaveBeenCalledWith("run");
    else {
      expect(onRun).not.toHaveBeenCalled();
      expect(screen.getByText("版本已变化")).toBeVisible();
    }
  },
);

it.each([
  "paused",
  "fee",
  "capability",
  "missing-etag",
  "error",
  "identity",
  "pending",
])("后台刷新不放宽 %s 守卫", async (guard) => {
  let reads = 0;
  const posts: RequestInit[] = [];
  if (guard === "pending")
    sessionStorage.setItem(
      "tender:command-record:task-run:member:bid:template:start",
      JSON.stringify({
        path: "/bids/bid/task-definitions/template/runs",
        body: { rerun: false },
        etag: '"version:1"',
        key: "pending-key",
      }),
    );
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: RequestInfo | URL, options?: RequestInit) => {
      if (options?.method === "POST") posts.push(options);
      reads++;
      if (guard === "error" && reads > 1)
        return json({ message: "刷新失败" }, 500);
      return json(
        {
          ...template,
          paused: guard === "paused",
          id: guard === "identity" ? "other" : template.id,
        },
        200,
        guard === "missing-etag" ? "" : '"version:1"',
      );
    }),
  );
  render(
    <TaskTemplateCard
      bidId="bid"
      memberId="member"
      id="template"
      kinds={guard === "capability" ? { ...kinds, items: [] } : kinds}
      executionBlocked={guard === "fee"}
      onChanged={vi.fn()}
      onRun={vi.fn()}
    />,
  );
  await waitFor(() => expect(reads).toBe(1));
  act(() => window.dispatchEvent(new Event("server-snapshot-change")));
  await waitFor(() => expect(reads).toBe(2));
  if (guard === "identity")
    expect(
      screen.queryByRole("button", { name: "手动运行当前版本" }),
    ).not.toBeInTheDocument();
  else {
    await waitFor(() => expect(button()).toBeDisabled());
    fireEvent.click(button());
  }
  expect(posts).toHaveLength(0);
});

it("运行请求未完成时后台刷新和重复点击不重复发送", async () => {
  let release!: (response: Response) => void;
  const posts: RequestInit[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: RequestInfo | URL, options?: RequestInit) => {
      if (options?.method === "POST") {
        posts.push(options);
        return new Promise<Response>((resolve) => {
          release = resolve;
        });
      }
      return json(template);
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
  await screen.findByRole("button", { name: "手动运行当前版本" });
  fireEvent.click(button());
  await waitFor(() => expect(button()).toBeDisabled());
  act(() => window.dispatchEvent(new Event("server-snapshot-change")));
  fireEvent.click(button());
  expect(posts).toHaveLength(1);
  await act(async () => release(json({ id: "run", bid_id: "bid" })));
  expect(posts).toHaveLength(1);
});

it.each(
  ["version", "digest", "etag"].flatMap((field) =>
    ["pointer", "Enter", " "].map((activation) => ({ field, activation })),
  ),
)(
  "仅 $field 变更后旧 $activation 手势失效，新按钮需另一次明确激活",
  async ({ field, activation }) => {
    let reads = 0;
    let release!: (response: Response) => void;
    const posts: RequestInit[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, options?: RequestInit) => {
        if (options?.method === "POST") {
          posts.push(options);
          return json({ id: "run", bid_id: "bid" });
        }
        reads++;
        return reads === 1
          ? json(template)
          : new Promise<Response>((resolve) => {
              release = resolve;
            });
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
    const original = await screen.findByRole("button", {
      name: "手动运行当前版本",
    });
    if (activation === "pointer") fireEvent.pointerDown(original);
    else fireEvent.keyDown(original, { key: activation });
    act(() => window.dispatchEvent(new Event("server-snapshot-change")));
    await waitFor(() => expect(reads).toBe(2));
    await act(async () =>
      release(
        json(
          {
            ...template,
            version_id: field === "version" ? "version2" : template.version_id,
            revision: field === "version" ? 2 : template.revision,
            digest: field === "digest" ? "e".repeat(64) : template.digest,
          },
          200,
          field === "etag" ? '"version:2"' : '"version:1"',
        ),
      ),
    );
    expect(button()).not.toBe(original);
    // Chrome touch can retarget the synthesized click to the new button.
    if (activation === "pointer") fireEvent.pointerUp(button());
    else fireEvent.keyUp(button(), { key: activation });
    fireEvent.click(button(), { detail: activation === "pointer" ? 1 : 0 });
    expect(posts).toHaveLength(0);
    fireEvent.pointerDown(button());
    fireEvent.pointerUp(button());
    fireEvent.click(button(), { detail: 1 });
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(new Headers(posts[0].headers).get("If-Match")).toBe(
      field === "etag" ? '"version:2"' : '"version:1"',
    );
  },
);

it.each(["cancelled", "missing"])(
  "%s 指针开始记录不能授权运行，辅助点击仍可明确运行",
  async (mode) => {
    const posts: RequestInit[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, options?: RequestInit) => {
        if (options?.method === "POST") {
          posts.push(options);
          return json({ id: "run", bid_id: "bid" });
        }
        return json(template);
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
    await screen.findByRole("button", { name: "手动运行当前版本" });
    if (mode === "cancelled") {
      fireEvent.pointerDown(button());
      fireEvent.pointerCancel(button());
    }
    fireEvent.click(button(), { detail: 1 });
    expect(posts).toHaveLength(0);
    fireEvent.click(button(), { detail: 0 });
    await waitFor(() => expect(posts).toHaveLength(1));
  },
);

it("a different physical pointer cannot consume another pointer's activation", async () => {
  const posts: RequestInit[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: RequestInfo | URL, options?: RequestInit) => {
      if (options?.method === "POST") {
        posts.push(options);
        return json({ id: "run", bid_id: "bid" });
      }
      return json(template);
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
  await screen.findByRole("button", { name: "手动运行当前版本" });
  function pointer(type: "pointerdown" | "click", id: number) {
    const event = new MouseEvent(type, {
      bubbles: true,
      detail: type === "click" ? 1 : 0,
    });
    Object.defineProperties(event, {
      pointerId: { value: id },
      pointerType: { value: "touch" },
    });
    fireEvent(button(), event);
  }
  pointer("pointerdown", 1);
  pointer("click", 2);
  expect(posts).toHaveLength(0);
  pointer("click", 1);
  expect(posts).toHaveLength(0);
  pointer("pointerdown", 1);
  pointer("click", 1);
  await waitFor(() => expect(posts).toHaveLength(1));
});
