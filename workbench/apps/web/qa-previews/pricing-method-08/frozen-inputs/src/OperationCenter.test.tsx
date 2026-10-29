import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { it, expect, vi } from "vitest";
import { OperationCenter } from "./OperationCenter";
it("只折叠服务端成功处理；运行/失败常驻且UUID仅在详情显示", async () => {
  localStorage.setItem(
    "tender:operations:bid",
    JSON.stringify(["done1", "done2", "failed", "running"]),
  );
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const id = url.split("/").at(-1)!;
      return new Response(
        JSON.stringify({
          id,
          bid_id: "bid",
          kind: "prepare-review",
          state: id.startsWith("done") ? "succeeded" : id,
          handler_version: "test/1",
        }),
      );
    }),
  );
  const u = userEvent.setup();
  render(<OperationCenter bidId="bid" />);
  const summary = await screen.findByText("已完成 2 项处理");
  expect(summary.closest("details")).not.toHaveAttribute("open");
  expect(await screen.findByText("执行失败")).toBeVisible();
  expect(await screen.findByText("正在处理")).toBeVisible();
  await u.click(summary);
  await waitFor(() =>
    expect(summary.closest("details")).toHaveAttribute("open"),
  );
  expect(screen.getAllByText("执行已结束")).toHaveLength(2);
  expect(screen.queryByText(/记录标识/)).toBeNull();
});
