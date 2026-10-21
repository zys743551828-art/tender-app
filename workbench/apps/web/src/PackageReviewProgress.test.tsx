import { useState } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { PackageReviewRunView } from "./contracts";
import Progress from "./PackageReviewProgress";
import {
  packageReviewFixture,
  packageReviewOperation,
} from "../qa-previews/frozen-inputs/packageReview";
import { changeId as id } from "../qa-previews/frozen-inputs/factChange";

let fixture: Awaited<ReturnType<typeof packageReviewFixture>>;
const fetchMock = vi.fn();
const json = (value: unknown) =>
  new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json", ETag: '"operation-1"' },
  });
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  vi.stubGlobal("fetch", fetchMock);
  sessionStorage.clear();
  fetchMock.mockReset();
  fixture = await packageReviewFixture();
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
function Harness({
  initial = fixture.run,
}: {
  initial?: PackageReviewRunView;
}) {
  const [run, setRun] = useState(initial);
  return <Progress {...fixture.props} run={run} onChange={setRun} />;
}
it("polls accepted work and stops fetching after the validated terminal result", async () => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  fetchMock
    .mockResolvedValueOnce(json(fixture.run))
    .mockResolvedValueOnce(json(fixture.completed));
  render(<Harness />);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(3000);
  });
  await screen.findByRole("region", { name: "整包范围核查结果" });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(9000);
  });
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(screen.getByText("核查执行已结束")).toBeInTheDocument();
});
it("shows an explicit retrieval gap when the operation succeeds without a result", async () => {
  const withoutResult = { ...fixture.completed, result: null };
  fetchMock
    .mockResolvedValueOnce(json(withoutResult))
    .mockResolvedValueOnce(json(fixture.completed));
  render(<Harness initial={withoutResult} />);
  await screen.findByText(/范围核查结果尚未取回/);
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "刷新本次核查状态" }),
    ).toBeEnabled(),
  );
  expect(
    screen.queryByRole("region", { name: "整包范围核查结果" }),
  ).not.toBeInTheDocument();
  await userEvent.click(
    screen.getByRole("button", { name: "刷新本次核查状态" }),
  );
  await screen.findByRole("region", { name: "整包范围核查结果" });
});
it("does not adopt a changed operation identity even when the run and prepared ids match", async () => {
  fetchMock.mockResolvedValueOnce(
    json({
      ...fixture.run,
      operation: { ...fixture.run.operation, id: id(999) },
    }),
  );
  render(<Harness />);
  await screen.findByText(/不可变身份发生变化/);
  expect(screen.getByText("已受理，等待核查")).toBeInTheDocument();
  expect(
    screen.queryByRole("region", { name: "整包范围核查结果" }),
  ).not.toBeInTheDocument();
});
it("a forced read after cancellation supersedes a pending poll, whose late reply cannot revive the old state", async () => {
  let resolve!: (response: Response) => void;
  let reads = 0;
  const cancelled = {
    ...fixture.run,
    operation: {
      ...fixture.run.operation,
      state: "cancelled" as const,
      finished_at: "2026-10-21T08:00:30.000000Z",
    },
  };
  fetchMock.mockImplementation(async (url: string, options: RequestInit) => {
    if (url.includes("/operations/"))
      return json({
        ...packageReviewOperation(fixture.run),
        state: options.method === "POST" ? "cancel_requested" : "queued",
      });
    reads++;
    return reads === 1
      ? new Promise<Response>((done) => {
          resolve = done;
        })
      : json(cancelled);
  });
  render(<Harness />);
  await userEvent.click(screen.getByRole("button", { name: "取消本次核查" }));
  await userEvent.type(
    screen.getByLabelText("取消本次核查的理由"),
    "合成：停止本次核查",
  );
  await userEvent.click(screen.getByRole("button", { name: "确认请求取消" }));
  await screen.findByText("本次核查已取消");
  await act(async () => {
    resolve(json(fixture.run));
  });
  expect(screen.getByText("本次核查已取消")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "刷新本次核查状态" }),
  ).toBeEnabled();
  expect(reads).toBe(2);
});
