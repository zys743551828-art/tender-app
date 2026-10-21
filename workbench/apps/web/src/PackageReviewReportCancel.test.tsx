import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Cancel from "./PackageReviewReportCancel";
import {
  packageReportOperation,
  packageReviewReportFixture,
} from "../qa-previews/frozen-inputs/packageReviewReport";
import { loadPackageReviewReportCancel } from "./packageReviewReportRecovery";
const fetchMock = vi.fn(),
  reload = vi.fn();
let f: Awaited<ReturnType<typeof packageReviewReportFixture>>;
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: {
      "Content-Type": "application/json",
      ETag: '"synthetic-report-v1"',
    },
  });
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  vi.stubGlobal("fetch", fetchMock);
  sessionStorage.clear();
  fetchMock.mockReset();
  reload.mockReset().mockResolvedValue(undefined);
  f = await packageReviewReportFixture();
  fetchMock.mockImplementation(async (_url, options: RequestInit) =>
    json({
      ...packageReportOperation(f.report),
      state: options.method === "POST" ? "cancel_requested" : "queued",
    }),
  );
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
const show = () =>
  render(
    <Cancel
      memberId={f.f.props.scope.memberId}
      run={f.f.completed}
      report={f.report}
      onReload={reload}
    />,
  );
const saved = () =>
  loadPackageReviewReportCancel(
    f.f.props.scope.memberId,
    f.f.completed,
    f.report,
  );
async function submit() {
  await userEvent.click(
    screen.getByRole("button", { name: "取消此份报告生成" }),
  );
  await userEvent.type(
    screen.getByLabelText("取消报告生成的理由"),
    "合成更新人工意见后重新生成",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "确认取消此份报告" }),
  );
}
it("targets only the report operation input and stores its exact cancellation before POST", async () => {
  fetchMock.mockImplementation(async (url: string, options: RequestInit) => {
    expect(url.startsWith(`/api/v1/operations/${f.report.operation.id}`)).toBe(
      true,
    );
    if (options.method === "POST") {
      expect(saved()!.body).toEqual(JSON.parse(String(options.body)));
      expect(saved()!.etag).toBe(new Headers(options.headers).get("If-Match"));
    }
    return json({
      ...packageReportOperation(f.report),
      state: options.method === "POST" ? "cancel_requested" : "queued",
    });
  });
  show();
  await submit();
  await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
  expect(saved()).toBeNull();
  expect(screen.getByText(/最终生成状态以重读报告为准/)).toBeInTheDocument();
});
it("recovers a lost cancellation with the original key, body and ETag without a fresh operation GET", async () => {
  fetchMock
    .mockResolvedValueOnce(json(packageReportOperation(f.report)))
    .mockRejectedValueOnce(new TypeError("synthetic lost cancel ACK"));
  const view = show();
  await submit();
  await screen.findByText("NETWORK_ERROR");
  const original = fetchMock.mock.calls[1][1] as RequestInit;
  view.unmount();
  show();
  await userEvent.click(
    screen.getByRole("button", { name: "恢复原报告取消请求" }),
  );
  await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
  const next = fetchMock.mock.calls[2][1] as RequestInit;
  expect(fetchMock).toHaveBeenCalledTimes(3);
  expect(next.body).toBe(original.body);
  expect(new Headers(next.headers).get("Idempotency-Key")).toBe(
    new Headers(original.headers).get("Idempotency-Key"),
  );
  expect(new Headers(next.headers).get("If-Match")).toBe(
    new Headers(original.headers).get("If-Match"),
  );
});
it("refuses the original review operation digest at the report-cancel endpoint", async () => {
  fetchMock.mockResolvedValueOnce(
    json({
      ...packageReportOperation(f.report),
      input_digest: f.f.completed.input_digest,
    }),
  );
  show();
  await submit();
  await screen.findByText(/未请求取消其他任务/);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(saved()).toBeNull();
});
it("leaves a wrong cancellation receipt pending and never claims that the report is cancelled", async () => {
  fetchMock
    .mockResolvedValueOnce(json(packageReportOperation(f.report)))
    .mockResolvedValueOnce(
      json({
        ...packageReportOperation(f.report),
        kind: "package-scope-review",
      }),
    );
  show();
  await submit();
  await screen.findByText(/取消回执与此份报告任务不符/);
  expect(saved()).not.toBeNull();
  expect(reload).not.toHaveBeenCalled();
});
it("reads an already completed report without sending cancellation", async () => {
  fetchMock.mockResolvedValueOnce(json(packageReportOperation(f.completed)));
  show();
  await submit();
  await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(saved()).toBeNull();
});
