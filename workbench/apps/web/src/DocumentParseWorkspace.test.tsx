import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as service from "./api";
import Workspace from "./DocumentParseWorkspace";
import type { DocumentParseView, StartDocumentParse } from "./contracts";
import {
  documentParseContextPath,
  documentParsePath,
} from "./documentParseProtocol";
import {
  documentParseStorageKey,
  loadDocumentParseRecord,
  storeDocumentParseRecord,
} from "./documentParseRecovery";
import {
  documentParseTestFixture,
  documentParseTestId as id,
} from "./documentParseTestFixture";

const fetchMock = vi.fn();
let f: Awaited<ReturnType<typeof documentParseTestFixture>>,
  post: (options: RequestInit) => Promise<Response>,
  detail: DocumentParseView,
  history: ReturnType<
    Awaited<ReturnType<typeof documentParseTestFixture>>["page"]
  >;
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  vi.stubGlobal("fetch", fetchMock);
  // A synthetic service advertises these new routes; production uses generated capabilities.
  vi.spyOn(service, "supportsApi").mockReturnValue(true);
  sessionStorage.clear();
  localStorage.clear();
  fetchMock.mockReset();
  f = await documentParseTestFixture();
  detail = f.completed;
  history = f.page();
  post = async (options) =>
    json(
      await f.ack(JSON.parse(options.body as string) as StartDocumentParse),
      202,
    );
  fetchMock.mockImplementation(async (url: string, options: RequestInit) => {
    const path = url.replace(/^\/api\/v1/, ""),
      base = documentParsePath(f.scope);
    if (path === base && options.method === "POST") return post(options);
    if (path === documentParseContextPath(f.scope)) return json(f.wrapper);
    if (path === `${base}?limit=10`) return json(history);
    if (path === `${base}/${detail.id}`) return json(detail);
    throw new Error(`unexpected synthetic parse request ${path}`);
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
const writes = () =>
  fetchMock.mock.calls.filter(([, options]) => options?.method === "POST");
const saved = () => loadDocumentParseRecord(f.scope);
const show = (
  props: {
    disabled?: boolean;
    onParsed?: (value: DocumentParseView) => void;
  } = {},
) => render(<Workspace {...f.scope} {...props} />);
async function expand() {
  await userEvent.click(
    screen.getByRole("button", { name: "解析原件与查看历史" }),
  );
}
async function prepare() {
  await expand();
  await userEvent.click(
    screen.getByRole("button", { name: "读取当前解析条件" }),
  );
  await screen.findByText("合成解析样例.pdf");
  await userEvent.type(
    screen.getByLabelText("解析理由（必填，最多 1,000 字）"),
    f.pending.body.reason,
  );
}
async function start() {
  await prepare();
  await userEvent.click(
    screen.getByRole("button", { name: "明确申请解析此文件版本" }),
  );
}
it("does zero network work until opened and explicitly read, then persists before POST and displays partial coverage", async () => {
  const parsed = vi.fn();
  show({ onParsed: parsed });
  expect(fetchMock).not.toHaveBeenCalled();
  await expand();
  expect(fetchMock).not.toHaveBeenCalled();
  await userEvent.click(
    screen.getByRole("button", { name: "读取当前解析条件" }),
  );
  await screen.findByText("合成解析样例.pdf");
  expect(writes()).toHaveLength(0);
  expect(
    screen.getByRole("button", { name: "明确申请解析此文件版本" }),
  ).toBeDisabled();
  await userEvent.type(
    screen.getByLabelText("解析理由（必填，最多 1,000 字）"),
    f.pending.body.reason,
  );
  post = async (options) => {
    expect(saved().pending!.key).toBe(
      new Headers(options.headers).get("Idempotency-Key"),
    );
    expect(saved().pending!.body).toEqual(JSON.parse(options.body as string));
    return json(await f.ack(JSON.parse(options.body as string)), 202);
  };
  await userEvent.click(
    screen.getByRole("button", { name: "明确申请解析此文件版本" }),
  );
  await screen.findByText("本次解析仅形成部分覆盖，仍有内容需要补充核对。");
  expect(writes()).toHaveLength(1);
  expect(saved().pending).toBeNull();
  expect(saved().lastId).toBe(f.request.id);
  expect(
    JSON.parse(localStorage.getItem(`tender:operations:${f.scope.bidId}`)!),
  ).toContain(f.request.operation.id);
  await waitFor(() => expect(parsed).toHaveBeenCalledTimes(1));
  expect(parsed).toHaveBeenLastCalledWith(f.completed);
  await userEvent.click(
    screen.getByRole("button", { name: "刷新本次解析状态" }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "刷新本次解析状态" }),
    ).toBeEnabled(),
  );
  expect(parsed).toHaveBeenCalledTimes(1);
  expect(
    fetchMock.mock.calls.every(
      ([url, options]) =>
        options.method === "GET" || String(url).endsWith("/parse-requests"),
    ),
  ).toBe(true);
});
it("recovers a lost ACK using the original key/body after the project closes, with no new context lookup", async () => {
  post = async () => {
    throw new TypeError("synthetic lost ACK");
  };
  const mounted = show();
  await start();
  await screen.findByText("NETWORK_ERROR");
  const original = writes()[0][1] as RequestInit;
  mounted.unmount();
  show({ disabled: true });
  const readsBefore = fetchMock.mock.calls.length;
  expect(screen.getByRole("button", { name: "恢复原解析申请" })).toBeEnabled();
  post = async (options) =>
    json(await f.ack(JSON.parse(options.body as string)), 202);
  await userEvent.click(screen.getByRole("button", { name: "恢复原解析申请" }));
  await screen.findByText("本次解析仅形成部分覆盖，仍有内容需要补充核对。");
  expect(writes()).toHaveLength(2);
  expect(writes()[1][1].body).toBe(original.body);
  expect(new Headers(writes()[1][1].headers).get("Idempotency-Key")).toBe(
    new Headers(original.headers).get("Idempotency-Key"),
  );
  expect(
    fetchMock.mock.calls
      .slice(readsBefore)
      .some(([url]) => String(url).endsWith("/parse-context")),
  ).toBe(false);
});
it.each([
  "COMMAND_INCOMPLETE",
  "IDEMPOTENCY_CONFLICT",
  "DOCUMENT_PARSE_SCOPE_MISMATCH",
])("retains the original pending request on %s", async (code) => {
  post = async () => json({ code, message: `合成${code}` }, 409);
  show();
  await start();
  await screen.findByText(code);
  expect(saved().pending!.body).toEqual(f.pending.body);
  expect(
    screen.getByRole("button", { name: "明确申请解析此文件版本" }),
  ).toBeDisabled();
  expect(screen.getByRole("button", { name: "恢复原解析申请" })).toBeEnabled();
});
it("clears an explicit context rejection and requires another deliberate context read", async () => {
  post = async () =>
    json(
      { code: "DOCUMENT_PARSE_CONTEXT_CHANGED", message: "合成解析条件已变化" },
      409,
    );
  show();
  await start();
  await screen.findByText("DOCUMENT_PARSE_CONTEXT_CHANGED");
  expect(saved().pending).toBeNull();
  expect(
    screen.getByRole("button", { name: "明确申请解析此文件版本" }),
  ).toBeDisabled();
  expect(screen.getByLabelText("解析理由（必填，最多 1,000 字）")).toHaveValue(
    f.pending.body.reason,
  );
});
it("keeps a malformed ACK for recovery and never displays it as a valid parse", async () => {
  post = async (options) =>
    json(
      {
        ...(await f.ack(JSON.parse(options.body as string))),
        actor_id: id(99),
      },
      202,
    );
  show();
  await start();
  await screen.findByText(/解析记录的项目、原件、方法或回执身份无法核验/);
  expect(saved().pending).not.toBeNull();
  expect(
    screen.queryByRole("region", { name: "本次解析状态" }),
  ).not.toBeInTheDocument();
});
it("reports cross-member reuse with the original author without rejecting legitimate shared work", async () => {
  detail = { ...f.completed, actor_id: id(77), reason: "其他成员先前申请" };
  post = async (options) =>
    json(
      await f.ack(
        JSON.parse(options.body as string),
        { ...f.request, actor_id: detail.actor_id, reason: detail.reason },
        true,
      ),
      202,
    );
  show();
  await start();
  await screen.findByText(/申请回执已确认，复用相同解析条件下的已有记录/);
  await screen.findByText("本次解析仅形成部分覆盖，仍有内容需要补充核对。");
  expect(saved().pending).toBeNull();
});
it("does not send when the original request cannot be durably saved", async () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new DOMException("synthetic quota", "QuotaExceededError");
  });
  show();
  await start();
  await screen.findByText(/浏览器未能更新解析恢复记录/);
  expect(writes()).toHaveLength(0);
});
it("preserves pending on post-ACK storage failure and does not regress terminal GET state when replaying the queued ACK", async () => {
  const actual = Storage.prototype.setItem;
  let count = 0;
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (
    this: Storage,
    key,
    value,
  ) {
    if (key === documentParseStorageKey(f.scope) && ++count === 2)
      throw new DOMException("synthetic after ACK", "QuotaExceededError");
    actual.call(this, key, value);
  });
  show();
  await start();
  await screen.findByText("本次解析仅形成部分覆盖，仍有内容需要补充核对。");
  await screen.findByText(/浏览器未能更新解析恢复记录/);
  expect(saved().pending).not.toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "恢复原解析申请" }));
  await waitFor(() => expect(saved().pending).toBeNull());
  expect(
    screen.getByText("本次解析仅形成部分覆盖，仍有内容需要补充核对。"),
  ).toBeInTheDocument();
});
it("keeps an unmounted late ACK recoverable and never posts automatically after returning", async () => {
  let resolve!: (response: Response) => void;
  post = () =>
    new Promise((done) => {
      resolve = done;
    });
  const mounted = show();
  await start();
  mounted.unmount();
  await act(async () => {
    resolve(json(await f.ack(), 202));
  });
  show();
  expect(saved().pending).not.toBeNull();
  expect(writes()).toHaveLength(1);
  expect(screen.getByRole("button", { name: "恢复原解析申请" })).toBeEnabled();
  expect(
    screen.queryByRole("region", { name: "本次解析状态" }),
  ).not.toBeInTheDocument();
});
it("keeps verified parse recovery independent of the optional task-center cache", async () => {
  const actual = Storage.prototype.setItem;
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (
    this: Storage,
    key,
    value,
  ) {
    if (key.startsWith("tender:operations:"))
      throw new DOMException(
        "synthetic task cache unavailable",
        "QuotaExceededError",
      );
    actual.call(this, key, value);
  });
  show();
  await start();
  await screen.findByText("本次解析仅形成部分覆盖，仍有内容需要补充核对。");
  expect(saved().pending).toBeNull();
  expect(saved().lastId).toBe(f.request.id);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
it("reads historical partial or failed coverage without requesting current context or creating work", async () => {
  detail = {
    ...f.completed,
    result: { ...f.completed.result!, coverage: "failed", page_count: 0 },
  };
  history = f.page([detail]);
  show({ disabled: true });
  await expand();
  await userEvent.click(screen.getByRole("button", { name: "读取解析历史" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "查看这次解析" }),
  );
  await screen.findByText("解析运行已结束，但未形成可用覆盖，请核对缺口。");
  expect(writes()).toHaveLength(0);
  expect(
    fetchMock.mock.calls.some(([url]) =>
      String(url).endsWith("/parse-context"),
    ),
  ).toBe(false);
});
it("does not replace a terminal result with a regressing refresh response", async () => {
  show();
  await start();
  await screen.findByText("本次解析仅形成部分覆盖，仍有内容需要补充核对。");
  detail = f.request;
  await userEvent.click(
    screen.getByRole("button", { name: "刷新本次解析状态" }),
  );
  await screen.findByText(/已确认终态或结果发生变化/);
  expect(
    screen.getByText("本次解析仅形成部分覆盖，仍有内容需要补充核对。"),
  ).toBeInTheDocument();
});
it("keeps history usable when recovery is corrupted and blocks creating new work", async () => {
  sessionStorage.setItem(documentParseStorageKey(f.scope), "not-json");
  show();
  await userEvent.click(screen.getByRole("button", { name: "读取解析历史" }));
  expect(
    await screen.findByRole("button", { name: "查看这次解析" }),
  ).toBeEnabled();
  expect(
    screen.getByRole("button", { name: "明确申请解析此文件版本" }),
  ).toBeDisabled();
});
it("isolates a different selected document from a late original request", async () => {
  let resolve!: (response: Response) => void;
  post = () =>
    new Promise((done) => {
      resolve = done;
    });
  const mounted = show();
  await start();
  mounted.rerender(<Workspace {...f.scope} documentId={id(99)} />);
  await act(async () => {
    resolve(json(await f.ack(), 202));
  });
  expect(saved().pending).not.toBeNull();
  expect(
    screen.queryByRole("region", { name: "本次解析状态" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "解析原件与查看历史" }),
  ).toHaveAttribute("aria-expanded", "false");
});
it("reads pages without accumulating prior page rows or repeating them", async () => {
  const second = { ...f.completed, id: id(40), reason: "第二页的合成申请" };
  history = { ...f.page(), has_more: true, next_cursor: "synthetic-cursor" };
  const original = fetchMock.getMockImplementation()!;
  fetchMock.mockImplementation((url: string, options: RequestInit) =>
    String(url).includes("cursor=synthetic-cursor")
      ? Promise.resolve(json(f.page([second])))
      : original(url, options),
  );
  show();
  await expand();
  await userEvent.click(screen.getByRole("button", { name: "读取解析历史" }));
  await screen.findByRole("button", { name: "查看这次解析" });
  await userEvent.click(screen.getByRole("button", { name: "下一页解析历史" }));
  const region = screen.getByRole("region", { name: "解析历史" });
  await within(region).findByText(second.reason);
  expect(
    within(region).queryByText(f.pending.body.reason),
  ).not.toBeInTheDocument();
});
it("does not auto-load a saved last id or auto-recover an existing pending request", () => {
  storeDocumentParseRecord({
    version: 1,
    scope: f.scope,
    pending: f.pending,
    lastId: f.completed.id,
  });
  show();
  expect(fetchMock).not.toHaveBeenCalled();
  expect(
    screen.getByRole("button", { name: "继续查看上次解析" }),
  ).toBeEnabled();
});
