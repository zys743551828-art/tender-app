import { StrictMode } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Workspace from "./PackageFactChangeWorkspace";
import {
  changeId as id,
  changeReply,
  factChangeFixture,
} from "../qa-previews/frozen-inputs/factChange";
import {
  factChangeStorageKey,
  loadFactChangeRecord,
  storeFactChangeRecord,
} from "./factChangeRecovery";
import type { PendingFactChange } from "./factChangeProtocol";
let fixture: Awaited<ReturnType<typeof factChangeFixture>>;
const fetchMock = vi.fn();
const response = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  sessionStorage.clear();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  fixture = await factChangeFixture();
  fetchMock.mockImplementation(async (url: string) => {
    const path = url.split("?")[0];
    if (path.endsWith("/fact-context")) return response(fixture.page);
    if (path.endsWith(`/facts/${id(51)}`)) return response(fixture.detail);
    if (path.endsWith(`/revisions/${id(4)}`)) return response(fixture.target);
    if (path.endsWith(`/revisions/${id(31)}`))
      return response(fixture.authority);
    if (path.endsWith(`/revisions/${id(4)}/evidence`))
      return response(fixture.directory);
    if (path.endsWith(`/evidence/${id(60)}`)) return response(fixture.evidence);
    if (path.endsWith(`/documents/${id(40)}`))
      return response(fixture.document);
    throw new Error(`Unexpected synthetic route: ${path}`);
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
function show(disabled = false, onCommitted = vi.fn()) {
  return render(
    <StrictMode>
      <Workspace
        scope={fixture.scope}
        frozen={fixture.frozen}
        disabled={disabled}
        onCommitted={onCommitted}
      />
    </StrictMode>,
  );
}
async function list() {
  await userEvent.click(
    screen.getByText("项目事实（可选）", { selector: "summary" }),
  );
  await userEvent.click(
    screen.getByRole("button", { name: "读取当前项目事实" }),
  );
  await screen.findByText("合同工期", { selector: "strong" });
}
async function edit() {
  await list();
  await userEvent.click(screen.getByRole("button", { name: "查看并修改" }));
  await screen.findByLabelText("事实主体");
}
async function confirm() {
  await userEvent.type(screen.getByLabelText("确认理由"), "核对原页后确认");
  await userEvent.click(
    screen.getByLabelText("我已核对原页并确认以上事实内容"),
  );
  await userEvent.click(screen.getByRole("button", { name: "确认并保存事实" }));
}
function interceptPost(run: (p: PendingFactChange) => Promise<Response>) {
  const read = fetchMock.getMockImplementation()!;
  fetchMock.mockImplementation(async (url: string, options?: RequestInit) => {
    if (options?.method !== "POST") return read(url, options);
    const saved = loadFactChangeRecord(fixture.keyScope);
    expect(saved.pending).not.toBeNull();
    expect(saved.pending?.key).toBe(
      new Headers(options.headers).get("Idempotency-Key"),
    );
    expect(saved.pending?.body).toEqual(JSON.parse(String(options.body)));
    return run(saved.pending!);
  });
}
it("performs no automatic reads or mutations on mount and requires explicit listing", async () => {
  show();
  expect(fetchMock).not.toHaveBeenCalled();
  await list();
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock.mock.calls[0][0]).toContain(
    `frozen_digest=${fixture.frozen.digest}`,
  );
});
it("saves the exact pending body before confirming and invalidates parent observations only after verified ACK", async () => {
  const committed = vi.fn();
  interceptPost(async (p) => response(await changeReply(fixture, p), 201));
  show(false, committed);
  await edit();
  await confirm();
  await screen.findByText("事实已确认保存，请重新复核当前条件并准备输入。");
  expect(committed).toHaveBeenCalledTimes(1);
  expect(loadFactChangeRecord(fixture.keyScope).pending).toBeNull();
  expect(loadFactChangeRecord(fixture.keyScope).lastId).toBeTruthy();
});
it.each([
  ["no", false],
  ["empty", null],
] as const)("keeps %s as a scalar when confirming", async (mode, value) => {
  interceptPost(async (p) => {
    expect(p.kind).toBe("confirm");
    if (p.kind === "confirm") expect(p.body.fact.value).toBe(value);
    return response(await changeReply(fixture, p), 201);
  });
  show();
  await edit();
  await userEvent.selectOptions(screen.getByLabelText("内容类型"), mode);
  await confirm();
  await screen.findByText("事实已确认保存，请重新复核当前条件并准备输入。");
});
it("a field edit cancels prior human confirmation", async () => {
  show();
  await edit();
  await userEvent.type(screen.getByLabelText("确认理由"), "已核对");
  await userEvent.click(
    screen.getByLabelText("我已核对原页并确认以上事实内容"),
  );
  expect(screen.getByRole("button", { name: "确认并保存事实" })).toBeEnabled();
  await userEvent.type(screen.getByLabelText("事实内容"), "1");
  expect(screen.getByRole("button", { name: "确认并保存事实" })).toBeDisabled();
});
it("a lost ACK survives refresh and retries the same body and key even when editing is disabled", async () => {
  interceptPost(async () => {
    throw new TypeError("synthetic disconnected response");
  });
  const view = show();
  await edit();
  await confirm();
  await screen.findByRole("button", { name: "恢复原事实操作" });
  const original = loadFactChangeRecord(fixture.keyScope).pending;
  expect(original).not.toBeNull();
  view.unmount();
  interceptPost(async (p) => {
    expect(p).toEqual(original);
    return response(await changeReply(fixture, p), 201);
  });
  const before = fetchMock.mock.calls.length;
  show(true);
  expect(fetchMock.mock.calls.length).toBe(before);
  await userEvent.click(screen.getByRole("button", { name: "恢复原事实操作" }));
  await screen.findByText("事实已确认保存，请重新复核当前条件并准备输入。");
});
it("rejects a well-hashed ACK for changed content and retains the pending operation", async () => {
  interceptPost(async (p) => {
    const wrong = structuredClone(p);
    if (wrong.kind === "confirm") wrong.body.fact.value = "999";
    return response(await changeReply(fixture, wrong), 201);
  });
  show();
  await edit();
  await confirm();
  await screen.findByText(/事实回执的身份、请求摘要或资格边界不符/);
  expect(loadFactChangeRecord(fixture.keyScope).pending).not.toBeNull();
});
it("keeps malformed recovery bytes and sends nothing", async () => {
  sessionStorage.setItem(factChangeStorageKey(fixture.keyScope), "{broken");
  show();
  await userEvent.click(
    screen.getByText("项目事实（可选）", { selector: "summary" }),
  );
  await screen.findByText(/事实操作恢复记录损坏/);
  expect(fetchMock).not.toHaveBeenCalled();
  expect(sessionStorage.getItem(factChangeStorageKey(fixture.keyScope))).toBe(
    "{broken",
  );
});
it("does not coerce unsupported historical JSON into an editable string and supports explicit withdrawal", async () => {
  fixture.detail.editability = "unsupported_or_oversized";
  fixture.detail.editable_fact = null;
  interceptPost(async (p) => {
    expect(p.kind).toBe("withdraw");
    return response(await changeReply(fixture, p), 201);
  });
  show();
  await list();
  await userEvent.click(screen.getByRole("button", { name: "查看并修改" }));
  await screen.findByText(/此事实的类型或长度暂不支持直接编辑/);
  expect(screen.queryByLabelText("事实内容")).toBeNull();
  await userEvent.type(screen.getByLabelText("撤回理由"), "原内容已不适用");
  await userEvent.click(screen.getByRole("button", { name: "撤回此事实" }));
  await screen.findByText("事实已撤回，历史记录保留。");
});
it("a fact outside the selected frozen parse cannot be reconfirmed", async () => {
  fixture.detail.evidence_references[0].frozen_parse_member = false;
  show();
  await edit();
  await confirm();
  expect(screen.getByRole("button", { name: "确认并保存事实" })).toBeDisabled();
  expect(
    fetchMock.mock.calls.some(([, options]) => options?.method === "POST"),
  ).toBe(false);
});
it("reads the historical package and actual quote with filename before adopting a new citation", async () => {
  show();
  await list();
  await userEvent.click(screen.getByRole("button", { name: "新增项目事实" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "浏览本方标书冻结原页" }),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "读取并采用第 1 条原句" }),
  );
  await screen.findByText(fixture.evidence.quote);
  expect(
    screen.getByText("合成标书-技术正文.pdf · 第 2 页"),
  ).toBeInTheDocument();
  expect(
    fetchMock.mock.calls.some(([url]) => String(url).includes("latest")),
  ).toBe(false);
  expect(
    fetchMock.mock.calls.some(([, options]) => options?.method === "POST"),
  ).toBe(false);
});
it.each(["parse", "unpublished", "document"])(
  "rejects a mismatched %s citation without adopting it",
  async (kind) => {
    if (kind === "parse") fixture.evidence.parse_run_id = id(90);
    if (kind === "unpublished") fixture.evidence.source_status = "retracted";
    if (kind === "document") fixture.document.sha256 = "0".repeat(64);
    show();
    await list();
    await userEvent.click(screen.getByRole("button", { name: "新增项目事实" }));
    await userEvent.click(
      await screen.findByRole("button", { name: "浏览本方标书冻结原页" }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "读取并采用第 1 条原句" }),
    );
    await waitFor(() =>
      expect(screen.getAllByRole("alert").length).toBeGreaterThan(0),
    );
    expect(screen.queryByText(fixture.evidence.quote)).toBeNull();
    expect(
      screen.getByText("从冻结原页选择依据，再核对事实内容。"),
    ).toBeInTheDocument();
  },
);
it("a late ACK after unmount does not clear the old recovery record", async () => {
  let resolve!: (value: Response) => void;
  interceptPost(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  const view = show();
  await edit();
  await confirm();
  const saved = loadFactChangeRecord(fixture.keyScope);
  view.unmount();
  await act(async () =>
    resolve(response(await changeReply(fixture, saved.pending!), 201)),
  );
  expect(loadFactChangeRecord(fixture.keyScope).pending).toEqual(saved.pending);
});
it("reading history never clears an uncertain original operation", async () => {
  const pending: PendingFactChange = {
    kind: "withdraw",
    key: id(80),
    body: {
      frozen_digest: fixture.frozen.digest,
      expected_head: fixture.page.head,
      fact_id: id(51),
      reason: "合成撤回",
    },
  };
  storeFactChangeRecord({
    version: 1,
    scope: fixture.keyScope,
    pending,
    lastId: id(80),
  });
  fetchMock.mockResolvedValue(response(await changeReply(fixture, pending)));
  show();
  await userEvent.click(
    screen.getByText("读取已有事实回执", { selector: "summary" }),
  );
  await userEvent.click(screen.getByRole("button", { name: "读取事实回执" }));
  await screen.findByText("历史事实回执，仅供核对。");
  expect(loadFactChangeRecord(fixture.keyScope).pending).toEqual(pending);
});
