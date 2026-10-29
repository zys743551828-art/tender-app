import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, ApiError, type ApiResult } from "./api";
import type { TemplateRequest } from "./contracts";
import { clearRecordedCommands } from "./recordedCommandStorage";
import { taskPackageCommandFixture } from "./taskPackageFixtures.test-support";
import {
  taskPackageStorageKey,
  useTaskPackageCommand,
} from "./useTaskPackageCommand";

vi.mock("./api", async () => ({
  ...(await vi.importActual<typeof import("./api")>("./api")),
  api: vi.fn(),
}));
const mockApi = vi.mocked(api);
const other = "00000000-0000-4000-8000-000000000999";
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((accept) => {
    resolve = accept;
  });
  return { promise, resolve };
}
beforeEach(() => {
  sessionStorage.clear();
  mockApi.mockReset();
});
afterEach(() => vi.restoreAllMocks());

it("durably records key, body, ETag and complete expectation before the first request, clearing only a fully validated ACK", async () => {
  const { f, createScope, create } = taskPackageCommandFixture();
  const storageKey = taskPackageStorageKey(createScope);
  mockApi.mockImplementation(async (path, options) => {
    const saved = JSON.parse(sessionStorage.getItem(storageKey)!);
    expect(saved).toMatchObject({
      version: 1,
      scope: createScope,
      state: "pending",
      pending: { ...create, key: options?.key },
    });
    expect(path).toBe(create.path);
    expect(options).toEqual({
      method: create.method,
      body: create.body,
      etag: create.etag,
      key: saved.pending.key,
    });
    return { data: f.created.data, etag: f.created.headers.etag };
  });
  const hook = renderHook(() => useTaskPackageCommand(createScope));
  let result: unknown;
  await act(async () => {
    result = await hook.result.current.run(create);
  });
  expect(result).toEqual({
    data: f.created.data,
    etag: f.created.headers.etag,
  });
  expect(hook.result.current.pending).toBeNull();
  expect(sessionStorage.getItem(storageKey)).toBeNull();
});

it("keeps the original queued ACK and does not substitute a GET or a newer template during retry", async () => {
  const { f, runScope, run } = taskPackageCommandFixture();
  mockApi.mockRejectedValueOnce(
    new ApiError("lost", 0, "NETWORK_ERROR", undefined, true),
  );
  const first = renderHook(() => useTaskPackageCommand(runScope));
  await act(async () => {
    await first.result.current.run(run);
  });
  const original = mockApi.mock.calls[0];
  const saved = sessionStorage.getItem(taskPackageStorageKey(runScope));
  first.unmount();
  const restored = renderHook(() => useTaskPackageCommand(runScope));
  await waitFor(() => expect(restored.result.current.busy).toBe(false));
  expect(restored.result.current.pending?.expected).toEqual(run.expected);
  mockApi.mockResolvedValueOnce({ data: f.replay.data, etag: null });
  let result: unknown;
  await act(async () => {
    result = await restored.result.current.retry();
  });
  expect(saved).not.toBeNull();
  expect(mockApi.mock.calls[1]).toEqual(original);
  expect(result).toMatchObject({
    data: {
      state: "queued",
      result: null,
      definition_version_id: f.created.data.version_id,
    },
  });
  expect(mockApi).toHaveBeenCalledTimes(2);
  expect(sessionStorage.getItem(taskPackageStorageKey(runScope))).toBeNull();
});

it.each([0, 401, 403, 408, 429, 500, 503])(
  "retains the same original key after HTTP/network status %i",
  async (status) => {
    const { f, createScope, create } = taskPackageCommandFixture();
    mockApi.mockRejectedValueOnce(
      new ApiError("uncertain", status, "REQUEST_FAILED"),
    );
    const hook = renderHook(() => useTaskPackageCommand(createScope));
    await act(async () => {
      await hook.result.current.run(create);
    });
    const key = hook.result.current.pending?.key;
    expect(key).toBeTruthy();
    expect(hook.result.current.rejected).toBe(false);
    expect(hook.result.current.conflict).toBe(false);
    mockApi.mockResolvedValueOnce({
      data: f.created.data,
      etag: f.created.headers.etag,
    });
    await act(async () => {
      await hook.result.current.retry();
    });
    expect(mockApi.mock.calls[1][1]?.key).toBe(key);
    expect(mockApi.mock.calls[1]).toEqual(mockApi.mock.calls[0]);
    expect(hook.result.current.pending).toBeNull();
  },
);

it.each(["missing", "digest", "etag", "cross-project", "formal"])(
  "retains original pending request after an invalid %s ACK",
  async (variant) => {
    const { f, createScope, create } = taskPackageCommandFixture();
    const data = structuredClone(f.created.data);
    if (variant === "digest") data.digest = "0".repeat(64);
    if (variant === "cross-project") data.bid_id = other;
    const value =
      variant === "formal"
        ? { ...data, run_created: true }
        : variant === "missing"
          ? undefined
          : data;
    mockApi.mockResolvedValueOnce({
      data: value,
      etag: variant === "etag" ? null : f.created.headers.etag,
    });
    const hook = renderHook(() => useTaskPackageCommand(createScope));
    await act(async () => {
      expect(await hook.result.current.run(create)).toBeNull();
    });
    expect(hook.result.current.pending?.body).toEqual(create.body);
    expect(hook.result.current.error).toBeInstanceOf(Error);
    expect(hook.result.current.rejected).toBe(false);
    const original = mockApi.mock.calls[0];
    mockApi.mockResolvedValueOnce({
      data: f.created.data,
      etag: f.created.headers.etag,
    });
    await act(async () => {
      await hook.result.current.retry();
    });
    expect(mockApi.mock.calls[1]).toEqual(original);
  },
);

it("checks run input and fee digests before resolving its caller or deleting recovery", async () => {
  const { f, runScope, run } = taskPackageCommandFixture();
  const data = structuredClone(f.queued.data);
  data.frozen_manifest.fee_scope = "0".repeat(64);
  mockApi.mockResolvedValueOnce({ data, etag: null });
  const hook = renderHook(() => useTaskPackageCommand(runScope));
  await act(async () => {
    expect(await hook.result.current.run(run)).toBeNull();
  });
  expect(hook.result.current.pending).not.toBeNull();
  expect(
    sessionStorage.getItem(taskPackageStorageKey(runScope)),
  ).not.toBeNull();
});

it("preserves both incomplete command and idempotency conflict responses for original-request recovery", async () => {
  const { createScope, create } = taskPackageCommandFixture();
  const hook = renderHook(() => useTaskPackageCommand(createScope));
  mockApi.mockRejectedValueOnce(
    new ApiError("pending", 409, "COMMAND_INCOMPLETE"),
  );
  await act(async () => {
    await hook.result.current.run(create);
  });
  const key = hook.result.current.pending?.key;
  mockApi.mockRejectedValueOnce(
    new ApiError("conflict", 409, "IDEMPOTENCY_CONFLICT"),
  );
  await act(async () => {
    await hook.result.current.retry();
  });
  expect(hook.result.current.pending?.key).toBe(key);
  expect(hook.result.current.rejected).toBe(false);
});

it("clears a definite business rejection while retaining the caller's editable request", async () => {
  const { runScope, run } = taskPackageCommandFixture();
  const input = structuredClone(run);
  mockApi.mockRejectedValueOnce(
    new ApiError("paused", 409, "TASK_TEMPLATE_PAUSED"),
  );
  const hook = renderHook(() => useTaskPackageCommand(runScope));
  await act(async () => {
    await hook.result.current.run(input);
  });
  expect(hook.result.current.pending).toBeNull();
  expect(hook.result.current.rejected).toBe(true);
  expect(hook.result.current.conflict).toBe(false);
  expect(input).toEqual(run);
  expect(sessionStorage.getItem(taskPackageStorageKey(runScope))).toBeNull();
});

it("persists a 412 conflict across remount and only adopts a new basis after its own fresh, identity-checked GET", async () => {
  const { f, reviseScope, revise } = taskPackageCommandFixture();
  mockApi.mockRejectedValueOnce(
    new ApiError("stale", 412, "REVISION_CONFLICT"),
  );
  const first = renderHook(() => useTaskPackageCommand(reviseScope));
  await act(async () => {
    await first.result.current.run(revise);
  });
  expect(first.result.current.pending).toBeNull();
  expect(first.result.current.conflict).toBe(true);
  act(() => first.result.current.clearError());
  expect(first.result.current.conflict).toBe(true);
  await act(async () => {
    await first.result.current.run(revise);
  });
  expect(mockApi).toHaveBeenCalledTimes(1);
  const key = taskPackageStorageKey(reviseScope);
  expect(JSON.parse(sessionStorage.getItem(key)!)).toMatchObject({
    state: "conflict",
    pending: { body: revise.body, etag: revise.etag },
  });
  first.unmount();
  const restored = renderHook(() => useTaskPackageCommand(reviseScope));
  await waitFor(() => expect(restored.result.current.busy).toBe(false));
  expect(restored.result.current.conflict).toBe(true);
  mockApi.mockResolvedValueOnce({
    data: { ...f.revised.data, id: other },
    etag: f.revised.headers.etag,
  });
  await act(async () => {
    expect(await restored.result.current.adoptBasis()).toBeNull();
  });
  expect(restored.result.current.conflict).toBe(true);
  expect(sessionStorage.getItem(key)).not.toBeNull();
  mockApi.mockResolvedValueOnce({
    data: f.revised.data,
    etag: f.revised.headers.etag,
  });
  let basis: unknown;
  await act(async () => {
    basis = await restored.result.current.adoptBasis();
  });
  expect(mockApi.mock.calls.at(-1)).toEqual([
    `/bids/${reviseScope.bidId}/task-definitions/${reviseScope.identity}`,
  ]);
  expect(basis).toEqual({ data: f.revised.data, etag: f.revised.headers.etag });
  expect(restored.result.current.conflict).toBe(false);
  expect(sessionStorage.getItem(key)).toBeNull();
});

it("fresh creation basis reads only its scoped bid and refuses missing or mismatched ETags", async () => {
  const { createScope } = taskPackageCommandFixture();
  const hook = renderHook(() => useTaskPackageCommand(createScope));
  mockApi.mockResolvedValueOnce({
    data: { id: createScope.bidId, revision: 4 },
    etag: `"bid:${other}:${"0".repeat(64)}"`,
  });
  await act(async () => {
    expect(await hook.result.current.adoptBasis()).toBeNull();
  });
  const tag = `"bid:${createScope.bidId}:${"0".repeat(64)}"`;
  mockApi.mockResolvedValueOnce({
    data: { id: createScope.bidId, revision: 4 },
    etag: tag,
  });
  await act(async () => {
    expect(await hook.result.current.adoptBasis()).toMatchObject({ etag: tag });
  });
  expect(mockApi.mock.calls[1]).toEqual([`/bids/${createScope.bidId}`]);
});

it.each([
  "not-json",
  "foreign-scope",
  "extra-field",
  "wrong-reference",
  "state-array",
  "too-large",
])(
  "blocks corrupted %s recovery without overwriting it or sending a new request",
  async (variant) => {
    const { createScope, create, pendingCreate } = taskPackageCommandFixture();
    const record = {
      version: 1,
      scope: createScope,
      state: "pending",
      pending: pendingCreate,
    };
    let raw: string;
    if (variant === "not-json") raw = "{damaged";
    else if (variant === "foreign-scope")
      raw = JSON.stringify({
        ...record,
        scope: { ...createScope, memberId: other },
      });
    else if (variant === "extra-field")
      raw = JSON.stringify({ ...record, trusted: true });
    else if (variant === "state-array")
      raw = JSON.stringify({ ...record, state: ["pending"] });
    else if (variant === "wrong-reference")
      raw = JSON.stringify({
        ...record,
        pending: { ...pendingCreate, path: `/bids/${other}/task-definitions` },
      });
    else raw = " ".repeat(256 * 1024 + 1);
    const key = taskPackageStorageKey(createScope);
    sessionStorage.setItem(key, raw);
    const hook = renderHook(() => useTaskPackageCommand(createScope));
    expect(hook.result.current.blocked).toBe(true);
    await act(async () => {
      await hook.result.current.run(create);
      await hook.result.current.retry();
      await hook.result.current.adoptBasis();
    });
    expect(mockApi).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(key)).toBe(raw);
  },
);

it("checks saved expectation digests on remount before allowing recovery", async () => {
  const { runScope, run, pendingRun } = taskPackageCommandFixture();
  const corrupted = structuredClone(pendingRun);
  if (corrupted.expected.kind !== "run") throw new Error("fixture");
  corrupted.expected.template.digest = "0".repeat(64);
  sessionStorage.setItem(
    taskPackageStorageKey(runScope),
    JSON.stringify({
      version: 1,
      scope: runScope,
      state: "pending",
      pending: corrupted,
    }),
  );
  const hook = renderHook(() => useTaskPackageCommand(runScope));
  await waitFor(() => expect(hook.result.current.blocked).toBe(true));
  await act(async () => {
    await hook.result.current.retry();
    await hook.result.current.run(run);
  });
  expect(mockApi).not.toHaveBeenCalled();
  expect(
    sessionStorage.getItem(taskPackageStorageKey(runScope)),
  ).not.toBeNull();
});

it("does not send when durable storage fails", async () => {
  const { createScope, create } = taskPackageCommandFixture();
  const hook = renderHook(() => useTaskPackageCommand(createScope));
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new DOMException("full", "QuotaExceededError");
  });
  await act(async () => {
    expect(await hook.result.current.run(create)).toBeNull();
  });
  expect(mockApi).not.toHaveBeenCalled();
  expect(hook.result.current.error).toBeInstanceOf(Error);
});

it("retains an already validated ACK for replay when recovery deletion fails", async () => {
  const { f, createScope, create } = taskPackageCommandFixture();
  const hook = renderHook(() => useTaskPackageCommand(createScope));
  const remove = vi
    .spyOn(Storage.prototype, "removeItem")
    .mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
  mockApi.mockResolvedValue({
    data: f.created.data,
    etag: f.created.headers.etag,
  });
  await act(async () => {
    expect(await hook.result.current.run(create)).toBeNull();
  });
  const key = hook.result.current.pending?.key;
  expect(key).toBeTruthy();
  remove.mockRestore();
  await act(async () => {
    await hook.result.current.retry();
  });
  expect(mockApi.mock.calls[1][1]?.key).toBe(key);
  expect(hook.result.current.pending).toBeNull();
});

it("copies the complete request before awaiting and never retries mutable UI pending objects", async () => {
  const { f, createScope, create } = taskPackageCommandFixture();
  const original = structuredClone(create);
  const hook = renderHook(() => useTaskPackageCommand(createScope));
  mockApi.mockRejectedValueOnce(new ApiError("lost", 0, "NETWORK_ERROR"));
  await act(async () => {
    const sending = hook.result.current.run(create);
    (create.body as TemplateRequest).name = "Edited while saving";
    await sending;
  });
  expect(mockApi.mock.calls[0][1]?.body).toEqual(original.body);
  (hook.result.current.pending!.body as TemplateRequest).name =
    "Do not send this mutable display copy";
  mockApi.mockResolvedValueOnce({
    data: f.created.data,
    etag: f.created.headers.etag,
  });
  await act(async () => {
    await hook.result.current.retry();
  });
  expect(mockApi.mock.calls[1]).toEqual(mockApi.mock.calls[0]);
});

it.each(["unmount", "scope", "logout"])(
  "ignores a late ACK after %s without clearing another scope or resurrecting storage",
  async (action) => {
    const { f, createScope, create } = taskPackageCommandFixture();
    const response = deferred<ApiResult<unknown>>();
    mockApi.mockReturnValueOnce(response.promise);
    const hook = renderHook(({ scope }) => useTaskPackageCommand(scope), {
      initialProps: { scope: createScope },
    });
    let request!: ReturnType<typeof hook.result.current.run>;
    act(() => {
      request = hook.result.current.run(create);
    });
    await waitFor(() => expect(mockApi).toHaveBeenCalledTimes(1));
    const key = taskPackageStorageKey(createScope),
      original = sessionStorage.getItem(key);
    if (action === "unmount") hook.unmount();
    if (action === "scope")
      hook.rerender({ scope: { ...createScope, bidId: other } });
    if (action === "logout") clearRecordedCommands();
    await act(async () => {
      response.resolve({ data: f.created.data, etag: f.created.headers.etag });
      expect(await request).toBeNull();
    });
    expect(sessionStorage.getItem(key)).toBe(
      action === "logout" ? null : original,
    );
    if (action === "scope") {
      expect(hook.result.current.pending).toBeNull();
      expect(
        sessionStorage.getItem(
          taskPackageStorageKey({ ...createScope, bidId: other }),
        ),
      ).toBeNull();
    }
  },
);

it("rechecks scope and storage after asynchronous ACK hashing completes", async () => {
  const { f, runScope, run } = taskPackageCommandFixture();
  const release = deferred<void>();
  const nativeDigest = crypto.subtle.digest.bind(crypto.subtle);
  let ack = false,
    pausedHashes = 0;
  vi.spyOn(crypto.subtle, "digest").mockImplementation(
    async (algorithm, data) => {
      if (ack) {
        ++pausedHashes;
        await release.promise;
      }
      return nativeDigest(algorithm, data);
    },
  );
  mockApi.mockImplementation(async () => {
    ack = true;
    return { data: f.queued.data, etag: null };
  });
  const hook = renderHook(() => useTaskPackageCommand(runScope));
  let request!: ReturnType<typeof hook.result.current.run>;
  act(() => {
    request = hook.result.current.run(run);
  });
  await waitFor(() => expect(pausedHashes).toBeGreaterThan(0));
  clearRecordedCommands();
  await act(async () => {
    release.resolve();
    expect(await request).toBeNull();
  });
  expect(sessionStorage.getItem(taskPackageStorageKey(runScope))).toBeNull();
  expect(hook.result.current.blocked).toBe(true);
});

it("never sends after logout removes the original record during asynchronous request verification", async () => {
  const { runScope, run } = taskPackageCommandFixture();
  const hook = renderHook(() => useTaskPackageCommand(runScope));
  await act(async () => {
    const request = hook.result.current.run(run);
    expect(
      sessionStorage.getItem(taskPackageStorageKey(runScope)),
    ).not.toBeNull();
    clearRecordedCommands();
    expect(await request).toBeNull();
  });
  expect(mockApi).not.toHaveBeenCalled();
  expect(sessionStorage.getItem(taskPackageStorageKey(runScope))).toBeNull();
});

it("does not overwrite a replacement record or submit concurrent new clicks", async () => {
  const { f, createScope, create } = taskPackageCommandFixture();
  const response = deferred<ApiResult<unknown>>();
  mockApi.mockReturnValueOnce(response.promise);
  const hook = renderHook(() => useTaskPackageCommand(createScope));
  let request!: ReturnType<typeof hook.result.current.run>;
  act(() => {
    request = hook.result.current.run(create);
  });
  await waitFor(() => expect(mockApi).toHaveBeenCalledTimes(1));
  await act(async () => {
    expect(await hook.result.current.run(create)).toBeNull();
    expect(await hook.result.current.retry()).toBeNull();
  });
  const key = taskPackageStorageKey(createScope);
  const replacement = sessionStorage
    .getItem(key)!
    .replace('"state":"pending"', '"state":"conflict"');
  sessionStorage.setItem(key, replacement);
  await act(async () => {
    response.resolve({ data: f.created.data, etag: f.created.headers.etag });
    expect(await request).toBeNull();
  });
  expect(mockApi).toHaveBeenCalledTimes(1);
  expect(sessionStorage.getItem(key)).toBe(replacement);
});

it("registers both task package command kinds for same-member retention and logout/account cleanup, even when damaged", () => {
  const { createScope, runScope } = taskPackageCommandFixture();
  const own = [
    taskPackageStorageKey(createScope),
    taskPackageStorageKey(runScope),
  ];
  const foreign = [
    taskPackageStorageKey({ ...createScope, memberId: other }),
    taskPackageStorageKey({ ...runScope, memberId: other }),
  ];
  for (const key of [...own, ...foreign])
    sessionStorage.setItem(key, "{damaged");
  clearRecordedCommands(createScope.memberId);
  for (const key of own) expect(sessionStorage.getItem(key)).toBe("{damaged");
  for (const key of foreign) expect(sessionStorage.getItem(key)).toBeNull();
  clearRecordedCommands();
  for (const key of own) expect(sessionStorage.getItem(key)).toBeNull();
});
