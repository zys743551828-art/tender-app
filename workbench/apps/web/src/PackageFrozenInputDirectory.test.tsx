import { StrictMode } from "react";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import PackageFrozenInputDirectory from "./PackageFrozenInputDirectory";
import { validateFrozenInputPage } from "./frozenInputDirectory";
import type { FrozenInputSummary } from "./frozenInputDirectory";
import type { FreezeScope } from "./packageFrozenInput";
import type { PackageReviewFrozenInputPage } from "./contracts";

const id = (n: number) =>
  `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
const scope: FreezeScope = {
  memberId: id(1),
  bidId: id(2),
  packageId: id(3),
  revisionId: id(4),
  inventoryId: id(5),
};
const row = (n = 1): FrozenInputSummary => ({
  id: id(n + 10),
  actor_id: id(1),
  digest: "a".repeat(64),
  input_digest: "b".repeat(64),
  context_digest: "c".repeat(64),
  frozen_at: `2026-10-19T08:00:${String(59 - n).padStart(2, "0")}.000001Z`,
});
const page = (
  items: FrozenInputSummary[] = [row()],
  next: string | null = null,
): PackageReviewFrozenInputPage => ({
  bid_id: scope.bidId,
  package_id: scope.packageId,
  revision_id: scope.revisionId,
  inventory_id: scope.inventoryId,
  items,
  has_more: next !== null,
  next_cursor: next,
});
const respond = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

it("闭合时不读目录，打开后显式选择，不自动采用最新记录", async () => {
  const selected = vi.fn();
  fetchMock.mockImplementation(async () => respond(page()));
  const view = render(
    <StrictMode>
      <PackageFrozenInputDirectory
        scope={scope}
        enabled={false}
        onSelect={selected}
      />
    </StrictMode>,
  );
  expect(fetchMock).not.toHaveBeenCalled();
  view.rerender(
    <StrictMode>
      <PackageFrozenInputDirectory scope={scope} enabled onSelect={selected} />
    </StrictMode>,
  );
  const button = await screen.findByRole("button", {
    name: /查看.*的冻结记录/,
  });
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(selected).not.toHaveBeenCalled();
  await userEvent.click(button);
  expect(selected).toHaveBeenCalledExactlyOnceWith(row());
  expect(fetchMock.mock.calls[0][1].method).toBe("GET");
});

it("加载下一页携带原游标，首屏刷新重新查询并清掉旧尾页", async () => {
  fetchMock.mockImplementation(async (path: string) =>
    respond(
      path.includes("cursor=") ? page([row(2)]) : page([row()], "signed/one+"),
    ),
  );
  render(
    <PackageFrozenInputDirectory scope={scope} enabled onSelect={vi.fn()} />,
  );
  await screen.findByText("已读取 1 条记录。");
  await userEvent.click(
    screen.getByRole("button", { name: "加载更多冻结记录" }),
  );
  await screen.findByText("已读取 2 条记录。");
  expect(fetchMock.mock.calls[1][0]).toContain("cursor=signed%2Fone%2B");
  await userEvent.click(screen.getByRole("button", { name: "刷新历史目录" }));
  await screen.findByText("已读取 1 条记录。");
  expect(screen.queryByText(id(12))).not.toBeInTheDocument();
});

it.each([
  "scope",
  "duplicate",
  "order",
  "cursor",
  "empty-more",
  "digest",
  "date",
])("拒绝%s坏分页，保留已核对首屏", async (kind) => {
  const bad = page([row(2)]);
  if (kind === "scope") bad.inventory_id = id(99);
  if (kind === "duplicate") bad.items = [row()];
  if (kind === "order")
    bad.items = [{ ...row(2), frozen_at: "2026-10-19T09:00:00Z" }];
  if (kind === "cursor") {
    bad.has_more = true;
    bad.next_cursor = "first";
  }
  if (kind === "empty-more") {
    bad.items = [];
    bad.has_more = true;
    bad.next_cursor = "second";
  }
  if (kind === "digest") bad.items[0].digest = "broken";
  if (kind === "date") bad.items[0].frozen_at = "broken";
  fetchMock.mockImplementation(async (path: string) =>
    respond(path.includes("cursor=") ? bad : page([row()], "first")),
  );
  render(
    <PackageFrozenInputDirectory scope={scope} enabled onSelect={vi.fn()} />,
  );
  await screen.findByText("已读取 1 条记录。");
  await userEvent.click(
    screen.getByRole("button", { name: "加载更多冻结记录" }),
  );
  await screen.findByRole("alert");
  expect(screen.getByText("已读取 1 条记录。")).toBeInTheDocument();
  expect(
    screen.getAllByRole("button", { name: /查看.*的冻结记录/ }),
  ).toHaveLength(1);
});

it("拒绝A→B→A游标循环，不无限拼接目录", () => {
  expect(() =>
    validateFrozenInputPage(
      page([row(3)], "A"),
      scope,
      [row(), row(2)],
      ["A", "B"],
    ),
  ).toThrow(/分页响应不符/);
});

it("微秒排序不按毫秒误判，同一时点按UUID降序", () => {
  const a = { ...row(), id: id(10), frozen_at: "2026-10-19T08:00:00.000002Z" };
  const b = { ...row(2), id: id(99), frozen_at: "2026-10-19T08:00:00.000001Z" };
  expect(() => validateFrozenInputPage(page([a, b]), scope)).not.toThrow();
  expect(() => validateFrozenInputPage(page([b, a]), scope)).toThrow();
  expect(() =>
    validateFrozenInputPage(page([{ ...a, id: id(20) }, a]), scope),
  ).not.toThrow();
  expect(() =>
    validateFrozenInputPage(page([a, { ...a, id: id(20) }]), scope),
  ).toThrow();
});

it("关闭再打开后忽略上次慢响应，成员／清单变化同样隔离", async () => {
  let finish!: (value: Response) => void;
  fetchMock.mockImplementationOnce(
    () =>
      new Promise<Response>((resolve) => {
        finish = resolve;
      }),
  );
  const view = render(
    <PackageFrozenInputDirectory scope={scope} enabled onSelect={vi.fn()} />,
  );
  view.rerender(
    <PackageFrozenInputDirectory
      scope={scope}
      enabled={false}
      onSelect={vi.fn()}
    />,
  );
  fetchMock.mockImplementation(async () => respond(page([])));
  view.rerender(
    <PackageFrozenInputDirectory scope={scope} enabled onSelect={vi.fn()} />,
  );
  await screen.findByText("此清单尚无冻结输入记录。");
  await act(async () => finish(respond(page())));
  expect(
    screen.queryByRole("button", { name: /查看.*的冻结记录/ }),
  ).not.toBeInTheDocument();
  const other = { ...scope, memberId: id(90), inventoryId: id(99) };
  fetchMock.mockImplementation(async () =>
    respond({ ...page([]), inventory_id: id(99) }),
  );
  view.rerender(
    <PackageFrozenInputDirectory scope={other} enabled onSelect={vi.fn()} />,
  );
  await screen.findByText("此清单尚无冻结输入记录。");
  expect(fetchMock.mock.calls.at(-1)![0]).toContain(
    `/requirement-inventories/${id(99)}/`,
  );
});

it("保存成功后的刷新信号重读首屏；失败读取可手动恢复", async () => {
  fetchMock.mockImplementationOnce(async () =>
    respond({ code: "TEMPORARY", message: "稍后再试" }, 503),
  );
  const view = render(
    <PackageFrozenInputDirectory scope={scope} enabled onSelect={vi.fn()} />,
  );
  await screen.findByRole("alert");
  fetchMock.mockImplementation(async () => respond(page()));
  await userEvent.click(screen.getByRole("button", { name: "刷新历史目录" }));
  await screen.findByText("已读取 1 条记录。");
  fetchMock.mockImplementation(async () => respond(page([])));
  view.rerender(
    <PackageFrozenInputDirectory
      scope={scope}
      enabled
      refreshId={id(99)}
      onSelect={vi.fn()}
    />,
  );
  await screen.findByText("此清单尚无冻结输入记录。");
});
