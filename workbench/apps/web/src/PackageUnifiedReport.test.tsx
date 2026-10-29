import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api, objectFetch } from "./api";
import { PackageUnifiedReport } from "./PackageUnifiedReport";
vi.mock("./api", async (load) => ({
  ...(await load<typeof import("./api")>()),
  api: vi.fn(),
  objectFetch: vi.fn(),
}));
const p = { bidId: "bid", scopeId: "scope", commandId: "cmd" };
const id = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa";
function result(extra: object = {}) {
  return {
    data: {
      schema: "package-unified-review-report/1",
      snapshot_id: "a".repeat(64),
      bid_id: "bid",
      scope_id: "scope",
      command_id: "cmd",
      review_id: id,
      sections: [
        ["一、废标／否决与强制性要求", ["部分覆盖"]],
        ["二、分类问题清单", []],
        ["三、可能的失分点", []],
        ["四、报价", ["未知"]],
      ],
      matrix: [],
      documents: [],
      ...extra,
    },
    etag: null,
  };
}
function start() {
  fireEvent.change(screen.getByLabelText("完成评审编号"), {
    target: { value: id },
  });
  fireEvent.click(screen.getByText("复验统一报告"));
}
beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(objectFetch).mockReset();
});
it("renders all four parts from one returned snapshot without invented numeric score", async () => {
  vi.mocked(api).mockResolvedValue(result());
  const refresh = vi.fn();
  render(<PackageUnifiedReport {...p} onRefresh={refresh} />);
  start();
  expect(refresh).toHaveBeenCalledOnce();
  await screen.findByText("四、报价");
  expect(screen.getByText("三、可能的失分点")).toBeTruthy();
  expect(screen.queryByText(/已校准/)).toBeNull();
});
it.each([
  { scope_id: "other" },
  { review_id: "other" },
  { snapshot_id: "wrong" },
  { sections: [null] },
  { matrix: [null] },
])("rejects foreign/malformed snapshots", async (extra) => {
  vi.mocked(api).mockResolvedValue(result(extra));
  render(<PackageUnifiedReport {...p} />);
  start();
  await screen.findByText(/统一快照身份/);
  expect(screen.queryByText("四、报价")).toBeNull();
});
it("discards a late report after changing scope", async () => {
  let finish!: (r: ReturnType<typeof result>) => void;
  vi.mocked(api).mockReturnValue(new Promise((resolve) => (finish = resolve)));
  const view = render(<PackageUnifiedReport {...p} />);
  start();
  view.rerender(<PackageUnifiedReport {...p} scopeId="next" />);
  await act(async () => finish(result()));
  expect(screen.queryByText("四、报价")).toBeNull();
});
it("does not download failed or stale Word output", async () => {
  vi.mocked(objectFetch).mockResolvedValue(
    new Response("denied", { status: 409 }),
  );
  render(<PackageUnifiedReport {...p} />);
  fireEvent.change(screen.getByLabelText("完成评审编号"), {
    target: { value: id },
  });
  fireEvent.click(screen.getByText("下载统一 Word"));
  await screen.findByText(/未下载旧文件/);
});
