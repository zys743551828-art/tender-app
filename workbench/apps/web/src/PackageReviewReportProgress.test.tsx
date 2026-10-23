import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Progress from "./PackageReviewReportProgress";
import { packageReviewReportFixture } from "../qa-previews/frozen-inputs/packageReviewReport";
import { changeId as id } from "../qa-previews/frozen-inputs/factChange";
let f: Awaited<ReturnType<typeof packageReviewReportFixture>>;
const fetchMock = vi.fn(),
  json = (value: unknown) =>
    new Response(JSON.stringify(value), {
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
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
function Wrapper() {
  const [report, setReport] = useState(f.report);
  return (
    <Progress
      {...f.f.props}
      run={f.f.completed}
      report={report}
      onChange={setReport}
    />
  );
}
it("replaces an old queued ACK with the fetched completed metadata and never regresses that terminal result", async () => {
  fetchMock
    .mockResolvedValueOnce(json(f.completed))
    .mockResolvedValueOnce(json(f.report));
  render(<Wrapper />);
  await screen.findByRole("button", { name: "下载本份 Word 报告" });
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "刷新报告生成状态" }),
    ).toBeEnabled(),
  );
  await userEvent.click(
    screen.getByRole("button", { name: "刷新报告生成状态" }),
  );
  await screen.findByText(/报告已确认的终态或生成文件发生变化/);
  expect(screen.getByText("报告副本已生成")).toBeInTheDocument();
});
it("rejects an operation substitution even when it has the requested report id", async () => {
  fetchMock.mockResolvedValueOnce(
    json({
      ...f.completed,
      operation: { ...f.completed.operation, id: id(900) },
    }),
  );
  render(<Wrapper />);
  await screen.findByText(/报告的不可变身份发生变化/);
  expect(
    screen.queryByRole("button", { name: "下载本份 Word 报告" }),
  ).not.toBeInTheDocument();
});
it("accepts reordered JSON fields without changing the immutable generated artifact", async () => {
  const reverse = Object.fromEntries(
    Object.entries(f.completed.result!).reverse(),
  );
  fetchMock
    .mockResolvedValueOnce(json(f.completed))
    .mockResolvedValueOnce(json({ ...f.completed, result: reverse }));
  render(<Wrapper />);
  await screen.findByRole("button", { name: "下载本份 Word 报告" });
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "刷新报告生成状态" }),
    ).toBeEnabled(),
  );
  await userEvent.click(
    screen.getByRole("button", { name: "刷新报告生成状态" }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "刷新报告生成状态" }),
    ).toBeEnabled(),
  );
  expect(screen.queryByText(/终态或生成文件发生变化/)).not.toBeInTheDocument();
});
