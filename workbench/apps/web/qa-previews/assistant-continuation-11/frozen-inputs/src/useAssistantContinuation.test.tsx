import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { useAssistantContinuation } from "./useAssistantContinuation";

let frames: Map<number, FrameRequestCallback>;
let frameId = 0;
let resize: ResizeObserverCallback;
let scroll: ReturnType<typeof vi.fn>;
function flush() {
  act(() => {
    const current = [...frames.values()];
    frames.clear();
    current.forEach((callback) => callback(0));
  });
}
function resizeContent() {
  act(() => resize([], {} as ResizeObserver));
  flush();
}
function Page({
  ready = true,
  auto = true,
}: {
  ready?: boolean;
  auto?: boolean;
}) {
  const position = useAssistantContinuation(ready, auto);
  return (
    <div ref={position.content}>
      <button onClick={position.continueWriting}>回到最新／继续提问</button>
      <button>阅读旧记录</button>
      <textarea aria-label="当前输入" ref={position.input} />
    </div>
  );
}
beforeEach(() => {
  frames = new Map();
  frameId = 0;
  scroll = vi.fn();
  vi.stubGlobal(
    "requestAnimationFrame",
    vi.fn((callback: FrameRequestCallback) => {
      frames.set(++frameId, callback);
      return frameId;
    }),
  );
  vi.stubGlobal(
    "cancelAnimationFrame",
    vi.fn((id: number) => frames.delete(id)),
  );
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: ResizeObserverCallback) {
        resize = callback;
      }
      observe() {}
      disconnect() {}
    },
  );
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    value: scroll,
    configurable: true,
  });
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
    top: 3000,
    bottom: 3120,
    left: 0,
    right: 300,
    width: 300,
    height: 120,
    x: 0,
    y: 3000,
    toJSON() {
      return {};
    },
  });
});
afterEach(() => vi.restoreAllMocks());
it("首次快照就绪一次定位输入，后续轮询快照不能重新聚焦或跳底", () => {
  const view = render(<Page ready={false} />);
  flush();
  expect(scroll).not.toHaveBeenCalled();
  view.rerender(<Page ready />);
  flush();
  expect(scroll).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("当前输入")).toHaveFocus();
  view.rerender(<Page ready={false} />);
  view.rerender(<Page ready />);
  flush();
  expect(scroll).toHaveBeenCalledTimes(1);
});
it("仍在输入时迟到卡片改变高度可保持输入可见，不再次调用focus", () => {
  render(<Page />);
  flush();
  const focus = vi.spyOn(screen.getByLabelText("当前输入"), "focus");
  resizeContent();
  expect(scroll).toHaveBeenCalledTimes(2);
  expect(focus).not.toHaveBeenCalled();
});
it("上滚读历史后，布局和轮询不抢位置；显式回到最新才恢复跟随", async () => {
  const user = userEvent.setup();
  render(<Page />);
  flush();
  fireEvent.wheel(window, { deltaY: -600 });
  resizeContent();
  expect(scroll).toHaveBeenCalledTimes(1);
  await user.click(screen.getByRole("button", { name: "阅读旧记录" }));
  resizeContent();
  expect(screen.getByRole("button", { name: "阅读旧记录" })).toHaveFocus();
  expect(scroll).toHaveBeenCalledTimes(1);
  await user.click(screen.getByRole("button", { name: "回到最新／继续提问" }));
  expect(screen.getByLabelText("当前输入")).toHaveFocus();
  expect(scroll).toHaveBeenCalledTimes(2);
});
it("键盘Tab＋Enter的继续入口聚焦输入，触摸读历史仍停止自动移动", async () => {
  const user = userEvent.setup();
  render(<Page auto={false} />);
  flush();
  await user.tab();
  expect(
    screen.getByRole("button", { name: "回到最新／继续提问" }),
  ).toHaveFocus();
  await user.keyboard("{Enter}");
  expect(screen.getByLabelText("当前输入")).toHaveFocus();
  expect(scroll).toHaveBeenCalledTimes(1);
  fireEvent.touchMove(window);
  resizeContent();
  expect(scroll).toHaveBeenCalledTimes(1);
});
it("等服务时用户已开始读历史，不在迟到响应后强抢焦点", () => {
  const view = render(<Page ready={false} />);
  fireEvent.wheel(window, { deltaY: -300 });
  view.rerender(<Page ready />);
  flush();
  expect(scroll).not.toHaveBeenCalled();
  expect(screen.getByLabelText("当前输入")).not.toHaveFocus();
});
it("显式Action链接保持对象定位，仍可主动继续提问", async () => {
  const user = userEvent.setup();
  render(<Page auto={false} />);
  flush();
  expect(scroll).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "回到最新／继续提问" }));
  expect(screen.getByLabelText("当前输入")).toHaveFocus();
  expect(scroll).toHaveBeenCalledTimes(1);
});
it("第一帧前轮询失效取消定位后，下次有效快照仍能完成首次定位", () => {
  const view = render(<Page ready />);
  view.rerender(<Page ready={false} />);
  flush();
  expect(scroll).not.toHaveBeenCalled();
  view.rerender(<Page ready />);
  flush();
  expect(scroll).toHaveBeenCalledTimes(1);
});
