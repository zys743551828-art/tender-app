import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { workContextFixture } from "../qa-previews/frozen-inputs/workContext";
import { packageReviewOriginalFetch } from "../qa-previews/frozen-inputs/packageReviewComparison";
import { WorkContextReviewDetails } from "./WorkContextReviewDetails";

const fetchMock = vi.fn();
let f: Awaited<ReturnType<typeof workContextFixture>>;
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  f = await workContextFixture();
});
afterEach(() => vi.unstubAllGlobals());
function selection() {
  if (f.context.selection.kind !== "package_review_run")
    throw new Error("fixture");
  return f.context.selection;
}
it("reads the original exact matrix without a command, cancellation or opinion form", async () => {
  fetchMock.mockImplementation(
    async (url: string) =>
      new Response(
        JSON.stringify(
          packageReviewOriginalFetch(f, url.replace(/^\/api\/v1/, "")),
        ),
        { headers: { "Content-Type": "application/json" } },
      ),
  );
  render(
    <WorkContextReviewDetails
      selection={selection()}
      memberId={f.props.scope.memberId}
      onClose={vi.fn()}
    />,
  );
  // The three exact reads and their asynchronous SHA-256 checks must finish
  // before the original matrix can be shown, including in a cold test worker.
  await screen.findByRole(
    "region",
    { name: "整包范围核查结果" },
    { timeout: 5000 },
  );
  expect(
    screen.queryByText("正在核对原冻结输入、执行准备与核查结果…"),
  ).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(3);
  expect(
    fetchMock.mock.calls.every(
      ([, options]) => !options?.method || options.method === "GET",
    ),
  ).toBe(true);
  expect(
    screen.queryByRole("button", { name: /取消|确认原|驳回/ }),
  ).not.toBeInTheDocument();
});
it("does not backfill a result missing from the fixed historical selection", async () => {
  fetchMock.mockImplementation(
    async (url: string) =>
      new Response(
        JSON.stringify(
          packageReviewOriginalFetch(f, url.replace(/^\/api\/v1/, "")),
        ),
        { headers: { "Content-Type": "application/json" } },
      ),
  );
  render(
    <WorkContextReviewDetails
      selection={{ ...selection(), result_digest: null }}
      memberId={f.props.scope.memberId}
      onClose={vi.fn()}
    />,
  );
  await screen.findByText(/此核查的结果或固定输入与原选择不同/);
  expect(
    screen.queryByRole("region", { name: "整包范围核查结果" }),
  ).not.toBeInTheDocument();
});
it("discards late original responses after the selection closes", async () => {
  const replies: (() => void)[] = [];
  fetchMock.mockImplementation(
    (url: string) =>
      new Promise<Response>((resolve) =>
        replies.push(() =>
          resolve(
            new Response(
              JSON.stringify(
                packageReviewOriginalFetch(f, url.replace(/^\/api\/v1/, "")),
              ),
              { headers: { "Content-Type": "application/json" } },
            ),
          ),
        ),
      ),
  );
  const view = render(
    <WorkContextReviewDetails
      selection={selection()}
      memberId={f.props.scope.memberId}
      onClose={vi.fn()}
    />,
  );
  expect(replies).toHaveLength(3);
  view.unmount();
  await act(async () => replies.forEach((reply) => reply()));
  expect(
    screen.queryByRole("region", { name: "整包范围核查结果" }),
  ).not.toBeInTheDocument();
});
