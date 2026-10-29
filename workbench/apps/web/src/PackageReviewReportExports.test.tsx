import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Exports from "./PackageReviewReportExports";
import { packageReviewReportFixture } from "../qa-previews/frozen-inputs/packageReviewReport";
import { packageReviewReportPath } from "./packageReviewReportProtocol";
import { loadPackageReviewReportRecord } from "./packageReviewReportRecovery";

const fetchMock = vi.fn();
let f: Awaited<ReturnType<typeof packageReviewReportFixture>>;
let post: (options: RequestInit) => Promise<Response>;
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
  sessionStorage.clear();
  fetchMock.mockReset();
  f = await packageReviewReportFixture();
  post = async () => json(f.report, 202);
  fetchMock.mockImplementation(async (url: string, options: RequestInit) => {
    const path = url.replace(/^\/api\/v1/, ""),
      base = packageReviewReportPath(f.f.props, f.f.completed);
    if (path === base && options.method === "POST") return post(options);
    if (path === base.replace(/\/report-exports$/, "/report-context"))
      return json(f.context);
    if (path === `${base}/${f.report.id}`) return json(f.completed);
    if (path === `${base}?limit=10`) return json(f.page());
    throw new Error(`unexpected synthetic report ${path}`);
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
const show = () => render(<Exports {...f.f.props} run={f.f.completed} />);
const writes = () =>
  fetchMock.mock.calls.filter(([, options]) => options?.method === "POST");
const saved = () =>
  loadPackageReviewReportRecord(f.f.props.scope.memberId, f.f.completed);
async function start() {
  await userEvent.click(
    screen.getByRole("button", { name: "读取报告生成依据" }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "申请生成 Word 报告" }),
    ).toBeEnabled(),
  );
  await userEvent.click(
    screen.getByRole("button", { name: "申请生成 Word 报告" }),
  );
}
it("requires explicit context and application, saves before POST, and reads a terminal detail after an old queued acknowledgement", async () => {
  show();
  expect(fetchMock).not.toHaveBeenCalled();
  expect(
    screen.getByRole("button", { name: "申请生成 Word 报告" }),
  ).toBeDisabled();
  post = async (options) => {
    expect(saved().pending!.body).toEqual(f.body);
    expect(saved().pending!.key).toBe(
      new Headers(options.headers).get("Idempotency-Key"),
    );
    return json(f.report, 202);
  };
  await start();
  await screen.findByRole("button", { name: "下载本份 Word 报告" });
  expect(writes()).toHaveLength(1);
  expect(saved().pending).toBeNull();
  expect(saved().lastId).toBe(f.report.id);
  expect(
    screen.getByText("当前未配置 PDF 转换能力，可生成 Word 报告。"),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("option", { name: "PDF 文档（.pdf）" }),
  ).not.toBeInTheDocument();
});
it("recovers a lost ACK using the exact old body and key without automatically reading current context", async () => {
  post = async () => {
    throw new TypeError("synthetic lost report ACK");
  };
  const view = show();
  await start();
  await screen.findByText("NETWORK_ERROR");
  const original = writes()[0][1] as RequestInit;
  view.unmount();
  show();
  const calls = fetchMock.mock.calls.length;
  post = async () => json(f.report, 202);
  await userEvent.click(screen.getByRole("button", { name: "恢复原报告申请" }));
  await screen.findByRole("button", { name: "下载本份 Word 报告" });
  expect(writes()).toHaveLength(2);
  expect(writes()[1][1].body).toBe(original.body);
  expect(new Headers(writes()[1][1].headers).get("Idempotency-Key")).toBe(
    new Headers(original.headers).get("Idempotency-Key"),
  );
  expect(
    fetchMock.mock.calls
      .slice(calls)
      .some(([url]) => String(url).endsWith("/report-context")),
  ).toBe(false);
});
it("clears an explicit context rejection and requires rereading and another explicit application", async () => {
  post = async () =>
    json(
      {
        code: "PACKAGE_REVIEW_REPORT_CONTEXT_CHANGED",
        message: "合成人工意见已变化",
      },
      409,
    );
  show();
  await start();
  await screen.findByText("合成人工意见已变化");
  expect(saved().pending).toBeNull();
  expect(
    screen.getByRole("button", { name: "申请生成 Word 报告" }),
  ).toBeDisabled();
  expect(writes()).toHaveLength(1);
  await userEvent.click(
    screen.getByRole("button", { name: "读取报告生成依据" }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "申请生成 Word 报告" }),
    ).toBeEnabled(),
  );
  expect(writes()).toHaveLength(1);
});
it("retains a mismatched report acknowledgement for exact recovery", async () => {
  post = async () => json({ ...f.report, context_digest: "0".repeat(64) }, 202);
  show();
  await start();
  await screen.findByText(/报告副本的原运行、结果、格式或任务身份无法核验/);
  expect(saved().pending!.body).toEqual(f.body);
  expect(
    screen.queryByRole("region", { name: "本份报告生成状态" }),
  ).not.toBeInTheDocument();
});
it("does not send a new application when the browser cannot persist it", async () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new DOMException("synthetic quota", "QuotaExceededError");
  });
  show();
  await start();
  await screen.findByText(/浏览器未能更新报告恢复记录/);
  expect(writes()).toHaveLength(0);
});
it("shows the accepted server receipt but keeps original recovery if storage fails after ACK", async () => {
  const actual = Storage.prototype.setItem;
  let writesToStorage = 0;
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (
    this: Storage,
    key,
    value,
  ) {
    if (++writesToStorage === 2)
      throw new DOMException("synthetic after ACK", "QuotaExceededError");
    actual.call(this, key, value);
  });
  show();
  await start();
  await screen.findByRole("button", { name: "下载本份 Word 报告" });
  expect(
    screen.getByText("报告申请回执已确认，实际生成状态以重读记录为准。"),
  ).toBeInTheDocument();
  expect(saved().pending).not.toBeNull();
  expect(
    screen.getByRole("button", { name: "恢复原报告申请" }),
  ).toBeInTheDocument();
});
it("keeps a late unmounted application recoverable and does not auto replay on a return", async () => {
  let resolve!: (value: Response) => void;
  post = () =>
    new Promise<Response>((done) => {
      resolve = done;
    });
  const view = show();
  await start();
  view.unmount();
  await act(async () => {
    resolve(json(f.report, 202));
  });
  show();
  expect(saved().pending).not.toBeNull();
  expect(writes()).toHaveLength(1);
  expect(
    screen.queryByRole("region", { name: "本份报告生成状态" }),
  ).not.toBeInTheDocument();
});
it("reads a stored report from history without context load or a new request", async () => {
  show();
  await userEvent.click(
    screen.getByText("本轮报告副本历史", { selector: "summary" }),
  );
  await userEvent.click(screen.getByRole("button", { name: "读取报告历史" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "查看此份报告" }),
  );
  await screen.findByRole("button", { name: "下载本份 Word 报告" });
  expect(writes()).toHaveLength(0);
  expect(
    fetchMock.mock.calls.some(([url]) =>
      String(url).endsWith("/report-context"),
    ),
  ).toBe(false);
});
