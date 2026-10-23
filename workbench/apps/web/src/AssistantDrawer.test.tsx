import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useCallback, useState } from "react";
import { AssistantDrawer } from "./AssistantDrawer";
import { assistantDockBounds } from "./assistantDock";
import { announceWorkspaceAuxiliary } from "./workspaceAuxiliary";

// Isolate presentation and lifetime from conversation HTTP, which is tested in
// AssistantWorkspace.test and the browser harness with real components.
vi.mock("./AssistantWorkspace", async () => {
  const { AssistantSourceSurface } = await import("./AssistantSourceSurface");
  return {
    AssistantWorkspace: function Workspace() {
      const [text, setText] = useState("");
      const [sources, setSources] = useState(false);
      return (
        <div>
          <label>
            合成提问
            <textarea
              value={text}
              onChange={(event) => setText(event.target.value)}
            />
          </label>
          <button onClick={() => setSources(true)}>选择来源</button>
          {sources && (
            <AssistantSourceSurface onClose={() => setSources(false)}>
              <label>
                来源查询
                <input />
              </label>
              <button>来源确认</button>
              <details>
                <summary>额外来源说明</summary>
                <button>折叠中的按钮</button>
              </details>
            </AssistantSourceSurface>
          )}
          <button>末尾可用操作</button>
        </div>
      );
    },
  };
});
let available = 1060;
const originalWidth = window.innerWidth;
function Fixture() {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  return (
    <main id="layout-task">
      <input aria-label="始终挂载的正文" defaultValue="正文草稿" />
      <button onClick={() => setOpen(true)}>打开项目助手</button>
      {open && (
        <AssistantDrawer
          bidId="bid-1"
          memberId="member-1"
          dockTargetId="layout-task"
          onClose={close}
        />
      )}
    </main>
  );
}
beforeEach(() => {
  localStorage.clear();
  available = 1060;
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: 1280,
  });
  const previous = HTMLElement.prototype.getBoundingClientRect;
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    function (this: HTMLElement) {
      return this.id === "layout-task"
        ? {
            width: available,
            height: 1400,
            left: window.innerWidth - available,
            right: window.innerWidth,
            top: 60,
            bottom: 1460,
            x: window.innerWidth - available,
            y: 60,
            toJSON: () => ({}),
          }
        : previous.call(this);
    },
  );
});
afterEach(() => {
  vi.restoreAllMocks();
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: originalWidth,
  });
});
it("reserves desktop body space, leaves Tab/body free, bounds keyboard resizing, and restores trigger focus", async () => {
  const user = userEvent.setup();
  render(<Fixture />);
  const opener = screen.getByRole("button", { name: "打开项目助手" });
  await user.click(opener);
  expect(
    screen.getByRole("complementary", { name: "项目主会话助手" }),
  ).not.toHaveAttribute("aria-modal");
  expect(document.body.style.overflow).not.toBe("hidden");
  expect(document.getElementById("layout-task")).toHaveAttribute(
    "data-assistant-docked",
    "true",
  );
  const divider = screen.getByRole("separator");
  divider.focus();
  await user.keyboard("{End}");
  expect(divider).toHaveAttribute("aria-valuenow", "428");
  expect(
    document
      .getElementById("layout-task")
      ?.style.getPropertyValue("--assistant-dock-space"),
  ).toBe("440px");
  await user.keyboard("{Home}{ArrowRight}");
  expect(divider).toHaveAttribute("aria-valuenow", "340");
  const body = screen.getByLabelText("始终挂载的正文");
  body.focus();
  expect(body).toHaveFocus();
  const tab = new KeyboardEvent("keydown", {
    key: "Tab",
    bubbles: true,
    cancelable: true,
  });
  screen.getByRole("button", { name: "末尾可用操作" }).dispatchEvent(tab);
  expect(tab.defaultPrevented).toBe(false);
  screen.getByLabelText("合成提问").focus();
  await user.keyboard("{Escape}");
  expect(opener).toHaveFocus();
  expect(document.getElementById("layout-task")).not.toHaveAttribute(
    "data-assistant-docked",
  );
  expect(
    document
      .getElementById("layout-task")
      ?.style.getPropertyValue("--assistant-dock-space"),
  ).toBe("");
});
it("keeps the same composer and body draft mounted across desktop / compact / desktop", async () => {
  const user = userEvent.setup();
  render(<Fixture />);
  await user.click(screen.getByRole("button", { name: "打开项目助手" }));
  const input = screen.getByLabelText("合成提问"),
    body = screen.getByLabelText("始终挂载的正文");
  await user.type(input, "未发送的提问");
  available = 390;
  act(() => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 390,
    });
    window.dispatchEvent(new Event("resize"));
  });
  expect(
    screen.getByRole("dialog", { name: "项目主会话助手" }),
  ).toHaveAttribute("aria-modal", "true");
  expect(document.body.style.overflow).toBe("hidden");
  expect(screen.getByLabelText("合成提问")).toBe(input);
  expect(input).toHaveValue("未发送的提问");
  screen.getByRole("button", { name: "末尾可用操作" }).focus();
  await user.tab();
  expect(screen.getByRole("button", { name: "收起助手" })).toHaveFocus();
  available = 1060;
  act(() => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1280,
    });
    window.dispatchEvent(new Event("resize"));
  });
  expect(
    screen.getByRole("complementary", { name: "项目主会话助手" }),
  ).toBeVisible();
  expect(document.body.style.overflow).not.toBe("hidden");
  expect(screen.getByLabelText("合成提问")).toBe(input);
  expect(screen.getByLabelText("始终挂载的正文")).toBe(body);
});
it("compact sources close first with Escape, keep the question, and restore each focus level", async () => {
  available = 390;
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: 390,
  });
  const user = userEvent.setup();
  render(<Fixture />);
  const opener = screen.getByRole("button", { name: "打开项目助手" });
  await user.click(opener);
  await user.type(screen.getByLabelText("合成提问"), "保留未发送稿");
  const source = screen.getByRole("button", { name: "选择来源" });
  await user.click(source);
  expect(screen.getAllByRole("dialog")).toHaveLength(2);
  screen.getByText("额外来源说明").focus();
  await user.tab();
  expect(screen.getByRole("button", { name: "返回提问" })).toHaveFocus();
  await user.keyboard("{Escape}");
  expect(
    screen.queryByRole("dialog", { name: "选择本次消息来源" }),
  ).not.toBeInTheDocument();
  expect(source).toHaveFocus();
  expect(document.body.style.overflow).toBe("hidden");
  expect(screen.getByLabelText("合成提问")).toHaveValue("保留未发送稿");
  await user.keyboard("{Escape}");
  expect(opener).toHaveFocus();
  expect(document.body.style.overflow).not.toBe("hidden");
});
it("only another auxiliary view in the same project closes the assistant", async () => {
  render(<Fixture />);
  fireEvent.click(screen.getByRole("button", { name: "打开项目助手" }));
  act(() => announceWorkspaceAuxiliary("bid-2", "directory"));
  expect(screen.getByRole("complementary")).toBeInTheDocument();
  act(() => announceWorkspaceAuxiliary("bid-1", "directory"));
  await waitFor(() =>
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument(),
  );
});
it("never docks when either task would be below its minimum", () => {
  expect(assistantDockBounds(971, 400).docked).toBe(false);
  expect(assistantDockBounds(972, 999)).toEqual({
    docked: true,
    max: 340,
    width: 340,
  });
  expect(assistantDockBounds(2000, -100).width).toBe(340);
  expect(assistantDockBounds(2000, 999).width).toBe(720);
});
