import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Original from "./PackageReviewOriginalRunDetails";
import {
  packageReviewFixture,
  packageReviewPage,
} from "../qa-previews/frozen-inputs/packageReview";
import { packageReviewOriginalFetch } from "../qa-previews/frozen-inputs/packageReviewComparison";
import { packageReviewHistoricalSummary } from "./packageReviewHistoricalRun";
const fetchMock = vi.fn();
let f: Awaited<ReturnType<typeof packageReviewFixture>>;
const json = (v: unknown) =>
  new Response(JSON.stringify(v), {
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
  f = await packageReviewFixture();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
function props() {
  return {
    memberId: f.props.scope.memberId,
    reference: packageReviewHistoricalSummary(
      packageReviewPage(f, [f.completed]).items[0],
      f.props.scope.bidId,
    )!,
    label: "合成原核查",
    onClose: vi.fn(),
  };
}
it("rejects a different result digest even when the returned run identity is otherwise valid", async () => {
  fetchMock.mockImplementation(async (url: string) =>
    json(packageReviewOriginalFetch(f, url.replace(/^\/api\/v1/, ""))),
  );
  const p = props();
  p.reference.result!.digest = "0".repeat(64);
  render(<Original {...p} />);
  await screen.findByText(/原核查身份或结果摘要与所选记录不符/);
  expect(
    screen.queryByRole("region", { name: "整包范围核查结果" }),
  ).not.toBeInTheDocument();
});
it("does not display an old original after the selected historical reference changes", async () => {
  const replies: (() => void)[] = [];
  fetchMock.mockImplementation(
    (url: string) =>
      new Promise<Response>((resolve) =>
        replies.push(() =>
          resolve(
            json(packageReviewOriginalFetch(f, url.replace(/^\/api\/v1/, ""))),
          ),
        ),
      ),
  );
  const p = props(),
    view = render(<Original {...p} />);
  expect(replies).toHaveLength(3);
  view.unmount();
  await act(async () => {
    replies.forEach((reply) => reply());
  });
  expect(
    screen.queryByRole("region", { name: "整包范围核查结果" }),
  ).not.toBeInTheDocument();
});
it("rejects a requested row digest that does not match the original matrix even when the whole report is valid", async () => {
  fetchMock.mockImplementation(async (url: string) =>
    json(packageReviewOriginalFetch(f, url.replace(/^\/api\/v1/, ""))),
  );
  render(
    <Original
      {...props()}
      requirement={{
        id: f.completed.result!.manifest.matrix[0].requirement_id,
        rowDigest: "0".repeat(64),
      }}
    />,
  );
  await screen.findByText(/所选原要求或机器行摘要与对比不符/);
  expect(
    screen.queryByRole("region", { name: "整包范围核查结果" }),
  ).not.toBeInTheDocument();
});
