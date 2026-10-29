import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useSaveQueue } from "./useSaveQueue";

it("保存串行且等待期间的新编辑继续排队，首个ACK不能把后续输入显示成已保存", async () => {
  const acknowledgments: (() => void)[] = [];
  const save = vi.fn<(text: string) => Promise<void>>(
    () => new Promise<void>((resolve) => acknowledgments.push(resolve)),
  );
  const { result } = renderHook(() => useSaveQueue(save, 60000));
  act(() => result.current.change("本地第一稿"));
  let complete: Promise<boolean>;
  act(() => {
    complete = result.current.flush();
  });
  expect(save).toHaveBeenCalledTimes(1);
  act(() => result.current.change("保存中的第二稿"));
  expect(result.current.phase).toBe("saving");
  await act(async () => {
    acknowledgments[0]();
  });
  expect(save.mock.calls.map(([text]) => text)).toEqual([
    "本地第一稿",
    "保存中的第二稿",
  ]);
  expect(result.current.phase).toBe("saving");
  expect(result.current.isDirty()).toBe(true);
  await act(async () => {
    acknowledgments[1]();
    expect(await complete!).toBe(true);
  });
  expect(result.current.phase).toBe("saved");
  expect(result.current.isDirty()).toBe(false);
});
it("失败后的新输入保留，明确重试先重放失败快照，再保存最新文本", async () => {
  const save = vi
    .fn<(value: string) => Promise<void>>()
    .mockRejectedValueOnce(new Error("响应丢失"))
    .mockResolvedValue(undefined);
  const { result } = renderHook(() => useSaveQueue(save, 60000));
  act(() => result.current.change("失败命令正文"));
  await act(async () => {
    expect(await result.current.flush()).toBe(false);
  });
  act(() => result.current.change("后来继续编辑"));
  expect(result.current.phase).toBe("failed");
  expect(save).toHaveBeenCalledTimes(1);
  await act(async () => {
    expect(await result.current.flush()).toBe(true);
  });
  expect(save.mock.calls.map(([text]) => text)).toEqual([
    "失败命令正文",
    "失败命令正文",
    "后来继续编辑",
  ]);
  expect(result.current.phase).toBe("saved");
});
it("自动保存防抖后仍需服务端ACK，生成或导航等待同一在途保存", async () => {
  let acknowledge: (() => void) | undefined;
  const save = vi.fn(
    () =>
      new Promise<void>((resolve) => {
        acknowledge = resolve;
      }),
  );
  const { result } = renderHook(() => useSaveQueue(save, 20));
  act(() => result.current.change("未确认内容"));
  await waitFor(() => expect(result.current.phase).toBe("saving"));
  const beforeBuild = result.current.flush();
  const beforeNavigate = result.current.flush();
  expect(beforeBuild).toBe(beforeNavigate);
  expect(save).toHaveBeenCalledTimes(1);
  await act(async () => {
    acknowledge!();
    expect(await beforeBuild).toBe(true);
  });
  expect(result.current.isDirty()).toBe(false);
});
it("服务器明确拒绝的内容修正后保存新输入，离开页面的迟到输入不会重新排队", async () => {
  const rejected = new Error("校验未通过");
  const save = vi
    .fn<(value: string) => Promise<void>>()
    .mockRejectedValueOnce(rejected)
    .mockResolvedValue(undefined);
  const { result, unmount } = renderHook(() =>
    useSaveQueue(save, 60000, (error) => error !== rejected),
  );
  act(() => result.current.change("不合法的字段"));
  await act(async () => {
    expect(await result.current.flush()).toBe(false);
  });
  act(() => result.current.change("已修正的字段"));
  await act(async () => {
    expect(await result.current.flush()).toBe(true);
  });
  expect(save.mock.calls.map(([text]) => text)).toEqual([
    "不合法的字段",
    "已修正的字段",
  ]);
  const lateChange = result.current.change;
  const flush = result.current.flush;
  unmount();
  lateChange("来源请求的迟到响应");
  expect(await flush()).toBe(true);
  expect(save).toHaveBeenCalledTimes(2);
});
