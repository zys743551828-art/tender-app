import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Workspace from "./PackageReviewComparisonWorkspace";
import {
  packageReviewComparisonFixture,
  packageReviewOriginalFetch,
} from "../qa-previews/frozen-inputs/packageReviewComparison";
import { changeId as id } from "../qa-previews/frozen-inputs/factChange";
import { packageReviewComparisonPath } from "./packageReviewComparisonProtocol";

const fetchMock = vi.fn();
let f: Awaited<ReturnType<typeof packageReviewComparisonFixture>>;
const json = (v: unknown, status = 200) =>
  new Response(JSON.stringify(v), {
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
  f = await packageReviewComparisonFixture(23);
  fetchMock.mockImplementation(async (url: string) => {
    const path = url.replace(/^\/api\/v1/, "");
    if (path === packageReviewComparisonPath(f.request)) return json(f.page());
    if (path === packageReviewComparisonPath(f.request, "synthetic-20"))
      return json(f.page(20));
    const original =
      packageReviewOriginalFetch(f.left, path) ??
      packageReviewOriginalFetch(f.right, path);
    if (original) return json(original);
    throw new Error(`unexpected synthetic comparison read ${path}`);
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
const props = () => ({
  memberId: f.left.props.scope.memberId,
  bidId: f.request.bidId,
  currentRun: f.right.completed,
});
async function load() {
  await userEvent.type(
    screen.getByLabelText("左侧核查编号（比较基准）"),
    f.request.leftId,
  );
  await userEvent.click(screen.getByRole("button", { name: "读取两轮对比" }));
  await screen.findByText("对比不判定风险已经解决");
}
it("only reads after explicit selection, pages 20 rows and opens the exact original input without starting work", async () => {
  render(<Workspace {...props()} />);
  expect(fetchMock).not.toHaveBeenCalled();
  await load();
  expect(screen.getAllByRole("article")).toHaveLength(20);
  expect(screen.getByText(/共 23 条/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "下一页对比" }));
  await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(3));
  await userEvent.click(
    screen.getByText("本次对比摘要与核对范围", { selector: "summary" }),
  );
  expect(
    screen.getByText("所有分页的条数、变化分类与完整对比摘要已核对。"),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "上一页对比" }));
  expect(screen.getAllByRole("article")).toHaveLength(20);
  const opener = screen.getByRole("button", { name: "查看右侧原结果与引用" });
  await userEvent.click(opener);
  // The first open loads the lazy result workspace before its explicit reads.
  await screen.findByRole(
    "region",
    { name: "整包范围核查结果" },
    { timeout: 3000 },
  );
  expect(
    screen.getAllByRole("region", { name: "两轮范围核查对比" }),
  ).toHaveLength(1);
  expect(
    fetchMock.mock.calls.filter(([, options]) => options.method !== "GET"),
  ).toHaveLength(0);
  await userEvent.click(screen.getByRole("button", { name: "关闭原核查详情" }));
  expect(opener).toHaveFocus();
});
it("preserves only each member's two-run selection through remount and never automatically rereads", async () => {
  const view = render(<Workspace {...props()} />);
  await load();
  view.unmount();
  const calls = fetchMock.mock.calls.length;
  const again = render(<Workspace {...props()} />);
  expect(screen.getByLabelText("左侧核查编号（比较基准）")).toHaveValue(
    f.request.leftId,
  );
  expect(fetchMock).toHaveBeenCalledTimes(calls);
  again.rerender(<Workspace {...props()} memberId={id(990)} />);
  expect(screen.getByLabelText("左侧核查编号（比较基准）")).toHaveValue("");
});
it("opens a specific comparison row at its exact original requirement instead of the first report page", async () => {
  render(<Workspace {...props()} />);
  await load();
  await userEvent.click(screen.getByRole("button", { name: "下一页对比" }));
  const row = f.page(20).items[2];
  const article = await screen.findByRole("article", {
    name: `对比要求：${row.requirement_id}`,
  });
  await userEvent.click(
    within(article).getByRole("button", { name: "查看此项右侧原结果与引用" }),
  );
  const result = await screen.findByRole("region", {
    name: "整包范围核查结果",
  });
  expect(within(result).getByLabelText("查找要求编号或内容")).toHaveValue(
    row.requirement_id,
  );
  expect(within(result).getAllByRole("article")).toHaveLength(1);
  expect(
    within(result).getByRole("heading", {
      name: row.right!.requirement_statement,
    }),
  ).toBeInTheDocument();
  expect(
    fetchMock.mock.calls.filter(([, options]) => options.method !== "GET"),
  ).toHaveLength(0);
});
it("discards a late prior selection and does not let it release a newer read", async () => {
  let resolve!: (r: Response) => void;
  fetchMock.mockImplementationOnce(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  render(<Workspace {...props()} />);
  await userEvent.type(
    screen.getByLabelText("左侧核查编号（比较基准）"),
    f.request.leftId,
  );
  await userEvent.click(screen.getByRole("button", { name: "读取两轮对比" }));
  await userEvent.click(screen.getByRole("button", { name: "交换左右两侧" }));
  let resolveNew!: (r: Response) => void;
  fetchMock.mockImplementationOnce(
    () =>
      new Promise<Response>((done) => {
        resolveNew = done;
      }),
  );
  await userEvent.click(screen.getByRole("button", { name: "读取两轮对比" }));
  await act(async () => {
    resolve(json(f.page()));
  });
  expect(screen.queryByText("对比不判定风险已经解决")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "正在读取对比…" })).toBeDisabled();
  await act(async () => {
    resolveNew(
      json(
        {
          code: "PACKAGE_REVIEW_COMPARISON_RUN_UNFINISHED",
          message: "合成尚未完成",
        },
        409,
      ),
    );
  });
  await screen.findByText("合成尚未完成");
  expect(screen.getByRole("button", { name: "读取两轮对比" })).toBeEnabled();
});
it("stops paging after a changed human snapshot invalidates the cursor, keeping the prior page explicitly stale", async () => {
  render(<Workspace {...props()} />);
  await load();
  fetchMock.mockImplementationOnce(async () =>
    json({ code: "INVALID_CURSOR", message: "合成人工记录已变化" }, 422),
  );
  await userEvent.click(screen.getByRole("button", { name: "下一页对比" }));
  await screen.findByText(/已显示页面属于之前读取的快照/);
  expect(screen.getByRole("button", { name: "下一页对比" })).toBeDisabled();
  expect(screen.getAllByRole("article")).toHaveLength(20);
  await userEvent.click(screen.getByRole("button", { name: "读取两轮对比" }));
  await waitFor(() =>
    expect(
      screen.queryByText(/已显示页面属于之前读取的快照/),
    ).not.toBeInTheDocument(),
  );
});

it("bulk reads and exports all verified rows while viewing the first page", async () => {
  f = await packageReviewComparisonFixture(43);
  fetchMock.mockImplementation(async (url: string) => {
    const cursor = new URL(url, "https://example.test").searchParams.get(
      "cursor",
    );
    return json(f.page(cursor ? Number(cursor.replace("synthetic-", "")) : 0));
  });
  const create = vi.fn<(blob: Blob) => string>(() => "blob:comparison-test");
  const revoke = vi.fn();
  vi.stubGlobal(
    "URL",
    class extends URL {
      static createObjectURL = create;
      static revokeObjectURL = revoke;
    },
  );
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  render(<Workspace {...props()} />);
  await load();
  const download = screen.getByRole("button", { name: "导出完整对比 JSON" });
  expect(download).toBeDisabled();
  await userEvent.click(
    screen.getByRole("button", { name: "读取全部剩余对比" }),
  );
  await waitFor(() => expect(download).toBeEnabled());
  expect(fetchMock).toHaveBeenCalledTimes(3);
  await userEvent.click(screen.getByRole("button", { name: "上一页对比" }));
  await userEvent.click(screen.getByRole("button", { name: "上一页对比" }));
  expect(screen.getAllByRole("article")).toHaveLength(20);
  await userEvent.click(download);
  const contents = await new Promise<string>((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.readAsText(create.mock.calls[0][0]);
  });
  const exported = JSON.parse(contents);
  expect(exported.export_version).toBe("package-review-comparison-export/1");
  expect(exported.comparison.items).toEqual([
    ...f.page().items,
    ...f.page(20).items,
    ...f.page(40).items,
  ]);
  expect(exported.comparison.comparison_digest).toBe(
    f.page().comparison_digest,
  );
  expect(exported.comparison).not.toHaveProperty("next_cursor");
  expect(exported.notice).toContain("不判定风险已经解决");
  expect(
    (click.mock.instances[0] as unknown as HTMLAnchorElement).download,
  ).toBe(
    `package-review-comparison-${f.request.leftId}-${f.request.rightId}.json`,
  );
  await waitFor(() =>
    expect(revoke).toHaveBeenCalledWith("blob:comparison-test"),
  );
  expect(fetchMock).toHaveBeenCalledTimes(3);
});
it("blocks export and stops bulk reading when a continuation repeats rows", async () => {
  render(<Workspace {...props()} />);
  await load();
  fetchMock.mockImplementationOnce(async () => json(f.page()));
  await userEvent.click(
    screen.getByRole("button", { name: "读取全部剩余对比" }),
  );
  await screen.findByText(/此次对比不能继续翻页/);
  expect(
    screen.getByRole("button", { name: "导出完整对比 JSON" }),
  ).toBeDisabled();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});
it("discards pending bulk continuation when selected runs change", async () => {
  render(<Workspace {...props()} />);
  await load();
  let finish!: (response: Response) => void;
  fetchMock.mockImplementationOnce(
    () =>
      new Promise<Response>((resolve) => {
        finish = resolve;
      }),
  );
  await userEvent.click(
    screen.getByRole("button", { name: "读取全部剩余对比" }),
  );
  await userEvent.click(screen.getByRole("button", { name: "交换左右两侧" }));
  await act(async () => finish(json(f.page(20))));
  expect(
    screen.queryByRole("button", { name: "导出完整对比 JSON" }),
  ).not.toBeInTheDocument();
  expect(screen.queryAllByRole("article")).toHaveLength(0);
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it("never enables export when the complete snapshot digest is forged", async () => {
  fetchMock.mockImplementation(async (url: string) => {
    const cursor = new URL(url, "https://example.test").searchParams.get(
      "cursor",
    );
    return json({
      ...f.page(cursor ? 20 : 0),
      comparison_digest: "0".repeat(64),
    });
  });
  render(<Workspace {...props()} />);
  await load();
  await userEvent.click(
    screen.getByRole("button", { name: "读取全部剩余对比" }),
  );
  await screen.findByText(/此次对比不能继续翻页/);
  expect(
    screen.getByRole("button", { name: "导出完整对比 JSON" }),
  ).toBeDisabled();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});
