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
