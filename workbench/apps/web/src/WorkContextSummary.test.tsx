import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { workContextFixture } from "../qa-previews/frozen-inputs/workContext";
import { WorkContextSummary } from "./WorkContextSummary";

let f: Awaited<ReturnType<typeof workContextFixture>>;
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  f = await workContextFixture();
});
it("shows scoped counts and unknown whole-package scoring without manufacturing a green pass", async () => {
  const open = vi.fn(),
    pkg = vi.fn();
  render(
    <WorkContextSummary
      context={f.context}
      onOpenOriginal={open}
      onOpenPackage={pkg}
    />,
  );
  expect(screen.getByText("尚未完整评估")).toBeVisible();
  expect(screen.getByText("尚未选择评分范围")).toBeVisible();
  expect(screen.getByText(/整体覆盖为部分/)).toBeVisible();
  expect(
    screen.queryByText(/整包通过|合规率|正式技术分：0/),
  ).not.toBeInTheDocument();
  expect(screen.getByText(f.context.selection_digest)).not.toBeVisible();
  await userEvent.click(
    screen.getByRole("button", { name: "读取所选核查原记录" }),
  );
  expect(open).toHaveBeenCalledOnce();
  await userEvent.click(screen.getByRole("button", { name: "打开此包修订" }));
  expect(pkg).toHaveBeenCalledWith({
    packageId: f.props.scope.packageId,
    revisionId: f.props.scope.revisionId,
    inventoryId: f.props.scope.inventoryId,
  });
});
it("uses the server's change-inspection action and keeps identity details folded", async () => {
  f.context.summary.primary_action = "inspect_changed_basis";
  f.context.current_observation.sources.status = "changed";
  const open = vi.fn();
  render(
    <WorkContextSummary
      context={f.context}
      onOpenOriginal={open}
      onOpenPackage={vi.fn()}
    />,
  );
  expect(screen.getByText("1 项依据已变化")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "核对变化依据" }));
  expect(screen.getByRole("table")).toBeVisible();
  expect(screen.getByText("当前依据逐项观察")).toHaveFocus();
  expect(open).not.toHaveBeenCalled();
  expect(screen.getByText(f.context.selection_digest)).not.toBeVisible();
});
