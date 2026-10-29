import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { setAuth } from "./api";
import { PackageAuthoringTemplateEditor } from "./PackageAuthoringTemplateEditor";
import { PackageAuthoringRunControl } from "./PackageAuthoringRunControl";
import { AssistantActionCard } from "./AssistantActionCard";
import { TaskRunCard } from "./TaskRunCard";
import { packageAuthoringFixture } from "./packageAuthoringFixtures.test-support";
import { taskPackageStorageKey } from "./useTaskPackageCommand";
import { validatePackageAuthoringRun } from "./taskPackageAuthoringProtocol";

const f = packageAuthoringFixture(),
  bidId = f.template.bid_id,
  memberId = f.member_id;
function json(data: unknown, etag?: string, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json",
      ...(etag ? { ETag: etag } : {}),
    },
  });
}
function transport({
  state = "published",
  writes,
  reads,
}: {
  state?: keyof typeof f.runs;
  writes?: (path: string, init: RequestInit) => Response | Promise<Response>;
  reads?: (path: string) => Response | Promise<Response> | undefined;
} = {}) {
  const sent: { path: string; init: RequestInit }[] = [],
    unexpected: string[] = [];
  const selected = f.scenarios[state] ?? f,
    currentBid = selected.template.bid_id;
  let run = structuredClone(f.runs[state]);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init: RequestInit = {}) => {
      const path = new URL(input, window.location.href).pathname;
      if (init.method && init.method !== "GET") {
        sent.push({ path, init });
        if (writes) return writes(path, init);
        unexpected.push(`${init.method} ${path}`);
        return json({ code: "UNEXPECTED_WRITE" }, undefined, 500);
      }
      const override = reads?.(path);
      if (override) return override;
      if (path === `/api/v1/bids/${currentBid}`)
        return json(selected.bid, selected.bid_etag);
      if (path === "/api/v1/task-kinds") return json(selected.kinds);
      if (path === `/api/v1/bids/${bidId}/authoring/package-inputs`)
        return json(f.input_page);
      if (
        path ===
        `/api/v1/bids/${currentBid}/authoring/package-inputs/${selected.input.manifest.id}`
      )
        return json(selected.input);
      if (
        path ===
        `/api/v1/bids/${currentBid}/authoring/package-inputs/${selected.input.manifest.id}/context`
      )
        return json(selected.context);
      if (
        path ===
        `/api/v1/bids/${currentBid}/task-definitions/${selected.template.id}`
      )
        return json(selected.template, selected.template_etag);
      if (
        path ===
        `/api/v1/bids/${currentBid}/task-definitions/${selected.template.id}/versions/${selected.template.version_id}`
      )
        return json(selected.template_version);
      if (path === `/api/v1/bids/${run.bid_id}/task-runs/${run.id}`)
        return json(run);
      if (path === `/api/v1/operations/${run.root_operation_id}`)
        return json(f.operations[state].data, f.operations[state].etag);
      if (path === `/api/v1/assistant/actions/${f.proposal.action_id}`)
        return json(f.proposal, f.proposal_etag);
      unexpected.push(`GET ${path}`);
      return json({ code: "UNEXPECTED_READ" }, undefined, 404);
    }),
  );
  return {
    sent,
    unexpected,
    setRun: (next: typeof run) => {
      run = next;
    },
  };
}
beforeEach(() => {
  sessionStorage.clear();
  window.history.replaceState({}, "", "/");
  setAuth({
    member: { id: memberId, display_name: "合成整包编写验收", active: true },
    csrf_token: "synthetic",
    expires_at: "2099-01-01T00:00:00Z",
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
function editorProps() {
  return {
    bidId,
    memberId,
    template: null,
    etag: f.bid_etag,
    onSaved: vi.fn(),
    onClose: vi.fn(),
  };
}

it("requires an explicit saved input choice and saves the exact template without starting a job", async () => {
  const calls = transport({
      writes: () => json(f.template, f.template_etag, 201),
    }),
    props = editorProps(),
    user = userEvent.setup();
  render(<PackageAuthoringTemplateEditor {...props} />);
  const save = screen.getByRole("button", {
    name: "保存固定整包编写模板，不运行",
  });
  expect(save).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "读取固定输入目录" }));
  await user.click(
    await screen.findByRole("button", { name: /选择这份编写输入/ }),
  );
  await user.type(
    screen.getByLabelText("固定整包编写模板名称"),
    f.template.configuration.name,
  );
  await user.type(
    screen.getByLabelText("固定整包编写要求"),
    f.template.configuration.instructions,
  );
  await waitFor(() => expect(save).toBeEnabled());
  await user.click(save);
  await waitFor(() => expect(props.onSaved).toHaveBeenCalledWith(f.template));
  expect(calls.sent).toHaveLength(1);
  expect(JSON.parse(String(calls.sent[0].init.body))).toEqual(
    f.template.configuration,
  );
  expect(calls.sent[0].path).toBe(`/api/v1/bids/${bidId}/task-definitions`);
  expect(calls.unexpected).toEqual([]);
});
it("restores the original lost template request after remount, including key and input, without a new selection", async () => {
  let n = 0;
  const calls = transport({
    writes: () => {
      if (++n === 1) throw new TypeError("lost ACK");
      return json(f.template, f.template_etag, 201);
    },
  });
  const props = {
      ...editorProps(),
      initialConfiguration: f.template.configuration,
    },
    user = userEvent.setup();
  const first = render(<PackageAuthoringTemplateEditor {...props} />);
  const save = await screen.findByRole("button", {
    name: "保存固定整包编写模板，不运行",
  });
  await waitFor(() => expect(save).toBeEnabled());
  await user.click(save);
  await screen.findByRole("button", { name: "恢复原固定整包模板保存结果" });
  first.unmount();
  render(<PackageAuthoringTemplateEditor {...props} />);
  await user.click(
    await screen.findByRole("button", { name: "恢复原固定整包模板保存结果" }),
  );
  await waitFor(() => expect(props.onSaved).toHaveBeenCalled());
  expect(calls.sent[1]).toEqual(calls.sent[0]);
  expect(
    sessionStorage.getItem(
      taskPackageStorageKey({
        kind: "authoring_template",
        memberId,
        bidId,
        identity: "new",
      }),
    ),
  ).toBeNull();
});
it("validates B2 execution independently from the B1 generation=false capture response", async () => {
  const calls = transport({
      writes: () => json(f.runs.queued, undefined, 202),
    }),
    onRun = vi.fn();
  render(
    <PackageAuthoringRunControl
      bidId={bidId}
      memberId={memberId}
      id={f.template.id}
      template={f.template}
      etag={f.template_etag}
      kinds={f.kinds}
      disabled={false}
      onRun={onRun}
      onChanged={vi.fn()}
    />,
  );
  const run = screen.getByRole("button", { name: "手动生成固定整包章节候选" });
  await waitFor(() => expect(run).toBeEnabled());
  await userEvent.click(run);
  await waitFor(() => expect(onRun).toHaveBeenCalledWith(f.runs.queued.id));
  expect(calls.sent).toHaveLength(1);
  expect(JSON.parse(String(calls.sent[0].init.body))).toEqual({ rerun: false });
  expect(calls.unexpected).toEqual([]);
});
it("shows the bound full proposal and concrete changes without a write or legacy source claim", async () => {
  const calls = transport();
  render(
    <TaskRunCard bidId={bidId} memberId={memberId} id={f.runs.published.id} />,
  );
  await userEvent.click(
    await screen.findByRole("button", {
      name: "核对固定整包章节候选的原稿与拟稿",
    }),
  );
  const link = await screen.findByRole("link", {
    name: "打开这份固定整包候选操作卡",
  });
  expect(link).toHaveAttribute(
    "href",
    `/assistant?action=${f.proposal.action_id}`,
  );
  await userEvent.click(await screen.findByText("查看具体文字增删"));
  expect(await screen.findByLabelText("拟修改后全文")).toHaveTextContent(
    "来自合成完整整包的可审阅修改建议；尚未采用。",
  );
  expect(screen.queryByText(/尚未绑定固定整包/)).not.toBeInTheDocument();
  expect(calls.sent).toEqual([]);
  expect(calls.unexpected).toEqual([]);
});
it.each(["awaiting-publication", "unknown-fee", "cancelled-before"] as const)(
  "does not publish a false candidate for native %s",
  async (state) => {
    const calls = transport({ state });
    render(
      <TaskRunCard
        bidId={f.runs[state].bid_id}
        memberId={memberId}
        id={f.runs[state].id}
      />,
    );
    await screen.findByRole("heading", { name: "固定整包章节编写" });
    expect(
      screen.queryByRole("button", {
        name: "核对固定整包章节候选的原稿与拟稿",
      }),
    ).not.toBeInTheDocument();
    expect(calls.sent).toEqual([]);
  },
);
it("keeps the last verified result read-only after a tampered update and never falls back to legacy chapter rendering", async () => {
  const calls = transport();
  render(
    <TaskRunCard bidId={bidId} memberId={memberId} id={f.runs.published.id} />,
  );
  await screen.findByRole("button", {
    name: "核对固定整包章节候选的原稿与拟稿",
  });
  const damaged = structuredClone(f.runs.published);
  damaged.result!.job_id = "00000000-0000-4000-8000-000000009999";
  calls.setRun(damaged);
  act(() => window.dispatchEvent(new Event("server-snapshot-change")));
  expect(await screen.findByText(/最新读取尚未通过核验/)).toBeVisible();
  expect(
    screen.getByRole("button", { name: "核对固定整包章节候选的原稿与拟稿" }),
  ).toBeDisabled();
  expect(screen.queryByText(/尚未绑定固定整包/)).not.toBeInTheDocument();
});
it("shows the actual package action comparison while adoption remains unavailable", async () => {
  const calls = transport();
  render(<AssistantActionCard id={f.proposal.action_id} memberId={memberId} />);
  expect(
    await screen.findByRole("button", { name: "此固定整包候选暂不可采纳" }),
  ).toBeDisabled();
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "拒绝此提议" })).toBeEnabled(),
  );
  await userEvent.click(await screen.findByText("查看具体文字增删"));
  expect(await screen.findByLabelText("拟修改后全文")).toHaveTextContent(
    "尚未采用",
  );
  expect(calls.sent).toEqual([]);
  expect(calls.unexpected).toEqual([]);
});

it("keeps the original frozen identity when a later individually valid response changes its actor", async () => {
  const calls = transport();
  render(
    <TaskRunCard bidId={bidId} memberId={memberId} id={f.runs.published.id} />,
  );
  await screen.findByRole("button", {
    name: "核对固定整包章节候选的原稿与拟稿",
  });
  const changed = structuredClone(f.runs.published);
  changed.frozen_manifest.actor_id = "00000000-0000-4000-8000-000000009999";
  // This is a valid standalone shape, but cannot replace this run's first
  // verified immutable manifest during a subsequent refresh.
  await expect(
    validatePackageAuthoringRun(changed, bidId, changed.id),
  ).resolves.toEqual(changed);
  calls.setRun(changed);
  act(() => window.dispatchEvent(new Event("server-snapshot-change")));
  expect(await screen.findByText(/原冻结身份发生变化/)).toBeVisible();
  expect(
    screen.getByRole("button", { name: "核对固定整包章节候选的原稿与拟稿" }),
  ).toBeDisabled();
  expect(calls.sent).toEqual([]);
});

it.each([false, true])(
  "refuses a duplicate semantic job and only links a same-project original task (foreign=%s)",
  async (foreign) => {
    const original = f.runs.published,
      calls = transport({
        writes: () =>
          json(
            {
              code: "AUTHORING_PACKAGE_ORIGINAL_JOB_REQUIRED",
              message: "相同内容已有原编写任务",
              retryable: false,
              details: {
                bid_id: foreign
                  ? "00000000-0000-4000-8000-000000009999"
                  : bidId,
                job_id: original.result!.job_id,
                task_run_id: original.id,
                new_attempt_authorized: false,
              },
            },
            undefined,
            409,
          ),
      });
    render(
      <PackageAuthoringRunControl
        bidId={bidId}
        memberId={memberId}
        id={f.template.id}
        template={f.template}
        etag={f.template_etag}
        kinds={f.kinds}
        disabled={false}
        onRun={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    const run = screen.getByRole("button", {
      name: "手动生成固定整包章节候选",
    });
    await waitFor(() => expect(run).toBeEnabled());
    await userEvent.click(run);
    await screen.findByText(/本次没有新建调用/);
    expect(run).toBeDisabled();
    const link = screen.queryByRole("link", {
      name: "打开对应的原编写任务",
    });
    if (foreign) expect(link).toBeNull();
    else
      expect(link).toHaveAttribute(
        "href",
        `/bids/${bidId}/tasks?run=${original.id}`,
      );
    expect(
      screen.queryByRole("button", { name: "恢复原固定整包编写受理结果" }),
    ).not.toBeInTheDocument();
    expect(calls.sent).toHaveLength(1);
    expect(calls.unexpected).toEqual([]);
  },
);
