import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AuthoringPanel } from "./AuthoringPanel";
import {
  authoringLayoutFixture,
  layoutScope,
} from "./authoringLayoutFixtures.test-support";
import { setAuth } from "./api";
import { announceWorkspaceAuxiliary } from "./workspaceAuxiliary";

let fixture = authoringLayoutFixture();
let width = 390;
beforeEach(() => {
  fixture = authoringLayoutFixture();
  localStorage.clear();
  sessionStorage.clear();
  vi.stubGlobal("fetch", vi.fn(fixture.fetcher));
  setAuth({
    member: {
      id: layoutScope.memberId,
      display_name: "合成交互验收",
      active: true,
    },
    csrf_token: "synthetic-not-a-credential",
    expires_at: "2099-01-01T00:00:00Z",
  });
  const previous = HTMLElement.prototype.getBoundingClientRect;
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    function (this: HTMLElement) {
      return this.classList.contains("authoring-columns")
        ? {
            width,
            height: 800,
            left: 0,
            right: width,
            top: 200,
            bottom: 1000,
            x: 0,
            y: 200,
            toJSON: () => ({}),
          }
        : previous.call(this);
    },
  );
});
afterEach(() => vi.restoreAllMocks());
function show() {
  return render(
    <AuthoringPanel
      {...layoutScope}
      projectTitle="合成编制项目"
      onOpenDraft={vi.fn()}
    />,
  );
}
it("starts with the body, keeps directory/editor mounted while collapsed, and restores directory focus", async () => {
  width = 390;
  const user = userEvent.setup();
  show();
  const body = await screen.findByLabelText("章节正文");
  const management = screen.getByText("草稿管理与新建").closest("details");
  expect(management).not.toHaveAttribute("open");
  expect(
    screen.queryByRole("button", { name: "创建正文草稿" }),
  ).not.toBeVisible();
  const opener = screen.getByRole("button", { name: "章节目录与计划" });
  await user.click(opener);
  const directory = screen.getByRole("dialog", { name: "章节目录与编写计划" });
  expect(directory).toHaveAttribute("aria-modal", "true");
  expect(body.closest("section")).toHaveAttribute("inert");
  expect(document.body.style.overflow).toBe("hidden");
  await user.keyboard("{Escape}");
  expect(opener).toHaveFocus();
  expect(directory).toHaveAttribute("hidden");
  expect(screen.getByLabelText("章节正文")).toBe(body);
  expect(document.body.style.overflow).not.toBe("hidden");
  expect(fixture.state.unexpected).toEqual([]);
});
it("a failed save prevents chapter changes, retains the actual editor, and retries the same command", async () => {
  width = 390;
  fixture.state.saveMode = "offline";
  const user = userEvent.setup();
  show();
  await screen.findByLabelText("章节正文");
  const writing = within(screen.getByRole("region", { name: "正文编写" }));
  const title = writing.getByLabelText("章节名称");
  const body = screen.getByLabelText("章节正文");
  fireEvent.change(title, { target: { value: "本地待保存章节名称" } });
  await user.click(screen.getByRole("button", { name: "章节目录与计划" }));
  const directory = screen.getByRole("dialog", { name: "章节目录与编写计划" });
  await user.click(
    within(directory).getByRole("button", { name: /质量保障措施/ }),
  );
  await within(directory).findByText(/本章保存尚未确认，未切换章节/);
  expect(writing.getByLabelText("章节名称")).toBe(title);
  expect(title).toHaveValue("本地待保存章节名称");
  expect(screen.getByLabelText("章节正文")).toBe(body);
  expect(fixture.state.appliedSaves).toBe(0);
  const first = fixture.state.writes[0];
  expect(first.key).toBeTruthy();
  await user.click(within(directory).getByRole("button", { name: "收起目录" }));
  fixture.state.saveMode = "ok";
  await user.click(screen.getByRole("button", { name: "重试保存" }));
  await screen.findByText(/已保存 · 章节修订 2/);
  expect(fixture.state.writes[1]).toEqual(first);
  expect(fixture.state.appliedSaves).toBe(1);
  await user.click(screen.getByRole("button", { name: "章节目录与计划" }));
  await user.click(
    within(directory).getByRole("button", { name: /质量保障措施/ }),
  );
  await waitFor(() =>
    expect(writing.getByLabelText("章节名称")).toHaveValue("质量保障措施"),
  );
  expect(directory).toHaveAttribute("hidden");
  expect(fixture.state.unexpected).toEqual([]);
});
it("desktop directory can collapse for another same-project task without saving or remounting the body", async () => {
  width = 1100;
  const user = userEvent.setup();
  show();
  const body = await screen.findByLabelText("章节正文");
  await user.click(screen.getByRole("button", { name: "章节目录与计划" }));
  const directory = screen.getByRole("complementary", {
    name: "章节目录与编写计划",
  });
  expect(document.body.style.overflow).not.toBe("hidden");
  act(() => announceWorkspaceAuxiliary("another-project", "assistant"));
  expect(directory).not.toHaveAttribute("hidden");
  act(() => announceWorkspaceAuxiliary(layoutScope.bidId, "assistant"));
  expect(directory).toHaveAttribute("hidden");
  expect(screen.getByLabelText("章节正文")).toBe(body);
  expect(fixture.state.writes).toHaveLength(0);
});
