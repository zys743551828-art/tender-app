import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { UploadBatchDiscovery } from "./UploadBatchDiscovery";
import type { UploadBatchView } from "./contracts";
// Explicit contract fixture for collection mechanisms; actual HTTP/browser evidence is separate.
vi.mock("./contracts", async (original) => {
  const actual = await original<typeof import("./contracts")>();
  return {
    ...actual,
    implementedOperations: [
      ...actual.implementedOperations,
      "GET /api/v1/bids/{bid_id}/upload-batches",
    ],
  };
});
const first: UploadBatchView = {
  id: "batch-first",
  bid_id: "bid",
  revision: 2,
  state: "open",
  uploads: [],
};
const second: UploadBatchView = {
  id: "batch-second",
  bid_id: "bid",
  revision: 1,
  state: "open",
  uploads: [],
};
function json(value: unknown) {
  return new Response(JSON.stringify(value));
}
it("新浏览器只凭项目读取批次，后续页保留状态与签名游标，选回真实批次不新建上传", async () => {
  const user = userEvent.setup();
  const selected = vi.fn();
  const writes = vi.fn();
  const paths: string[] = [];
  localStorage.clear();
  sessionStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, options?: RequestInit) => {
      paths.push(url);
      if (options?.method === "POST") writes();
      return url.includes("cursor=")
        ? json({ items: [second], has_more: false, next_cursor: null })
        : json({
            items: [first],
            has_more: true,
            next_cursor: "opaque:scope-bound",
          });
    }),
  );
  render(
    <UploadBatchDiscovery
      bidId="bid"
      currentId={null}
      disabled={false}
      hasUnsentFiles={false}
      onSelect={selected}
    />,
  );
  await user.click(
    screen.getByRole("button", { name: "查找本项目已保存的上传批次" }),
  );
  await user.click(await screen.findByRole("button", { name: "加载更多批次" }));
  await waitFor(() =>
    expect(
      screen.getAllByRole("button", { name: "切换到此批次继续核对" }),
    ).toHaveLength(2),
  );
  await user.click(
    screen.getAllByRole("button", { name: "切换到此批次继续核对" })[1],
  );
  expect(selected).toHaveBeenCalledWith(second);
  expect(paths).toContain(
    "/api/v1/bids/bid/upload-batches?state=open&limit=20&cursor=opaque%3Ascope-bound",
  );
  expect(writes).not.toHaveBeenCalled();
});
it("待上传本地选择不因切批丢失，其他项目的批次不提供接续按钮", async () => {
  const user = userEvent.setup();
  const selected = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      json({
        items: [first, { ...second, bid_id: "other-bid" }],
        has_more: false,
        next_cursor: null,
      }),
    ),
  );
  render(
    <UploadBatchDiscovery
      bidId="bid"
      currentId={null}
      disabled={false}
      hasUnsentFiles={true}
      onSelect={selected}
    />,
  );
  await user.click(
    screen.getByRole("button", { name: "查找本项目已保存的上传批次" }),
  );
  expect(
    await screen.findByRole("button", { name: "切换到此批次继续核对" }),
  ).toBeDisabled();
  expect(screen.getByText(/批次项目身份不一致/)).toBeVisible();
  expect(selected).not.toHaveBeenCalled();
});
