import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ApiError } from "./api";
import { ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";

it("keeps the actionable error visible and reveals the original diagnostics only on request", async () => {
  const retry = vi.fn();
  render(
    <ErrorNotice
      error={
        new ApiError(
          "来源已经变化，请重新核对。",
          409,
          "SOURCE_CHANGED",
          "request-original",
          false,
          { expected_revision: 7 },
        )
      }
      onRetry={retry}
    />,
  );
  expect(screen.getByRole("alert")).toHaveTextContent(
    "来源已经变化，请重新核对。",
  );
  const detail = screen.getByText("查看错误详情").closest("details")!;
  expect(detail).not.toHaveAttribute("open");
  expect(within(detail).getByText("request-original")).not.toBeVisible();
  await userEvent.click(screen.getByText("查看错误详情"));
  expect(within(detail).getByText("SOURCE_CHANGED")).toBeVisible();
  expect(within(detail).getByText(/expected_revision/)).toBeVisible();
  expect(retry).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "重试" }));
  expect(retry).toHaveBeenCalledOnce();
});

it("shows first-read skeletons without asserting an empty result or inventing records", () => {
  const view = render(
    <ResourceState
      loading
      hasData={false}
      onRetry={vi.fn()}
      emptyLabel="当前没有已保存结果"
      loadingLabel="正在读取原记录…"
    />,
  );
  expect(screen.getByRole("status")).toHaveTextContent("正在读取原记录…");
  expect(screen.queryByText("当前没有已保存结果")).not.toBeInTheDocument();
  view.rerender(
    <ResourceState
      loading
      hasData
      onRetry={vi.fn()}
      emptyLabel="当前没有已保存结果"
    />,
  );
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("provides an explicit read action for an empty resource and preserves the caller's domain action", async () => {
  const retry = vi.fn(),
    create = vi.fn();
  const view = render(
    <ResourceState hasData={false} onRetry={retry} emptyLabel="尚未保存模板" />,
  );
  expect(retry).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "重新读取" }));
  expect(retry).toHaveBeenCalledOnce();
  view.rerender(
    <ResourceState
      hasData={false}
      onRetry={retry}
      emptyLabel="尚未保存模板"
      emptyAction={<button onClick={create}>配置模板</button>}
    />,
  );
  expect(
    screen.queryByRole("button", { name: "重新读取" }),
  ).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "配置模板" }));
  expect(create).toHaveBeenCalledOnce();
});
