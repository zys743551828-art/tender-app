import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Cancel from "./PackageReviewCancel";
import {
  packageReviewFixture,
  packageReviewOperation,
} from "../qa-previews/frozen-inputs/packageReview";
import { changeId as id } from "../qa-previews/frozen-inputs/factChange";
import { loadPackageReviewCancel } from "./packageReviewRecovery";

let fixture: Awaited<ReturnType<typeof packageReviewFixture>>;
const fetchMock = vi.fn(),
  reload = vi.fn();
const json = (value: unknown, status = 200, etag = '"revision-1"') =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json", ETag: etag },
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
  fixture = await packageReviewFixture();
  fetchMock.mockImplementation(async (_url, options: RequestInit) =>
    json({
      ...packageReviewOperation(fixture.run),
      state: options.method === "POST" ? "cancel_requested" : "queued",
    }),
  );
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
const show = () =>
  render(<Cancel {...fixture.props} run={fixture.run} onReload={reload} />);
async function submit() {
  await userEvent.click(screen.getByRole("button", { name: "取消本次核查" }));
  await userEvent.type(
    screen.getByLabelText("取消本次核查的理由"),
    "合成测试：准备补充资料后再核查",
  );
  await userEvent.click(screen.getByRole("button", { name: "确认请求取消" }));
}
it("reads the exact operation and If-Match, persists before POST and reloads the same run after a verified acknowledgement", async () => {
  fetchMock.mockImplementation(async (url: string, options: RequestInit) => {
    expect(
      url.startsWith(`/api/v1/operations/${fixture.run.operation.id}`),
    ).toBe(true);
    if (options.method === "POST") {
      const pending = loadPackageReviewCancel(fixture.props, fixture.run)!;
      expect(pending.body).toEqual(JSON.parse(String(options.body)));
      expect(pending.etag).toBe(new Headers(options.headers).get("If-Match"));
      expect(pending.key).toBe(
        new Headers(options.headers).get("Idempotency-Key"),
      );
      return json({
        ...packageReviewOperation(fixture.run),
        state: "cancel_requested",
      });
    }
    return json(packageReviewOperation(fixture.run));
  });
  show();
  expect(fetchMock).not.toHaveBeenCalled();
  await submit();
  await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(loadPackageReviewCancel(fixture.props, fixture.run)).toBeNull();
  expect(screen.getByText(/最终状态以重新读取/)).toBeInTheDocument();
});
it("retains unknown cancellation across refresh and retries the original reason, key and ETag without a new GET", async () => {
  fetchMock
    .mockImplementationOnce(async () =>
      json(packageReviewOperation(fixture.run)),
    )
    .mockRejectedValueOnce(new TypeError("lost cancellation acknowledgement"));
  const view = show();
  await submit();
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "恢复原取消请求" }),
    ).toBeEnabled(),
  );
  const original = fetchMock.mock.calls[1][1] as RequestInit;
  view.unmount();
  show();
  expect(fetchMock).toHaveBeenCalledTimes(2);
  await userEvent.click(screen.getByRole("button", { name: "恢复原取消请求" }));
  await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
  const retry = fetchMock.mock.calls[2][1] as RequestInit;
  expect(retry.body).toBe(original.body);
  expect(new Headers(retry.headers).get("If-Match")).toBe(
    new Headers(original.headers).get("If-Match"),
  );
  expect(new Headers(retry.headers).get("Idempotency-Key")).toBe(
    new Headers(original.headers).get("Idempotency-Key"),
  );
});
it("does not cancel an operation with another bid or input digest", async () => {
  fetchMock.mockResolvedValueOnce(
    json({ ...packageReviewOperation(fixture.run), bid_id: id(990) }),
  );
  show();
  await submit();
  await screen.findByText(/未请求取消其他任务/);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(loadPackageReviewCancel(fixture.props, fixture.run)).toBeNull();
  expect(screen.getByLabelText("取消本次核查的理由")).toHaveValue(
    "合成测试：准备补充资料后再核查",
  );
});
it("keeps a mismatched cancellation acknowledgement pending and never declares the other operation cancelled", async () => {
  fetchMock
    .mockImplementationOnce(async () =>
      json(packageReviewOperation(fixture.run)),
    )
    .mockResolvedValueOnce(
      json({
        ...packageReviewOperation(fixture.run),
        id: id(991),
        state: "cancelled",
      }),
    );
  show();
  await submit();
  await screen.findByText(/取消回执与本次核查任务不符/);
  expect(loadPackageReviewCancel(fixture.props, fixture.run)).toBeTruthy();
  expect(reload).not.toHaveBeenCalled();
});
it("clears a replay-prioritized revision rejection but preserves the reason for an explicit retry", async () => {
  fetchMock
    .mockImplementationOnce(async () =>
      json(packageReviewOperation(fixture.run)),
    )
    .mockResolvedValueOnce(
      json({ code: "REVISION_CONFLICT", message: "合成任务状态已变化" }, 412),
    );
  show();
  await submit();
  await screen.findByText("合成任务状态已变化");
  expect(loadPackageReviewCancel(fixture.props, fixture.run)).toBeNull();
  expect(screen.getByRole("button", { name: "确认请求取消" })).toBeEnabled();
  expect(reload).not.toHaveBeenCalled();
});
it("does not submit when the fresh operation read is already terminal", async () => {
  fetchMock.mockResolvedValueOnce(
    json({ ...packageReviewOperation(fixture.run), state: "succeeded" }),
  );
  show();
  await submit();
  await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(
    screen.getByText(/任务已经结束，未再发送取消请求/),
  ).toBeInTheDocument();
});
