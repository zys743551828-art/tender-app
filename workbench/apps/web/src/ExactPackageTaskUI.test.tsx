import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { setAuth } from "./api";
import { TaskTemplateEditor } from "./TaskTemplateEditor";
import { TaskTemplateCard } from "./TaskTemplateCard";
import { TaskRunCard } from "./TaskRunCard";
import { ExactPackageTaskRunControl } from "./ExactPackageTaskRunControl";
import { PackageScopeGuardProvider } from "./PackageScopeGuardProvider";
import { usePackageScopeState } from "./packageScopeGuard";
import {
  taskPackageFixture,
  type TaskPackageHTTPFixture,
} from "./taskPackageFixtures.test-support";
import { normalizeTaskPackageRequest } from "./taskPackageProtocol";
import { taskPackageStorageKey } from "./useTaskPackageCommand";

const f = taskPackageFixture();
const bidId = f.created.data.bid_id;
const memberId = String(f.queued.data.frozen_manifest.actor_id);
const initial = f.created.data.configuration;
const selection = normalizeTaskPackageRequest(initial).source_selection.input;
const identity = `package:${selection.execution_input_id}:${selection.dependency_plan_id}`;
const createdTag = f.created.headers.etag;
const bidTag = f.created.request.headers!["if-match"];
function response(data: unknown, status = 200, etag?: string) {
  return new Response(JSON.stringify(data), {
    status,
    headers: etag ? { ETag: etag } : {},
  });
}
function reply(value: TaskPackageHTTPFixture<unknown>) {
  return new Response(JSON.stringify(value.data), {
    status: value.status,
    headers: value.headers,
  });
}
function failure(code: string, status: number) {
  return response({ code, message: code, retryable: false }, status);
}
function recoveryKey(
  kind: "template" | "run",
  id = kind === "template" ? identity : f.created.data.id,
) {
  return taskPackageStorageKey({ kind, memberId, bidId, identity: id });
}
function setup(
  writes: (
    url: string,
    init: RequestInit,
  ) => Promise<Response> | Response = () => reply(f.created),
  reads?: (url: string) => Response | Promise<Response> | undefined,
) {
  const paths: string[] = [],
    sent: RequestInit[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const path = new URL(input, window.location.href).pathname;
      paths.push(path);
      if (init?.method && init.method !== "GET") {
        sent.push(init);
        return writes(path, init);
      }
      const override = reads?.(path);
      if (override) return override;
      if (path === f.revised.request.path) return reply(f.created);
      const found = Object.values(f).find(
        (row) =>
          row.request.method === "GET" &&
          row.request.path.split("?")[0] === path,
      );
      if (found) return reply(found);
      if (path.endsWith(`/operations/${f.completed.data.root_operation_id}`))
        return response({
          id: f.completed.data.root_operation_id,
          bid_id: bidId,
          state: "succeeded",
        });
      return response({ items: [], has_more: false, next_cursor: null });
    }),
  );
  return { paths, sent };
}
function editorProps(editing = false) {
  return {
    bidId,
    memberId,
    template: editing ? f.created.data : null,
    etag: editing ? createdTag : bidTag,
    formIdentity: editing ? undefined : identity,
    initialConfiguration: editing ? undefined : initial,
    onSaved: vi.fn(),
    onClose: vi.fn(),
  };
}
function runProps() {
  return {
    bidId,
    memberId,
    template: f.created.data,
    etag: createdTag,
    kinds: f.kinds.data,
    onRun: vi.fn(),
    onChanged: vi.fn(),
  };
}
function GuardState() {
  return (
    <output aria-label="真实任务导航状态">
      {JSON.stringify(usePackageScopeState())}
    </output>
  );
}
async function useRevisedName(user: ReturnType<typeof userEvent.setup>) {
  await user.clear(screen.getByLabelText("模板名称"));
  await user.type(
    screen.getByLabelText("模板名称"),
    f.revised.data.configuration.name,
  );
}

beforeEach(() => {
  sessionStorage.clear();
  window.history.replaceState({}, "", `/bids/${bidId}/tasks`);
  setAuth({
    member: { id: memberId, display_name: "合成任务验收", active: true },
    csrf_token: "synthetic-csrf",
    expires_at: "2099-01-01T00:00:00Z",
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("saves the full exact source unchanged, stays manual and does not read single-body materials or start a run", async () => {
  const user = userEvent.setup(),
    transport = setup(),
    props = editorProps();
  render(<TaskTemplateEditor {...props} />);
  expect(screen.getByLabelText("任务类型")).toHaveAttribute("readonly");
  expect(screen.getByLabelText("触发方式")).toHaveValue("仅手动运行");
  expect(
    screen.queryByRole("combobox", { name: "来源范围" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText(selection.dependency_plan_id)).not.toBeVisible();
  await user.click(screen.getByText("核对完整来源身份与摘要"));
  expect(screen.getByText(selection.dependency_plan_id)).toBeVisible();
  await user.click(
    screen.getByRole("button", { name: "保存任务模板，不运行" }),
  );
  await waitFor(() =>
    expect(props.onSaved).toHaveBeenCalledWith(f.created.data),
  );
  expect(transport.sent).toHaveLength(1);
  expect(JSON.parse(String(transport.sent[0].body))).toEqual(initial);
  expect(
    transport.paths.some(
      (path) => path.endsWith("/materials") || path.endsWith("/runs"),
    ),
  ).toBe(false);
  expect(sessionStorage.getItem(recoveryKey("template"))).toBeNull();
});

it("reports only changed input as dirty and releases it after explicit reset or verified save", async () => {
  const user = userEvent.setup(),
    props = editorProps();
  setup();
  render(
    <PackageScopeGuardProvider>
      <GuardState />
      <TaskTemplateEditor {...props} />
    </PackageScopeGuardProvider>,
  );
  expect(screen.getByLabelText("真实任务导航状态")).toHaveTextContent(
    '"dirty":false',
  );
  await user.type(screen.getByLabelText("任务说明"), "待保存文字");
  expect(screen.getByLabelText("真实任务导航状态")).toHaveTextContent(
    '"dirty":true',
  );
  await user.click(
    screen.getByRole("button", { name: "放弃未发送的文字修改" }),
  );
  expect(screen.getByLabelText("真实任务导航状态")).toHaveTextContent(
    '"dirty":false',
  );
  await user.click(
    screen.getByRole("button", { name: "保存任务模板，不运行" }),
  );
  await waitFor(() => expect(props.onSaved).toHaveBeenCalledTimes(1));
  expect(screen.getByLabelText("真实任务导航状态")).toHaveTextContent(
    '"pending":false',
  );
});

it("updates an exact template with its original readonly input and strict version ACK", async () => {
  const user = userEvent.setup(),
    props = editorProps(true),
    transport = setup(() => reply(f.revised));
  render(<TaskTemplateEditor {...props} />);
  await useRevisedName(user);
  await user.click(
    screen.getByRole("button", { name: "保存任务模板，不运行" }),
  );
  await waitFor(() =>
    expect(props.onSaved).toHaveBeenCalledWith(f.revised.data),
  );
  expect(transport.sent[0].method).toBe("PUT");
  expect(JSON.parse(String(transport.sent[0].body))).toEqual(
    f.revised.request.body,
  );
  expect(new Headers(transport.sent[0].headers).get("If-Match")).toBe(
    createdTag,
  );
});

it("restores a lost exact PUT after remount using its original body, key and ETag even when the prop head advanced", async () => {
  const user = userEvent.setup(),
    props = editorProps(true);
  let lost = true;
  const transport = setup(() => {
    if (lost) throw new TypeError("synthetic lost ACK");
    return reply(f.revised);
  });
  const ui = render(<TaskTemplateEditor {...props} />);
  await useRevisedName(user);
  await user.click(
    screen.getByRole("button", { name: "保存任务模板，不运行" }),
  );
  await screen.findByRole("button", { name: "恢复原模板保存结果" });
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "放弃未发送的文字修改" }),
    ).toBeDisabled(),
  );
  ui.unmount();
  lost = false;
  render(<TaskTemplateEditor {...props} etag={f.revised.headers.etag} />);
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "恢复原模板保存结果" }),
    ).toBeEnabled(),
  );
  await user.click(screen.getByRole("button", { name: "恢复原模板保存结果" }));
  await waitFor(() => expect(props.onSaved).toHaveBeenCalledTimes(1));
  expect(transport.sent).toHaveLength(2);
  expect(transport.sent[1].body).toBe(transport.sent[0].body);
  expect(new Headers(transport.sent[1].headers).get("If-Match")).toBe(
    createdTag,
  );
  expect(new Headers(transport.sent[1].headers).get("Idempotency-Key")).toBe(
    new Headers(transport.sent[0].headers).get("Idempotency-Key"),
  );
});

it.each([401, 403, "bad-etag", "wrong-scope"] as const)(
  "keeps exact template recovery on %s until the original valid receipt arrives",
  async (mode) => {
    const user = userEvent.setup(),
      props = editorProps();
    let good = false;
    const transport = setup(() =>
      good
        ? reply(f.created)
        : typeof mode === "number"
          ? failure("AUTH_REQUIRED", mode)
          : response(
              mode === "wrong-scope"
                ? {
                    ...f.created.data,
                    bid_id: "11111111-1111-4111-8111-111111111111",
                  }
                : f.created.data,
              201,
              mode === "bad-etag" ? '"wrong:1"' : createdTag,
            ),
    );
    render(<TaskTemplateEditor {...props} />);
    await user.click(
      screen.getByRole("button", { name: "保存任务模板，不运行" }),
    );
    await screen.findByRole("button", { name: "恢复原模板保存结果" });
    expect(props.onSaved).not.toHaveBeenCalled();
    const original = sessionStorage.getItem(recoveryKey("template"));
    expect(original).not.toBeNull();
    good = true;
    await user.click(
      screen.getByRole("button", { name: "恢复原模板保存结果" }),
    );
    await waitFor(() => expect(props.onSaved).toHaveBeenCalledTimes(1));
    expect(transport.sent[1].body).toBe(transport.sent[0].body);
    expect(new Headers(transport.sent[1].headers).get("Idempotency-Key")).toBe(
      new Headers(transport.sent[0].headers).get("Idempotency-Key"),
    );
  },
);

it("preserves exact input after 412 and waits for a successful explicit current-template read before a new CAS", async () => {
  const user = userEvent.setup(),
    props = editorProps(true);
  let rejected = false,
    release: ((value: Response) => void) | undefined;
  // Only this third revision ACK is synthetic: original PG configuration/digest remain unchanged.
  const third = {
    ...f.revised.data,
    revision: 3,
    version_id: "11111111-1111-4111-8111-111111111111",
  };
  const transport = setup(
    () => {
      if (!rejected) {
        rejected = true;
        return failure("REVISION_CONFLICT", 412);
      }
      return response(third, 200, `"task-template:${third.id}:3"`);
    },
    (path) =>
      path === f.revised.request.path
        ? new Promise<Response>((resolve) => {
            release = resolve;
          })
        : undefined,
  );
  render(<TaskTemplateEditor {...props} />);
  await useRevisedName(user);
  await user.click(
    screen.getByRole("button", { name: "保存任务模板，不运行" }),
  );
  await screen.findByText(/保存基准已变化/);
  expect(screen.getByLabelText("模板名称")).toHaveValue(
    f.revised.data.configuration.name,
  );
  expect(
    screen.getByRole("button", { name: "保存任务模板，不运行" }),
  ).toBeDisabled();
  await user.click(
    screen.getByRole("button", { name: "读取并采用当前修订，保留输入" }),
  );
  expect(
    screen.getByRole("button", { name: "保存任务模板，不运行" }),
  ).toBeDisabled();
  await act(async () => {
    release?.(reply(f.revised));
  });
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "保存任务模板，不运行" }),
    ).toBeEnabled(),
  );
  await user.click(
    screen.getByRole("button", { name: "保存任务模板，不运行" }),
  );
  await waitFor(() => expect(props.onSaved).toHaveBeenCalledWith(third));
  expect(new Headers(transport.sent[1].headers).get("If-Match")).toBe(
    f.revised.headers.etag,
  );
});

it("does not send when durable exact-command storage fails and leaves the visible input intact", async () => {
  const user = userEvent.setup(),
    props = editorProps(),
    transport = setup();
  const setItem = Storage.prototype.setItem;
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (
    this: Storage,
    key,
    value,
  ) {
    if (key.includes("task-package-template"))
      throw new DOMException("full", "QuotaExceededError");
    setItem.call(this, key, value);
  });
  render(<TaskTemplateEditor {...props} />);
  await user.click(
    screen.getByRole("button", { name: "保存任务模板，不运行" }),
  );
  await screen.findByText(/无法可靠保存整包任务的原请求/);
  expect(transport.sent).toHaveLength(0);
  expect(screen.getByLabelText("任务说明")).toHaveValue(initial.instructions);
  expect(props.onSaved).not.toHaveBeenCalled();
});

it("does not accept a late create ACK after unmount or recreate a removed recovery record", async () => {
  const user = userEvent.setup(),
    props = editorProps();
  let release: ((value: Response) => void) | undefined;
  const transport = setup(
    () =>
      new Promise<Response>((resolve) => {
        release = resolve;
      }),
  );
  const ui = render(<TaskTemplateEditor {...props} />);
  await user.click(
    screen.getByRole("button", { name: "保存任务模板，不运行" }),
  );
  await waitFor(() => expect(transport.sent).toHaveLength(1));
  const raw = sessionStorage.getItem(recoveryKey("template"));
  expect(raw).not.toBeNull();
  ui.unmount();
  sessionStorage.removeItem(recoveryKey("template"));
  await act(async () => {
    release?.(reply(f.created));
    await new Promise((resolve) => setTimeout(resolve, 5));
  });
  expect(props.onSaved).not.toHaveBeenCalled();
  expect(sessionStorage.getItem(recoveryKey("template"))).toBeNull();
});

it("blocks exact execution when its capability is unavailable or method changed", async () => {
  const props = runProps(),
    transport = setup();
  const unavailable = structuredClone(f.kinds.data);
  unavailable.items[0].exact_package_manual!.available = false;
  const ui = render(
    <ExactPackageTaskRunControl {...props} kinds={unavailable} />,
  );
  await screen.findByText(/整包手动执行能力：当前不可用/);
  expect(
    screen.getByRole("button", { name: "手动运行这份整包输入" }),
  ).toBeDisabled();
  const changed = structuredClone(f.kinds.data);
  changed.items[0].exact_package_manual!.method_digest = "a".repeat(64);
  ui.rerender(<ExactPackageTaskRunControl {...props} kinds={changed} />);
  await screen.findByText(/模板中的核查方法与当前服务不一致/);
  expect(
    screen.getByRole("button", { name: "手动运行这份整包输入" }),
  ).toBeDisabled();
  expect(transport.sent).toHaveLength(0);
});

it("recovers the original manual run ACK after remount despite a newer template, without rerun or a new key", async () => {
  const user = userEvent.setup(),
    props = runProps();
  let good = false;
  const transport = setup(() => {
    if (!good) throw new TypeError("lost");
    return reply(f.replay);
  });
  const ui = render(<ExactPackageTaskRunControl {...props} />);
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "手动运行这份整包输入" }),
    ).toBeEnabled(),
  );
  await user.click(
    screen.getByRole("button", { name: "手动运行这份整包输入" }),
  );
  await screen.findByRole("button", { name: "恢复原整包运行受理结果" });
  ui.unmount();
  good = true;
  render(
    <ExactPackageTaskRunControl
      {...props}
      template={f.revised.data}
      etag={f.revised.headers.etag}
    />,
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "恢复原整包运行受理结果" }),
    ).toBeEnabled(),
  );
  await user.click(
    screen.getByRole("button", { name: "恢复原整包运行受理结果" }),
  );
  await waitFor(() =>
    expect(props.onRun).toHaveBeenCalledWith(f.queued.data.id),
  );
  expect(screen.getByText(/原命令受理回执：等待处理/)).toBeVisible();
  expect(transport.sent).toHaveLength(2);
  expect(JSON.parse(String(transport.sent[0].body))).toEqual({ rerun: false });
  expect(transport.sent[1].body).toBe(transport.sent[0].body);
  expect(new Headers(transport.sent[1].headers).get("If-Match")).toBe(
    createdTag,
  );
  expect(new Headers(transport.sent[1].headers).get("Idempotency-Key")).toBe(
    new Headers(transport.sent[0].headers).get("Idempotency-Key"),
  );
});

it("does not clear a mismatched native run acknowledgement", async () => {
  const user = userEvent.setup(),
    props = runProps();
  setup(() =>
    response(
      { ...f.queued.data, bid_id: "11111111-1111-4111-8111-111111111111" },
      202,
    ),
  );
  render(<ExactPackageTaskRunControl {...props} />);
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "手动运行这份整包输入" }),
    ).toBeEnabled(),
  );
  await user.click(
    screen.getByRole("button", { name: "手动运行这份整包输入" }),
  );
  await screen.findByRole("button", { name: "恢复原整包运行受理结果" });
  expect(props.onRun).not.toHaveBeenCalled();
  expect(sessionStorage.getItem(recoveryKey("run"))).not.toBeNull();
  expect(
    screen.getByRole("button", { name: "手动运行这份整包输入" }),
  ).toBeDisabled();
});

it("shows completed exact-run scope and opens its verified native details without selecting a body or latest run", async () => {
  const user = userEvent.setup(),
    transport = setup();
  render(
    <TaskRunCard bidId={bidId} memberId={memberId} id={f.completed.data.id} />,
  );
  await screen.findByText(/服务器当前任务状态：已记录处理结果/);
  expect(screen.getByText(/整体覆盖仍为部分/)).toBeVisible();
  expect(screen.queryByText("核对本次冻结受检稿原件")).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /api/ })).not.toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: "查看任务绑定的原生整包核查" }),
  );
  await screen.findByRole("heading", { name: "本次整包范围核查" });
  expect(transport.paths).toContain(f.native.request.path);
  expect(transport.paths).toContain(f.frozen.request.path);
  expect(transport.paths).toContain(f.prepared.request.path);
  expect(transport.sent).toHaveLength(0);
});

it("rejects a forged native path without exposing a single-body or alternate run fallback", async () => {
  const bad = structuredClone(f.completed.data);
  (bad.frozen_manifest.package_review as { run_ref: string }).run_ref =
    "https://example.invalid/another-run";
  const transport = setup(undefined, (path) =>
    path === f.completed.request.path ? response(bad) : undefined,
  );
  render(<TaskRunCard bidId={bidId} memberId={memberId} id={bad.id} />);
  await screen.findByText(/整包任务的身份、原输入、摘要或回执边界不符/);
  expect(
    screen.queryByRole("button", { name: "查看任务绑定的原生整包核查" }),
  ).not.toBeInTheDocument();
  expect(screen.queryByText("核对本次冻结受检稿原件")).not.toBeInTheDocument();
  expect(
    transport.paths.some(
      (path) => path.includes("/operations/") || path.includes("/review-runs/"),
    ),
  ).toBe(false);
});

it("keeps a collapsed exact editor mounted so its real dirty state continues to interlock run and pause", async () => {
  const user = userEvent.setup();
  setup();
  render(
    <TaskTemplateCard
      bidId={bidId}
      memberId={memberId}
      id={f.created.data.id}
      kinds={f.kinds.data}
      onChanged={vi.fn()}
      onRun={vi.fn()}
    />,
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "手动运行这份整包输入" }),
    ).toBeEnabled(),
  );
  await user.click(screen.getByRole("button", { name: "修改并保存新版本" }));
  await user.type(screen.getByLabelText("任务说明"), "未发送文字");
  expect(
    screen.getByRole("button", { name: "手动运行这份整包输入" }),
  ).toBeDisabled();
  expect(screen.getByRole("button", { name: "暂停后续触发" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "收起表单，保留输入" }));
  expect(
    screen.getByRole("button", { name: "手动运行这份整包输入" }),
  ).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "修改并保存新版本" }));
  expect(screen.getByLabelText("任务说明")).toHaveValue(
    initial.instructions + "未发送文字",
  );
  await user.click(
    screen.getByRole("button", { name: "放弃未发送的文字修改" }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "手动运行这份整包输入" }),
    ).toBeEnabled(),
  );
});

it("preserves the mounted exact edit session and marks its old basis when a server event advances the template version", async () => {
  const user = userEvent.setup();
  let advanced = false;
  setup(undefined, (path) =>
    path === f.revised.request.path
      ? reply(advanced ? f.revised : f.created)
      : undefined,
  );
  render(
    <PackageScopeGuardProvider>
      <GuardState />
      <TaskTemplateCard
        bidId={bidId}
        memberId={memberId}
        id={f.created.data.id}
        kinds={f.kinds.data}
        onChanged={vi.fn()}
        onRun={vi.fn()}
      />
    </PackageScopeGuardProvider>,
  );
  await user.click(
    await screen.findByRole("button", { name: "修改并保存新版本" }),
  );
  const originalEditor = screen.getByLabelText("任务说明");
  await user.type(originalEditor, "我的未提交修改");
  advanced = true;
  act(() => window.dispatchEvent(new Event("server-snapshot-change")));
  await screen.findByText(/服务器模板修订已更新/);
  expect(screen.getByLabelText("任务说明")).toBe(originalEditor);
  expect(originalEditor).toHaveValue(initial.instructions + "我的未提交修改");
  expect(screen.getByLabelText("真实任务导航状态")).toHaveTextContent(
    '"dirty":true',
  );
  expect(
    screen.getByRole("button", { name: "保存任务模板，不运行" }),
  ).toBeDisabled();
  await user.click(
    screen.getByRole("button", { name: "读取并采用当前修订，保留输入" }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "保存任务模板，不运行" }),
    ).toBeEnabled(),
  );
  expect(originalEditor).toHaveValue(initial.instructions + "我的未提交修改");
});

it("keeps a native detail mounted but read-only while a newer task read is pending or fails validation", async () => {
  const user = userEvent.setup();
  let wait = false,
    release: ((value: Response) => void) | undefined;
  const transport = setup(undefined, (path) =>
    path === f.completed.request.path && wait
      ? new Promise<Response>((resolve) => {
          release = resolve;
        })
      : undefined,
  );
  render(
    <TaskRunCard bidId={bidId} memberId={memberId} id={f.completed.data.id} />,
  );
  await user.click(
    await screen.findByRole("button", { name: "查看任务绑定的原生整包核查" }),
  );
  const heading = await screen.findByRole("heading", {
    name: "本次整包范围核查",
  });
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "刷新本次核查状态" }),
    ).toBeEnabled(),
  );
  wait = true;
  act(() => window.dispatchEvent(new Event("server-snapshot-change")));
  await screen.findByText(/最新读取正在核验或未通过核验/);
  expect(
    screen.getByRole("button", { name: "查看任务绑定的原生整包核查" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "刷新本次核查状态" }),
  ).toBeDisabled();
  expect(screen.getByText(/上次已核验任务状态/)).toBeVisible();
  const bad = structuredClone(f.completed.data);
  bad.frozen_manifest.input_digest = "a".repeat(64);
  await act(async () => {
    release?.(response(bad));
  });
  await screen.findByText(/整包任务的身份、原输入、摘要或回执边界不符/);
  expect(screen.getByRole("heading", { name: "本次整包范围核查" })).toBe(
    heading,
  );
  expect(
    screen.getByRole("button", { name: "刷新本次核查状态" }),
  ).toBeDisabled();
  wait = false;
  act(() => window.dispatchEvent(new Event("server-snapshot-change")));
  await screen.findByText(/服务器当前任务状态：已记录处理结果/);
  expect(screen.getByRole("heading", { name: "本次整包范围核查" })).toBe(
    heading,
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "刷新本次核查状态" }),
    ).toBeEnabled(),
  );
  expect(
    transport.paths.filter((path) => path === f.native.request.path).length,
  ).toBeLessThanOrEqual(3);
  expect(transport.sent).toHaveLength(0);
});

it("does not substitute an unrelated fixed-version description for the validated package run", async () => {
  const user = userEvent.setup();
  const wrong = structuredClone(f.createdVersion.data);
  wrong.config.definition.name = "不属于本次冻结输入的说明";
  setup(undefined, (path) =>
    path === f.createdVersion.request.path ? response(wrong) : undefined,
  );
  render(
    <TaskRunCard bidId={bidId} memberId={memberId} id={f.completed.data.id} />,
  );
  await screen.findByText(/固定模板版本与这次任务的冻结说明不一致/);
  expect(
    screen.queryByText("不属于本次冻结输入的说明"),
  ).not.toBeInTheDocument();
  await user.click(screen.getByText("核对完整来源身份与摘要"));
  expect(screen.getByText(selection.inventory_id)).toBeVisible();
});

it("isolates a late template ACK when the member changes without reusing the old mounted editor", async () => {
  const user = userEvent.setup(),
    props = editorProps();
  let release: ((value: Response) => void) | undefined;
  const transport = setup(
    () =>
      new Promise<Response>((resolve) => {
        release = resolve;
      }),
  );
  const ui = render(<TaskTemplateEditor {...props} />);
  await user.click(
    screen.getByRole("button", { name: "保存任务模板，不运行" }),
  );
  await waitFor(() => expect(transport.sent).toHaveLength(1));
  const newMember = "11111111-1111-4111-8111-111111111111";
  ui.rerender(
    <TaskTemplateEditor
      {...props}
      memberId={newMember}
      initialConfiguration={{ ...initial, name: "新成员自己的表单" }}
    />,
  );
  await act(async () => {
    release?.(reply(f.created));
    await new Promise((resolve) => setTimeout(resolve, 5));
  });
  expect(props.onSaved).not.toHaveBeenCalled();
  expect(screen.getByLabelText("模板名称")).toHaveValue("新成员自己的表单");
  expect(sessionStorage.getItem(recoveryKey("template"))).not.toBeNull();
});
