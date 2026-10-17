import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { changeSequence, eventDecoder } from "./eventStream";
import { useProjectStream } from "./useProjectStream";

const data = {
  stream_id: "stream",
  seq: 7,
  event_type: "state.changed",
  object_ref: { kind: "bid", id: "bid" },
  revision: null,
};
beforeEach(() => {
  sessionStorage.clear();
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});
it("流分帧支持分块、CRLF及多行数据，空revision仍是有效变化；重复和跨项目事件不更新", () => {
  const frames: Parameters<Parameters<typeof eventDecoder>[0]>[0][] = [];
  const decode = eventDecoder((frame) => frames.push(frame));
  decode(": keepalive\r\n\r\nid: stream:7\r\nevent: cha");
  decode(`nge\r\ndata: ${JSON.stringify(data)}\r\n\r`);
  decode("\n");
  expect(frames).toHaveLength(1);
  expect(changeSequence(frames[0], "stream", "bid", 0)).toBe(7);
  expect(changeSequence(frames[0], "stream", "bid", 7)).toBeNull();
  expect(changeSequence(frames[0], "stream", "other", 0)).toBeNull();
  decode('event: control\ndata: {\ndata: "code":"RESET_REQUIRED"}\n\n');
  expect(JSON.parse(frames[1].data)).toEqual({ code: "RESET_REQUIRED" });
});
it("同源Cookie流从最后序号续接，410先刷新清游标，401停止且不清除本地正文", async () => {
  sessionStorage.setItem(
    "tender:authoring:member:bid:draft",
    "尚未确认的本地正文",
  );
  const changed = vi.fn();
  const expired = vi.fn();
  window.addEventListener("server-snapshot-change", changed);
  window.addEventListener("session-expired", expired);
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(
        `id: stream:7\nevent: change\ndata: ${JSON.stringify(data)}\n\n`,
        { headers: { "Content-Type": "text/event-stream" } },
      ),
    )
    .mockResolvedValueOnce(new Response("{}", { status: 410 }))
    .mockResolvedValueOnce(new Response("{}", { status: 401 }));
  vi.stubGlobal("fetch", fetcher);
  const { unmount } = renderHook(() => useProjectStream("stream", "bid"));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(350);
  });
  expect(sessionStorage.getItem("tender:stream:stream")).toBe("7");
  expect(changed).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0][1].credentials).toBe("same-origin");
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  expect(
    new Headers(fetcher.mock.calls[1][1].headers).get("Last-Event-ID"),
  ).toBe("stream:7");
  expect(sessionStorage.getItem("tender:stream:stream")).toBeNull();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  expect(changed).toHaveBeenCalledTimes(2);
  expect(
    new Headers(fetcher.mock.calls[2][1].headers).has("Last-Event-ID"),
  ).toBe(false);
  expect(expired).toHaveBeenCalledTimes(1);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(15000);
  });
  expect(fetcher).toHaveBeenCalledTimes(3);
  expect(sessionStorage.getItem("tender:authoring:member:bid:draft")).toBe(
    "尚未确认的本地正文",
  );
  unmount();
  window.removeEventListener("server-snapshot-change", changed);
  window.removeEventListener("session-expired", expired);
});
