import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ProjectLifecyclePanel } from "./ProjectLifecyclePanel";
import type { ProjectLifecycleView } from "./contracts";
import { setAuth } from "./api";

const initial: ProjectLifecycleView = {
  bid_id: "bid",
  phase: "preparation",
  archived_at: null,
  revision: 1,
  allowed_actions: ["start", "terminate"],
  archive_blockers: [],
  active_operations: [],
  unfinished_uploads: [],
  unfinished_batches: [],
  batch_closure_available: true,
};
const json = (value: unknown, status = 200, tag = '"life:1"') =>
  new Response(JSON.stringify(value), { status, headers: { ETag: tag } });
beforeEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
  setAuth({
    member: { id: "member", display_name: "合成", active: true },
    csrf_token: "csrf",
    expires_at: "2099-01-01T00:00:00Z",
  });
});
it("server actions only, cancel sends nothing, reason required, double submit records once", async () => {
  const user = userEvent.setup();
  const writes: RequestInit[] = [];
  let current = initial;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, options?: RequestInit) => {
      if (options?.method === "POST") {
        writes.push(options);
        current = {
          ...initial,
          phase: "working",
          revision: 2,
          allowed_actions: ["terminate"],
        };
      }
      return json(current);
    }),
  );
  render(
    <ProjectLifecyclePanel
      bidId="bid"
      memberId="member"
      onChanged={() => {}}
    />,
  );
  await user.click(await screen.findByRole("button", { name: "终止本轮工作" }));
  expect(
    screen.getByRole("button", { name: "确认终止本轮工作" }),
  ).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "取消此次变更" }));
  expect(writes).toHaveLength(0);
  expect(
    screen.queryByRole("button", { name: "结束本轮工作" }),
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "开始本轮工作" }));
  await user.type(
    screen.getByLabelText("本次状态变更原因"),
    "  合成人工开始  ",
  );
  const form = screen.getByLabelText("本次状态变更原因").closest("form")!;
  fireEvent.submit(form);
  fireEvent.submit(form);
  await screen.findByText(/状态变更已记录/);
  expect(writes).toHaveLength(1);
  expect(JSON.parse(String(writes[0].body))).toEqual({
    action: "start",
    reason: "合成人工开始",
  });
  expect(new Headers(writes[0].headers).get("If-Match")).toBe('"life:1"');
});
it("412 retains reason, never rebases automatically, explicit refresh requires choosing again", async () => {
  const user = userEvent.setup();
  let tag = '"old"';
  let current = initial;
  const writes: RequestInit[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, options?: RequestInit) => {
      if (options?.method === "POST") {
        writes.push(options);
        tag = '"new"';
        current = {
          ...initial,
          phase: "working",
          revision: 2,
          allowed_actions: ["terminate"],
        };
        return json({ code: "REVISION_CONFLICT", message: "旧版本拒绝" }, 412);
      }
      return json(current, 200, tag);
    }),
  );
  render(
    <ProjectLifecyclePanel
      bidId="bid"
      memberId="member"
      onChanged={() => {}}
    />,
  );
  await user.click(await screen.findByRole("button", { name: "终止本轮工作" }));
  await user.type(screen.getByLabelText("本次状态变更原因"), "保留核对原因");
  await user.click(screen.getByRole("button", { name: "确认终止本轮工作" }));
  await screen.findByText(/项目状态已变化/);
  expect(screen.getByLabelText("本次状态变更原因")).toHaveValue("保留核对原因");
  expect(
    screen.getByRole("button", { name: "确认终止本轮工作" }),
  ).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "重新读取项目状态" }));
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: "确认终止本轮工作" }),
    ).not.toBeInTheDocument(),
  );
  expect(writes).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "终止本轮工作" }));
  expect(screen.getByLabelText("本次状态变更原因")).toHaveValue("保留核对原因");
});
it("lost ACK survives remount with exact original request; another member cannot recover it", async () => {
  const user = userEvent.setup();
  const writes: RequestInit[] = [];
  let current = initial;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, options?: RequestInit) => {
      if (options?.method === "POST") {
        writes.push(options);
        current = {
          ...initial,
          phase: "working",
          revision: 2,
          allowed_actions: ["terminate"],
        };
        if (writes.length === 1) throw new TypeError("isolated lost ACK");
      }
      return json(current);
    }),
  );
  const view = render(
    <ProjectLifecyclePanel
      bidId="bid"
      memberId="member"
      onChanged={() => {}}
    />,
  );
  await user.click(await screen.findByRole("button", { name: "开始本轮工作" }));
  await user.type(screen.getByLabelText("本次状态变更原因"), "原冻结原因");
  await user.click(screen.getByRole("button", { name: "确认开始本轮工作" }));
  await screen.findByRole("button", { name: "恢复原状态变更回执" });
  view.unmount();
  const other = render(
    <ProjectLifecyclePanel bidId="bid" memberId="other" onChanged={() => {}} />,
  );
  expect(
    screen.queryByRole("button", { name: "恢复原状态变更回执" }),
  ).not.toBeInTheDocument();
  other.unmount();
  render(
    <ProjectLifecyclePanel
      bidId="bid"
      memberId="member"
      onChanged={() => {}}
    />,
  );
  await user.click(
    await screen.findByRole("button", { name: "恢复原状态变更回执" }),
  );
  await screen.findByText(/状态变更已记录/);
  expect(writes).toHaveLength(2);
  for (const header of ["Idempotency-Key", "If-Match"])
    expect(new Headers(writes[1].headers).get(header)).toBe(
      new Headers(writes[0].headers).get(header),
    );
  expect(writes[1].body).toEqual(writes[0].body);
});
it("archive blockers and submitted-only end follow authoritative capabilities", async () => {
  const current = {
    ...initial,
    phase: "terminated",
    allowed_actions: ["reopen"],
    archive_blockers: ["OPERATIONS_IN_FLIGHT"],
    active_operations: [
      { id: "op", kind: "review", state: "cancel_requested" },
    ],
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => json(current)),
  );
  const view = render(
    <ProjectLifecyclePanel
      bidId="bid"
      memberId="member"
      onChanged={() => {}}
    />,
  );
  await screen.findByText(/仍有后台任务/);
  expect(
    screen.queryByRole("button", { name: "归档项目" }),
  ).not.toBeInTheDocument();
  view.unmount();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      json({
        ...initial,
        phase: "submitted",
        allowed_actions: ["end", "terminate"],
      }),
    ),
  );
  render(
    <ProjectLifecyclePanel
      bidId="bid"
      memberId="member"
      onChanged={() => {}}
    />,
  );
  expect(
    await screen.findByRole("button", { name: "结束本轮工作" }),
  ).toBeEnabled();
});
it("late old project acknowledgement cannot update the new project", async () => {
  const user = userEvent.setup();
  let finish!: (response: Response) => void;
  const changed = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) =>
      options?.method === "POST"
        ? new Promise<Response>((resolve) => {
            finish = resolve;
          })
        : json({ ...initial, bid_id: url.includes("other") ? "other" : "bid" }),
    ),
  );
  const view = render(
    <ProjectLifecyclePanel bidId="bid" memberId="member" onChanged={changed} />,
  );
  await user.click(await screen.findByRole("button", { name: "开始本轮工作" }));
  await user.type(screen.getByLabelText("本次状态变更原因"), "旧项目原因");
  await user.click(screen.getByRole("button", { name: "确认开始本轮工作" }));
  view.rerender(
    <ProjectLifecyclePanel
      key="other"
      bidId="other"
      memberId="member"
      onChanged={changed}
    />,
  );
  await act(async () => {
    finish(json({ ...initial, phase: "working" }));
  });
  expect(changed).not.toHaveBeenCalled();
  expect(screen.queryByText(/状态变更已记录/)).not.toBeInTheDocument();
});
it("foreign view and tampered stored target fail closed", async () => {
  sessionStorage.setItem(
    "tender:command-record:lifecycle:member:bid",
    JSON.stringify({
      path: "/bids/foreign/lifecycle",
      body: { action: "start", reason: "wrong target" },
      etag: '"tag"',
      key: "key",
    }),
  );
  const fetcher = vi.fn(async () => json({ ...initial, bid_id: "foreign" }));
  vi.stubGlobal("fetch", fetcher);
  render(
    <ProjectLifecyclePanel
      bidId="bid"
      memberId="member"
      onChanged={() => {}}
    />,
  );
  await screen.findByText("项目状态身份不一致，不能操作。");
  expect(
    screen.queryByRole("button", { name: "开始本轮工作" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "恢复原状态变更回执" }),
  ).toBeDisabled();
});

it("announces success only after the shared refresh settles and still rejects a later stale reopen intent", async () => {
  let finishRefresh!: (response: Response) => void;
  let finishLaterRead!: (response: Response) => void;
  const refresh = new Promise<Response>((resolve) => {
    finishRefresh = resolve;
  });
  const laterRead = new Promise<Response>((resolve) => {
    finishLaterRead = resolve;
  });
  const terminated: ProjectLifecycleView = {
    ...initial,
    phase: "terminated",
    revision: 2,
    allowed_actions: ["reopen"],
  };
  let gets = 0;
  const writes: RequestInit[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, options?: RequestInit) => {
      if (options?.method === "POST") {
        writes.push(options);
        return json(terminated, 200, '"life:2"');
      }
      gets++;
      return gets === 1 ? json(initial) : gets === 2 ? refresh : laterRead;
    }),
  );
  const changed = vi.fn();
  render(
    <ProjectLifecyclePanel bidId="bid" memberId="member" onChanged={changed} />,
  );
  const user = userEvent.setup();
  const terminate = await screen.findByRole("button", {
    name: "终止本轮工作",
  });
  await waitFor(() => expect(terminate).toBeEnabled());
  await user.click(terminate);
  await user.type(screen.getByLabelText("本次状态变更原因"), "合成终止原因");
  await user.click(screen.getByRole("button", { name: "确认终止本轮工作" }));
  await waitFor(() => expect(gets).toBe(2));
  expect(changed).toHaveBeenCalledTimes(1);
  expect(screen.queryByText(/状态变更已记录/)).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "重新打开项目" }),
  ).not.toBeInTheDocument();
  await act(async () => {
    finishRefresh(json(terminated, 200, '"life:2"'));
  });
  await screen.findByText(/状态变更已记录/);
  expect(gets).toBe(2);
  const reopen = screen.getByRole("button", {
    name: "重新打开项目",
  });
  expect(reopen).toBeEnabled();
  await user.click(reopen);
  await user.type(
    screen.getByLabelText("本次状态变更原因"),
    "合成快速恢复原因",
  );
  const confirm = screen.getByRole("button", {
    name: "确认重新打开项目",
  });
  expect(confirm).toBeEnabled();
  act(() => {
    window.dispatchEvent(new Event("server-snapshot-change"));
  });
  expect(confirm).toBeDisabled();
  await act(async () => {
    finishLaterRead(json({ ...terminated, revision: 3 }, 200, '"life:3"'));
  });
  await screen.findByText(/项目状态已变化/);
  expect(confirm).toBeDisabled();
  fireEvent.submit(screen.getByLabelText("本次状态变更原因").closest("form")!);
  expect(writes).toHaveLength(1);
  expect(JSON.parse(String(writes[0].body)).action).toBe("terminate");
});
