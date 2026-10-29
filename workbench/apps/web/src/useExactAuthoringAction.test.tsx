import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";
import {
  exactAuthoringFixture,
  exactId,
  actionEtag,
} from "./authoringExactFixtures.test-support";
import {
  exactActionStorageKey,
  useExactAuthoringAction,
} from "./useExactAuthoringAction";
import { clearRecordedCommands } from "./recordedCommandStorage";

vi.mock("./api", async () => ({
  ...(await vi.importActual<typeof import("./api")>("./api")),
  api: vi.fn(),
}));
const mocked = vi.mocked(api);
beforeEach(() => {
  sessionStorage.clear();
  mocked.mockReset();
});
it("keeps the original candidate, decision, ETag and key after a lost ACK and replays exactly after remount", async () => {
  const f = await exactAuthoringFixture(),
    scope = { memberId: f.f.member_id, actionId: f.action.action_id };
  mocked.mockRejectedValueOnce(new ApiError("lost", 0, "NETWORK_ERROR"));
  const first = renderHook(() => useExactAuthoringAction(scope));
  await act(async () => {
    await first.result.current.run(f.action, f.etag, "confirm", f.input);
  });
  const original = mocked.mock.calls[0],
    record = sessionStorage.getItem(exactActionStorageKey(scope));
  expect(first.result.current.pending).toBe(true);
  expect(JSON.parse(record!).pending.original).toEqual(f.action);
  first.unmount();
  mocked.mockResolvedValueOnce({ data: f.executed, etag: f.executedEtag });
  const restored = renderHook(() => useExactAuthoringAction(scope));
  await act(async () => {
    await restored.result.current.retry();
  });
  expect(mocked.mock.calls[1]).toEqual(original);
  expect(sessionStorage.getItem(exactActionStorageKey(scope))).toBeNull();
});
it.each(["wrong-ack", "wrong-draft", "unauthorized", "unknown-conflict"])(
  "preserves the original request for %s",
  async (kind) => {
    const f = await exactAuthoringFixture(),
      scope = { memberId: f.f.member_id, actionId: f.action.action_id };
    if (kind === "wrong-ack" || kind === "wrong-draft") {
      const v = structuredClone(f.executed);
      if (kind === "wrong-ack") v.job_id = exactId(99);
      else if (
        v.result &&
        "assistant_resolution" in v.result &&
        v.result.assistant_resolution.domain_result &&
        "draft_id" in v.result.assistant_resolution.domain_result
      )
        v.result.assistant_resolution.domain_result.draft_id = exactId(99);
      else throw new Error("synthetic adoption result missing");
      mocked.mockResolvedValueOnce({ data: v, etag: await actionEtag(v) });
    } else
      mocked.mockRejectedValueOnce(
        new ApiError(
          "uncertain",
          kind === "unauthorized" ? 403 : 409,
          "UNRECOGNIZED",
        ),
      );
    const hook = renderHook(() => useExactAuthoringAction(scope));
    await act(async () => {
      await hook.result.current.run(f.action, f.etag, "confirm", f.input);
    });
    expect(hook.result.current.pending).toBe(true);
    expect(sessionStorage.getItem(exactActionStorageKey(scope))).not.toBeNull();
    await act(async () => {
      await hook.result.current.run(f.action, f.etag, "reject");
    });
    expect(mocked).toHaveBeenCalledTimes(1);
  },
);
it("requires explicit rereading after a CAS conflict without replacing the original record", async () => {
  const f = await exactAuthoringFixture(),
    scope = { memberId: f.f.member_id, actionId: f.action.action_id };
  mocked.mockRejectedValueOnce(
    new ApiError("conflict", 412, "REVISION_CONFLICT"),
  );
  const hook = renderHook(() => useExactAuthoringAction(scope));
  await act(async () => {
    await hook.result.current.run(f.action, f.etag, "confirm", f.input);
  });
  expect(hook.result.current.conflict).toBe(true);
  await act(async () => {
    await hook.result.current.retry();
    await hook.result.current.run(f.action, f.etag, "reject");
  });
  expect(mocked).toHaveBeenCalledTimes(1);
  await act(async () => {
    expect(
      await hook.result.current.acknowledgeConflict(f.executed, f.executedEtag),
    ).toBe(true);
  });
  expect(hook.result.current.conflict).toBe(false);
});
it("does not recreate a cleared record or accept a late ACK after a member switch", async () => {
  const f = await exactAuthoringFixture(),
    scope = { memberId: f.f.member_id, actionId: f.action.action_id };
  let finish!: (r: { data: typeof f.executed; etag: string }) => void;
  mocked.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const hook = renderHook(
    ({ memberId }) => useExactAuthoringAction({ ...scope, memberId }),
    { initialProps: { memberId: scope.memberId } },
  );
  let sending!: Promise<unknown>;
  act(() => {
    sending = hook.result.current.run(f.action, f.etag, "confirm", f.input);
  });
  await waitFor(() => expect(mocked).toHaveBeenCalled());
  clearRecordedCommands();
  hook.rerender({ memberId: exactId(99) });
  await act(async () => {
    finish({ data: f.executed, etag: f.executedEtag });
    await sending;
  });
  expect(sessionStorage.getItem(exactActionStorageKey(scope))).toBeNull();
  expect(hook.result.current.pending).toBe(false);
});
it("recovers the old B2 command record with the same request after upgrading to B3", async () => {
  const f = await exactAuthoringFixture(),
    scope = { memberId: f.f.member_id, actionId: f.action.action_id };
  const key = exactId(99),
    path = `/assistant/actions/${scope.actionId}/resolve`;
  sessionStorage.setItem(
    exactActionStorageKey(scope),
    JSON.stringify({ path, body: { decision: "confirm" }, etag: f.etag, key }),
  );
  mocked
    .mockResolvedValueOnce({ data: f.executed, etag: f.executedEtag })
    .mockResolvedValueOnce({ data: f.executed, etag: f.executedEtag });
  const hook = renderHook(() => useExactAuthoringAction(scope));
  await act(async () => {
    await hook.result.current.retry();
  });
  expect(mocked.mock.calls[1]).toEqual([
    path,
    { method: "POST", body: { decision: "confirm" }, etag: f.etag, key },
  ]);
  expect(sessionStorage.getItem(exactActionStorageKey(scope))).toBeNull();
});
