import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { setAuth } from "./api";
import { TaskRunCard } from "./TaskRunCard";
import {
  taskChapterFixtures,
  type TaskChapterHTTP,
} from "./taskChapterFixtures.test-support";

const fixtures = taskChapterFixtures();
function json(value: unknown, etag?: string) {
  return new Response(JSON.stringify(value), {
    headers: {
      "Content-Type": "application/json",
      ...(etag ? { ETag: etag } : {}),
    },
  });
}
function transport(initial: TaskChapterHTTP) {
  let record = structuredClone(initial);
  const calls: { path: string; method: string }[] = [];
  const unexpected: string[] = [];
  const read = vi.fn(async (input: string, options: RequestInit = {}) => {
    const path = new URL(input, window.location.href).pathname;
    const method = options.method ?? "GET";
    calls.push({ path, method });
    const run = record.run;
    if (method === "GET") {
      if (path === `/api/v1/bids/${run.bid_id}/task-runs/${run.id}`)
        return json(run);
      if (
        path ===
        `/api/v1/bids/${run.bid_id}/task-definitions/${run.frozen_manifest.definition_id}/versions/${run.definition_version_id}`
      )
        return json(record.template_version);
      if (path === `/api/v1/operations/${run.root_operation_id}`)
        return json(record.operation, record.operation_etag);
      if (
        record.proposal &&
        path === `/api/v1/assistant/actions/${String(run.result?.action_id)}`
      )
        return json(record.proposal);
    }
    unexpected.push(`${method} ${path}`);
    throw new Error("Unexpected fixture request");
  });
  vi.stubGlobal("fetch", read);
  return {
    calls,
    unexpected,
    set: (next: TaskChapterHTTP) => {
      record = structuredClone(next);
    },
  };
}
function show(record: TaskChapterHTTP) {
  const run = record.run;
  setAuth({
    member: {
      id: String(run.frozen_manifest.actor_id),
      display_name: "合成原生任务验收",
      active: true,
    },
    csrf_token: "synthetic",
    expires_at: "2099-01-01T00:00:00Z",
  });
  return render(
    <TaskRunCard
      bidId={run.bid_id}
      id={run.id}
      memberId={String(run.frozen_manifest.actor_id)}
    />,
  );
}
beforeEach(() => {
  sessionStorage.clear();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("keeps candidate_ready pending despite a succeeded native operation and exposes no adoption action", async () => {
  const record = fixtures["awaiting-publication"],
    requests = transport(record);
  show(record);
  expect(await screen.findByText("等待提案发布")).toBeVisible();
  expect(
    await screen.findByText(/模型候选已保存，正在等待原生提案发布/),
  ).toBeVisible();
  expect(screen.queryByText("已记录处理结果")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "核对本任务绑定的章节提案" }),
  ).not.toBeInTheDocument();
  expect(requests.calls.every((c) => c.method === "GET")).toBe(true);
  expect(requests.unexpected).toEqual([]);
});

it("shows the exact native proposal, original text and concrete change without any write", async () => {
  const record = fixtures.published,
    requests = transport(record);
  show(record);
  expect(await screen.findByText(/尚未绑定固定整包/)).toBeVisible();
  await userEvent.click(
    await screen.findByRole("button", { name: "核对本任务绑定的章节提案" }),
  );
  const link = await screen.findByRole("link", {
    name: "打开这份提案的持久操作卡",
  });
  expect(link).toHaveAttribute(
    "href",
    `/assistant?action=${record.proposal!.action_id}`,
  );
  await userEvent.click(await screen.findByText("查看具体文字增删"));
  expect(await screen.findByLabelText("拟修改后全文")).toHaveTextContent(
    "合成原页支持的修改建议，尚未采纳",
  );
  expect(screen.getByLabelText("修改前全文")).toHaveTextContent("原正文一");
  expect(
    screen.queryByRole("button", { name: "应用这份正文修改" }),
  ).not.toBeInTheDocument();
  expect(requests.calls.every((c) => c.method === "GET")).toBe(true);
  expect(requests.unexpected).toEqual([]);
});

it.each([
  "job_id",
  "target_bid_id",
  "section_id",
  "base_section_revision",
] as const)(
  "does not display or link a proposal whose %s differs from the original task",
  async (field) => {
    const record = structuredClone(fixtures.published);
    if (field === "section_id" || field === "base_section_revision") {
      if (record.proposal!.preview.kind !== "authoring_patch")
        throw new Error("native patch fixture");
      if (field === "section_id")
        record.proposal!.preview.section_id = "another-section";
      else record.proposal!.preview.base_section_revision++;
    } else record.proposal![field] = "another-identity";
    const requests = transport(record);
    show(record);
    await userEvent.click(
      await screen.findByRole("button", { name: "核对本任务绑定的章节提案" }),
    );
    expect(
      await screen.findByText(/原生提案与本任务的项目、章节或原始 job 不一致/),
    ).toBeVisible();
    expect(screen.queryByText("查看具体文字增删")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "打开这份提案的持久操作卡" }),
    ).not.toBeInTheDocument();
    expect(requests.unexpected).toEqual([]);
  },
);

it("refuses a false task success if its result identifies another native job", async () => {
  const record = structuredClone(fixtures.published);
  record.run.result!.job_id = "10000000-0000-4000-8000-000000000000";
  const requests = transport(record);
  show(record);
  expect(await screen.findByText("章节结果关联待核对")).toBeVisible();
  expect(screen.queryByText("已记录处理结果")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "核对本任务绑定的章节提案" }),
  ).not.toBeInTheDocument();
  expect(
    requests.calls.some((c) => c.path.includes("/assistant/actions/")),
  ).toBe(false);
});

it("removes the old proposal when the current task read no longer confirms its publication", async () => {
  const record = fixtures.published,
    requests = transport(record);
  show(record);
  await userEvent.click(
    await screen.findByRole("button", { name: "核对本任务绑定的章节提案" }),
  );
  await screen.findByRole("link", { name: "打开这份提案的持久操作卡" });
  // Explicit adversarial stale response: actual pending and published fixtures share one task ID.
  requests.set(fixtures["awaiting-publication"]);
  act(() => window.dispatchEvent(new Event("server-snapshot-change")));
  await waitFor(() =>
    expect(
      screen.queryByRole("link", { name: "打开这份提案的持久操作卡" }),
    ).not.toBeInTheDocument(),
  );
  expect(await screen.findByText("等待提案发布")).toBeVisible();
});

it.each([
  ["stale-section", "原输入已过期"],
  ["failed", "执行失败"],
  ["cancelled", "已取消"],
  ["unknown-fee", "需核对调用账本"],
] as const)(
  "explains the real %s state without a false proposal",
  async (name, label) => {
    const record = fixtures[name],
      requests = transport(record);
    show(record);
    expect(await screen.findByText(label)).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "核对本任务绑定的章节提案" }),
    ).not.toBeInTheDocument();
    expect(requests.calls.every((c) => c.method === "GET")).toBe(true);
    expect(requests.unexpected).toEqual([]);
  },
);
