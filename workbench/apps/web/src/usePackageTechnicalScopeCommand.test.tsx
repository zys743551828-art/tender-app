import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";
import {
  technicalAckFor,
  technicalFixture,
} from "./packageTechnicalScopeFixtures.test-support";
import {
  readTechnicalRecovery,
  technicalRecoveryKey,
  writeTechnicalRecovery,
} from "./packageTechnicalScopeRecovery";
import type { TechnicalPending } from "./packageTechnicalScopeProtocol";
import { usePackageTechnicalScopeCommand } from "./usePackageTechnicalScopeCommand";
vi.mock("./api", async (load) => ({
  ...(await load<typeof import("./api")>()),
  api: vi.fn(),
  supportsApi: () => true,
}));
const mocked = vi.mocked(api);
beforeEach(() => {
  sessionStorage.clear();
  mocked.mockReset();
});
const commandOf = (p: TechnicalPending) => ({
  body: p.body,
  etag: p.etag,
  expected: p.expected,
});

it("preserves malformed successful HTTP acknowledgements and recovers exactly across remount", async () => {
  const f = technicalFixture();
  mocked.mockResolvedValueOnce({ data: { scope: f.ack.scope }, etag: f.etag });
  const first = renderHook(() => usePackageTechnicalScopeCommand(f.scope));
  await act(async () => {
    await first.result.current.save(commandOf(f.pending));
  });
  const pending = readTechnicalRecovery(f.scope)!;
  expect(pending.body).toEqual(f.pending.body);
  expect(first.result.current.error).toBeTruthy();
  expect(first.result.current.result).toBeNull();
  first.unmount();
  mocked.mockResolvedValueOnce(await technicalAckFor(pending));
  const second = renderHook(() => usePackageTechnicalScopeCommand(f.scope));
  await act(async () => {
    await second.result.current.retry();
  });
  expect(mocked.mock.calls[1][1]).toEqual(mocked.mock.calls[0][1]);
  expect(readTechnicalRecovery(f.scope)).toBeNull();
  expect(second.result.current.result?.digest).toBe(f.ack.scope.digest);
});

it("persists before dispatch and sends a double click only once", async () => {
  const f = technicalFixture();
  let resolve!: (value: Awaited<ReturnType<typeof technicalAckFor>>) => void;
  mocked.mockImplementationOnce(async () => {
    expect(readTechnicalRecovery(f.scope)).not.toBeNull();
    return new Promise((done) => {
      resolve = done;
    });
  });
  const hook = renderHook(() => usePackageTechnicalScopeCommand(f.scope));
  let inFlight!: Promise<unknown>;
  await act(async () => {
    inFlight = hook.result.current.save(commandOf(f.pending));
    await hook.result.current.save(commandOf(f.pending));
  });
  await waitFor(() => expect(mocked).toHaveBeenCalledTimes(1));
  const pending = readTechnicalRecovery(f.scope)!;
  await act(async () => {
    resolve(await technicalAckFor(pending));
    await inFlight;
  });
  expect(hook.result.current.pending).toBeNull();
});

it("does not clear a late acknowledgement after the source component unmounts", async () => {
  const f = technicalFixture();
  let resolve!: (value: Awaited<ReturnType<typeof technicalAckFor>>) => void;
  mocked.mockImplementationOnce(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  const hook = renderHook(() => usePackageTechnicalScopeCommand(f.scope));
  let inFlight!: Promise<unknown>;
  await act(async () => {
    inFlight = hook.result.current.save(commandOf(f.pending));
  });
  await waitFor(() => expect(mocked).toHaveBeenCalledTimes(1));
  const pending = readTechnicalRecovery(f.scope)!;
  hook.unmount();
  resolve(await technicalAckFor(pending));
  await inFlight;
  expect(readTechnicalRecovery(f.scope)).toEqual(pending);
});

it("preserves an auth failure but releases an explicit version rejection", async () => {
  const f = technicalFixture();
  writeTechnicalRecovery(f.scope, f.pending);
  mocked.mockRejectedValueOnce(new ApiError("expired", 401, "SESSION_EXPIRED"));
  const hook = renderHook(() => usePackageTechnicalScopeCommand(f.scope));
  await act(async () => {
    await hook.result.current.retry();
  });
  expect(readTechnicalRecovery(f.scope)).toEqual(f.pending);
  mocked.mockRejectedValueOnce(
    new ApiError("changed", 412, "REVISION_CONFLICT"),
  );
  await act(async () => {
    await hook.result.current.retry();
  });
  expect(readTechnicalRecovery(f.scope)).toBeNull();
});

it("corrupt local recovery prevents a replacement command", async () => {
  const f = technicalFixture();
  sessionStorage.setItem(technicalRecoveryKey(f.scope), "{");
  const hook = renderHook(() => usePackageTechnicalScopeCommand(f.scope));
  await act(async () => {
    await hook.result.current.save(commandOf(f.pending));
  });
  expect(hook.result.current.blocked).toBe(true);
  expect(mocked).not.toHaveBeenCalled();
});
