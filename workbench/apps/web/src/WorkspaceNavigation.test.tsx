import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { WorkspaceNavigation } from "./WorkspaceNavigation";

const capability = vi.hoisted(() => ({
  pricing: true,
  tasks: true,
  bidId: "project-a",
  error: false,
}));
vi.mock("./api", () => ({
  supportsApi: (_method: string, path: string) =>
    path.endsWith("/task-definitions") ? capability.tasks : capability.pricing,
}));
vi.mock("./contracts", () => ({ taskTemplatesContractReady: true }));
vi.mock("./useResource", () => ({
  useResource: () => ({
    data: { bid_id: capability.bidId, settings: { pricing: true } },
    error: capability.error ? new Error("read failed") : null,
  }),
}));

beforeEach(() => {
  capability.pricing = true;
  capability.tasks = true;
  capability.bidId = "project-a";
  capability.error = false;
});

it("keeps the five primary destinations visible and preserves secondary deep links behind more", async () => {
  const navigate = vi.fn(),
    user = userEvent.setup();
  render(
    <WorkspaceNavigation
      bidId="project-a"
      page="overview"
      onNavigate={navigate}
    />,
  );
  const nav = screen.getByRole("navigation", { name: "项目工作区" });
  expect(
    within(nav)
      .getAllByRole("link")
      .map((link) => link.textContent),
  ).toEqual(["项目概览", "项目资料", "整包核查", "章节编制", "实交与成绩"]);
  await user.click(screen.getByRole("button", { name: "更多工作区" }));
  const legacy = screen.getByRole("link", { name: "单稿评审历史" });
  expect(legacy).toHaveAttribute("href", "/bids/project-a/review");
  await user.click(legacy);
  expect(navigate).toHaveBeenCalledWith("review");
  expect(screen.getByRole("button", { name: "更多工作区" })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
});

it("closes secondary navigation with Escape and restores focus, and closes on an outside pointer", async () => {
  const user = userEvent.setup();
  render(
    <WorkspaceNavigation bidId="project-a" page="rules" onNavigate={vi.fn()} />,
  );
  const button = screen.getByRole("button", { name: "更多 · 规则核对" });
  await user.click(button);
  screen.getByRole("link", { name: "规则核对" }).focus();
  await user.keyboard("{Escape}");
  expect(button).toHaveFocus();
  expect(button).toHaveAttribute("aria-expanded", "false");
  await user.click(button);
  fireEvent.pointerDown(document.body);
  expect(button).toHaveAttribute("aria-expanded", "false");
});

it("routes the compact selector through the parent's navigation guard without altering current selection itself", () => {
  const navigate = vi.fn();
  render(
    <WorkspaceNavigation
      bidId="project-a"
      page="packages"
      onNavigate={navigate}
    />,
  );
  const picker = screen.getByRole("combobox", { name: "当前工作区" });
  fireEvent.change(picker, { target: { value: "authoring" } });
  expect(navigate).toHaveBeenCalledOnce();
  expect(navigate).toHaveBeenCalledWith("authoring");
  expect(picker).toHaveValue("packages");
});

it("does not offer missing capabilities or another project's pricing settings and keeps unavailable current identity", () => {
  capability.tasks = false;
  capability.bidId = "another-project";
  render(
    <WorkspaceNavigation
      bidId="project-a"
      page="pricing"
      onNavigate={vi.fn()}
    />,
  );
  expect(
    screen.queryByRole("option", { name: "可复用任务" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("option", { name: "报价情景" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("option", { name: "报价情景（暂不可用）" }),
  ).toBeDisabled();
  expect(screen.getByRole("combobox", { name: "当前工作区" })).toHaveValue(
    "pricing",
  );
});
