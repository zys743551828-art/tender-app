import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import History from "./PackageReviewDecisionHistory";
import { packageReviewFixture } from "../qa-previews/frozen-inputs/packageReview";
import {
  packageReviewDecisionBody,
  packageReviewDecisionPage,
  packageReviewDecisionReply,
} from "../qa-previews/frozen-inputs/packageReviewDecision";
import { packageReviewDecisionsPath } from "./packageReviewDecisionProtocol";
let f: Awaited<ReturnType<typeof packageReviewFixture>>;
const json = (data: unknown) =>
  new Response(JSON.stringify(data), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  f = await packageReviewFixture();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
async function open() {
  await userEvent.click(screen.getByText("此项人工记录与原引用历史"));
  await userEvent.click(
    screen.getByRole("button", { name: "读取此项人工历史" }),
  );
}
it("reads only the selected row's immutable history and original quotes after explicit action", async () => {
  const body = await packageReviewDecisionBody(f),
    head = await packageReviewDecisionReply(f, body),
    page = await packageReviewDecisionPage(f, [head]),
    p = { ...f.props, run: f.completed },
    row = f.completed.result!.manifest.matrix[0];
  const fetcher = vi.fn(async () => json(page));
  vi.stubGlobal("fetch", fetcher);
  render(<History p={p} row={row} />);
  expect(fetcher).not.toHaveBeenCalled();
  await open();
  expect(await screen.findByText(body.reason)).toBeInTheDocument();
  expect(screen.getByText(body.selected_quotes[0].quote)).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledWith(
    `/api/v1${packageReviewDecisionsPath(p, row.requirement_id)}?limit=20`,
    expect.objectContaining({ method: "GET" }),
  );
  expect(
    screen.queryByRole("button", { name: "确认此项判断" }),
  ).not.toBeInTheDocument();
});
it("rejects history from another matrix row before showing its reason or quotes", async () => {
  const body = await packageReviewDecisionBody(f, 1),
    head = await packageReviewDecisionReply(f, body, 1),
    page = await packageReviewDecisionPage(f, [head], 1);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => json(page)),
  );
  render(
    <History
      p={{ ...f.props, run: f.completed }}
      row={f.completed.result!.manifest.matrix[0]}
    />,
  );
  await open();
  expect(
    await screen.findByText(/人工记录与原核查结果、条款、引用或版本不符/),
  ).toBeInTheDocument();
  expect(screen.queryByText(body.reason)).not.toBeInTheDocument();
});
it("refuses a repeated cursor or overlapping history page instead of counting old records twice", async () => {
  const body = await packageReviewDecisionBody(f),
    first = await packageReviewDecisionReply(f, body),
    second = await packageReviewDecisionReply(
      f,
      await packageReviewDecisionBody(f, 0, first, "needs_review"),
      0,
      2,
    ),
    page = await packageReviewDecisionPage(f, [second, first]);
  page.has_more = true;
  page.next_cursor = "synthetic-cursor";
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => json(page)),
  );
  render(
    <History
      p={{ ...f.props, run: f.completed }}
      row={f.completed.result!.manifest.matrix[0]}
    />,
  );
  await open();
  await userEvent.click(
    await screen.findByRole("button", { name: "读取更早的人工历史" }),
  );
  expect(
    await screen.findByText(/人工历史游标重复或记录重叠/),
  ).toBeInTheDocument();
  expect(screen.getByText("第 2 版 · 需要复查")).toBeInTheDocument();
});
