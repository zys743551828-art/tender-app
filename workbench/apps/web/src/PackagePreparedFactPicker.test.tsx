import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Picker from "./PackagePreparedFactPicker";
import type {
  PackageExecutionInputView,
  PackagePreparedFactPage,
} from "./contracts";
import { matchesPreparedFacts } from "./preparedFactDirectory";
const id = (n: number) =>
  `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
const scope = {
  memberId: id(1),
  bidId: id(2),
  packageId: id(3),
  revisionId: id(4),
  inventoryId: id(5),
};
const prepared = {
  digest: "a".repeat(64),
  manifest: {
    id: id(7),
    execution_context: {
      fact_count: 2,
      fact_set_id: id(50),
      facts_digest: "b".repeat(64),
    },
  },
} as PackageExecutionInputView;
const row = (n: number) => ({
  fact_id: id(n),
  fact_item_digest: "c".repeat(64),
  name: n === 90 ? "合同工期" : "总建筑面积",
  subject: "本工程",
  scope: "本标段",
  value_preview: n === 90 ? "180" : "10000",
  unit: n === 90 ? "天" : "平方米",
  preview_truncated: false,
});
const page = (): PackagePreparedFactPage => ({
  bid_id: scope.bidId,
  package_id: scope.packageId,
  revision_id: scope.revisionId,
  inventory_id: scope.inventoryId,
  frozen_input_id: id(6),
  execution_input_id: id(7),
  execution_input_digest: prepared.digest,
  facts_digest: "b".repeat(64),
  fact_set_id: id(50),
  fact_count: 2,
  items: [row(90)],
  has_more: true,
  next_cursor: "synthetic:page-2",
});
const mock = vi.fn();
const select = vi.fn();
const props = {
  scope,
  frozenId: id(6),
  prepared,
  disabled: false,
  onSelect: select,
};
const response = (data: unknown) =>
  new Response(JSON.stringify(data), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
beforeEach(() => {
  mock.mockReset();
  select.mockReset();
  vi.stubGlobal("fetch", mock);
});
afterEach(() => vi.unstubAllGlobals());
it("显式读取原摘要并按名称选择，分页不自动发请求", async () => {
  mock.mockResolvedValueOnce(response(page()));
  mock.mockResolvedValueOnce(
    response({
      ...page(),
      items: [row(91)],
      has_more: false,
      next_cursor: null,
    }),
  );
  render(<Picker {...props} />);
  expect(mock).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "读取原事实列表" }));
  await userEvent.click(
    await screen.findByRole("button", { name: /合同工期 · 180 天/ }),
  );
  expect(select).toHaveBeenCalledWith(row(90));
  expect(mock).toHaveBeenCalledTimes(1);
  await userEvent.click(screen.getByRole("button", { name: "加载更多原事实" }));
  await screen.findByRole("button", { name: /总建筑面积 · 10000 平方米/ });
  expect(String(mock.mock.calls[1][0])).toContain("cursor=synthetic%3Apage-2");
});
it("重复页不追加或继续翻页，旧列表保留", async () => {
  mock.mockResolvedValueOnce(response(page()));
  mock.mockResolvedValueOnce(
    response({ ...page(), has_more: false, next_cursor: null }),
  );
  render(<Picker {...props} />);
  await userEvent.click(screen.getByRole("button", { name: "读取原事实列表" }));
  await screen.findByRole("button", { name: /合同工期/ });
  await userEvent.click(screen.getByRole("button", { name: "加载更多原事实" }));
  await screen.findByText(/原事实目录出现重复记录或游标/);
  expect(screen.getAllByRole("button", { name: /合同工期/ })).toHaveLength(1);
});
it("准备记录切换后迟到目录不会展示或选中旧事实", async () => {
  let resolve!: (r: Response) => void;
  mock.mockReturnValueOnce(
    new Promise<Response>((r) => {
      resolve = r;
    }),
  );
  const view = render(<Picker {...props} />);
  await userEvent.click(screen.getByRole("button", { name: "读取原事实列表" }));
  view.rerender(
    <Picker
      {...props}
      prepared={{ ...prepared, manifest: { ...prepared.manifest, id: id(99) } }}
    />,
  );
  await act(async () => {
    resolve(response(page()));
  });
  expect(
    screen.queryByRole("button", { name: /合同工期/ }),
  ).not.toBeInTheDocument();
  expect(select).not.toHaveBeenCalled();
});
it("摘要截断单独说明，长Unicode摘要按码点校验", async () => {
  const v = page();
  v.items[0].value_preview = "🙂".repeat(240);
  v.items[0].preview_truncated = true;
  expect(matchesPreparedFacts(v, scope, id(6), prepared, null)).toBe(true);
  mock.mockResolvedValueOnce(response(v));
  render(<Picker {...props} />);
  await userEvent.click(screen.getByRole("button", { name: "读取原事实列表" }));
  await screen.findByText("摘要有截断，请结合完整原资料核对。");
});
it.each([
  "scope",
  "prepared",
  "facts",
  "set",
  "count",
  "duplicate",
  "cursor",
  "length",
])("目录%s不符不用于选择", (change) => {
  const v = page();
  if (change === "scope") v.package_id = id(99);
  if (change === "prepared") v.execution_input_digest = "f".repeat(64);
  if (change === "facts") v.facts_digest = "f".repeat(64);
  if (change === "set") v.fact_set_id = id(99);
  if (change === "count") v.fact_count = 3;
  if (change === "duplicate") v.items.push({ ...v.items[0] });
  if (change === "cursor") v.next_cursor = null;
  if (change === "length") v.items[0].name = "甲".repeat(241);
  expect(matchesPreparedFacts(v, scope, id(6), prepared, null)).toBe(false);
});
