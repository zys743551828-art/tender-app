import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useResource } from "./useResource";

it("all callers awaiting an existing reload wait for its snapshot without another GET", async () => {
  let finish!: (response: Response) => void;
  const response = new Promise<Response>((resolve) => {
    finish = resolve;
  });
  const fetcher = vi.fn(() => response);
  vi.stubGlobal("fetch", fetcher);
  const { result } = renderHook(() =>
    useResource<{ bid_id: string }>("/bids/bid/lifecycle"),
  );
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  let completed = 0;
  const first = result.current.reload().then(() => {
    completed++;
  });
  const second = result.current.reload().then(() => {
    completed++;
  });
  await act(async () => {
    await Promise.resolve();
  });
  expect(completed).toBe(0);
  expect(result.current.loading).toBe(true);
  expect(result.current.data).toBeUndefined();
  await act(async () => {
    finish(
      new Response(JSON.stringify({ bid_id: "bid" }), {
        headers: { ETag: '"snapshot-1"' },
      }),
    );
    await Promise.all([first, second]);
  });
  expect(completed).toBe(2);
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(result.current.loading).toBe(false);
  expect(result.current.data).toEqual({ bid_id: "bid" });
  expect(result.current.etag).toBe('"snapshot-1"');
});

it("fresh reload replaces a pre-write read and ignores its late older snapshot", async () => {
  let finishOld!: (response: Response) => void;
  const old = new Promise<Response>((resolve) => {
    finishOld = resolve;
  });
  const response = (revision: number) =>
    new Response(JSON.stringify({ revision }), {
      headers: { ETag: '"snapshot-' + revision + '"' },
    });
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(response(1))
    .mockReturnValueOnce(old)
    .mockResolvedValueOnce(response(3));
  vi.stubGlobal("fetch", fetcher);
  const { result } = renderHook(() =>
    useResource<{ revision: number }>("/bids/bid/lifecycle"),
  );
  await waitFor(() => expect(result.current.data?.revision).toBe(1));
  let pending!: Promise<void>;
  act(() => {
    pending = result.current.reload();
  });
  expect(result.current.loading).toBe(true);
  await act(async () => {
    await result.current.reloadFresh();
  });
  expect(fetcher).toHaveBeenCalledTimes(3);
  expect(result.current.data?.revision).toBe(3);
  await act(async () => {
    finishOld(response(2));
    await pending;
  });
  expect(result.current.data?.revision).toBe(3);
  expect(result.current.etag).toBe('"snapshot-3"');
  expect(result.current.loading).toBe(false);
});

it.each(["old-error", "fresh-error"])(
  "keeps the fresh outcome when %s overlaps another read",
  async (kind) => {
    let finishOld!: (response: Response) => void;
    let failOld!: (error: Error) => void;
    const old = new Promise<Response>((resolve, reject) => {
      finishOld = resolve;
      failOld = reject;
    });
    const response = (revision: number) =>
      new Response(JSON.stringify({ revision }), {
        headers: { ETag: '"snapshot-' + revision + '"' },
      });
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(response(1))
      .mockReturnValueOnce(old);
    if (kind === "fresh-error")
      fetcher.mockRejectedValueOnce(new Error("new read unavailable"));
    else fetcher.mockResolvedValueOnce(response(3));
    vi.stubGlobal("fetch", fetcher);
    const { result } = renderHook(() =>
      useResource<{ revision: number }>("/bids/bid/lifecycle"),
    );
    await waitFor(() => expect(result.current.data?.revision).toBe(1));
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.reload();
    });
    await act(async () => {
      await result.current.reloadFresh();
    });
    expect(result.current.data?.revision).toBe(kind === "fresh-error" ? 1 : 3);
    if (kind === "fresh-error") expect(result.current.error).toBeTruthy();
    await act(async () => {
      if (kind === "old-error") failOld(new Error("old read unavailable"));
      else finishOld(response(2));
      await pending;
    });
    expect(result.current.loading).toBe(false);
    expect(result.current.data?.revision).toBe(kind === "fresh-error" ? 1 : 3);
    if (kind === "fresh-error") expect(result.current.error).toBeTruthy();
    else expect(result.current.error).toBeUndefined();
  },
);
