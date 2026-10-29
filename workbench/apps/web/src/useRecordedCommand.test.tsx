import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import type { ApiResult } from "./api";
import { useRecordedCommand } from "./useRecordedCommand";

const path = "/bids/bid/pricing-formulas";
const reply = (scope: string) =>
  new Response(JSON.stringify({ scope }), {
    headers: { ETag: '"acknowledgement"' },
  });
const recordKey = (scope: string) => `tender:command-record:${scope}`;

beforeEach(() => {
  sessionStorage.clear();
  vi.restoreAllMocks();
});

it.each([
  new Error("Acknowledgement identity mismatch"),
  new ApiError("Acknowledgement identity mismatch", 422, "BAD_ACK"),
])(
  "keeps the original request when validation rejects a received acknowledgement: %s",
  async (failure) => {
    const requests: {
      body: string;
      key: string | null;
      etag: string | null;
    }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        const headers = new Headers(init?.headers);
        requests.push({
          body: String(init?.body),
          key: headers.get("Idempotency-Key"),
          etag: headers.get("If-Match"),
        });
        return reply(requests.length === 1 ? "wrong" : "original");
      }),
    );
    const validate = vi.fn(({ data }: ApiResult<unknown>) => {
      if ((data as { scope: string }).scope !== "original") throw failure;
    });
    const { result } = renderHook(() =>
      useRecordedCommand("original", validate),
    );
    let received: ApiResult<unknown> | null = null;
    await act(async () => {
      received = await result.current.run(
        path,
        { immutable: "body" },
        '"basis"',
      );
    });
    expect(received).toBeNull();
    expect(result.current.error).toBe(failure);
    expect(result.current.pending).not.toBeNull();
    expect(sessionStorage.getItem(recordKey("original"))).not.toBeNull();
    expect(sessionStorage.getItem("tender:command:original")).not.toBeNull();
    await act(async () => {
      received = await result.current.retry();
    });
    expect(received).toMatchObject({ data: { scope: "original" } });
    expect(validate).toHaveBeenCalledTimes(2);
    expect(requests).toHaveLength(2);
    expect(requests[1]).toEqual(requests[0]);
    expect(result.current.pending).toBeNull();
    expect(sessionStorage.getItem(recordKey("original"))).toBeNull();
  },
);

it("isolates a changed hook scope while requests are pending and restores the first request on return", async () => {
  const releases: ((response: Response) => void)[] = [];
  const requests: { body: string; key: string | null; etag: string | null }[] =
    [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init?: RequestInit) => {
      const headers = new Headers(init?.headers);
      requests.push({
        body: String(init?.body),
        key: headers.get("Idempotency-Key"),
        etag: headers.get("If-Match"),
      });
      if (requests.length <= 2)
        return new Promise<Response>((resolve) => releases.push(resolve));
      return reply("first");
    }),
  );
  const { result, rerender } = renderHook(
    ({ scope }) => useRecordedCommand(scope),
    { initialProps: { scope: "first" } },
  );
  let first!: Promise<ApiResult<unknown> | null>;
  act(() => {
    first = result.current.run(path, { scope: "first" }, '"first-basis"');
  });
  rerender({ scope: "second" });
  expect(result.current.pending).toBeNull();
  expect(result.current.busy).toBe(false);
  let second!: Promise<ApiResult<unknown> | null>;
  act(() => {
    second = result.current.run(path, { scope: "second" }, '"second-basis"');
  });
  await act(async () => {
    releases[0](reply("first"));
    expect(await first).toBeNull();
  });
  expect(result.current.pending?.body).toEqual({ scope: "second" });
  expect(result.current.busy).toBe(true);
  expect(sessionStorage.getItem(recordKey("first"))).not.toBeNull();
  await act(async () => {
    releases[1](reply("second"));
    expect(await second).toMatchObject({ data: { scope: "second" } });
  });
  expect(sessionStorage.getItem(recordKey("second"))).toBeNull();
  rerender({ scope: "first" });
  expect(result.current.pending?.body).toEqual({ scope: "first" });
  await act(async () => {
    expect(await result.current.retry()).toMatchObject({
      data: { scope: "first" },
    });
  });
  expect(requests).toHaveLength(3);
  expect(requests[2]).toEqual(requests[0]);
  expect(result.current.pending).toBeNull();
});

it("retains a received acknowledgement if the scope changes during asynchronous validation", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => reply("first")),
  );
  let finishValidation!: () => void;
  const validation = vi.fn(
    () =>
      new Promise<void>((resolve) => {
        finishValidation = resolve;
      }),
  );
  const { result, rerender } = renderHook(
    ({ scope }) => useRecordedCommand(scope, validation),
    { initialProps: { scope: "first" } },
  );
  let pending!: Promise<ApiResult<unknown> | null>;
  await act(async () => {
    pending = result.current.run(path, { scope: "first" }, '"first-basis"');
  });
  expect(validation).toHaveBeenCalledOnce();
  rerender({ scope: "second" });
  await act(async () => {
    finishValidation();
    expect(await pending).toBeNull();
  });
  expect(result.current.pending).toBeNull();
  expect(sessionStorage.getItem(recordKey("first"))).not.toBeNull();
  rerender({ scope: "first" });
  expect(result.current.pending?.body).toEqual({ scope: "first" });
});
