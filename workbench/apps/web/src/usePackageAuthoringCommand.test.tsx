import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";
import { packageAuthoringCommandFixture } from "./packageAuthoringFixtures.test-support";
import {
  taskPackageStorageKey,
  useTaskPackageCommand,
} from "./useTaskPackageCommand";
import { clearRecordedCommands } from "./recordedCommandStorage";

vi.mock("./api", async () => ({
  ...(await vi.importActual<typeof import("./api")>("./api")),
  api: vi.fn(),
}));
const mockApi = vi.mocked(api),
  other = "00000000-0000-4000-8000-000000009999";
beforeEach(() => {
  sessionStorage.clear();
  mockApi.mockReset();
});
it("persists the complete fixed authoring command before transport and clears only its verified ACK", async () => {
  const { f, create, createScope } = packageAuthoringCommandFixture(),
    key = taskPackageStorageKey(createScope);
  mockApi.mockImplementation(async (path, options) => {
    const record = JSON.parse(sessionStorage.getItem(key)!);
    expect(record.pending).toEqual({ ...create, key: options?.key });
    expect(path).toBe(create.path);
    expect(record.scope).toEqual(createScope);
    return { data: f.template, etag: f.template_etag };
  });
  const hook = renderHook(() => useTaskPackageCommand(createScope));
  await act(async () => {
    await hook.result.current.run(create);
  });
  expect(sessionStorage.getItem(key)).toBeNull();
  expect(hook.result.current.pending).toBeNull();
});
it("replays the exact original authoring run and queued ACK after a lost response without any replacement GET", async () => {
  const { f, run, runScope } = packageAuthoringCommandFixture();
  mockApi.mockRejectedValueOnce(
    new ApiError("lost", 0, "NETWORK_ERROR", undefined, true),
  );
  const first = renderHook(() => useTaskPackageCommand(runScope));
  await act(async () => {
    await first.result.current.run(run);
  });
  const original = mockApi.mock.calls[0];
  first.unmount();
  const restored = renderHook(() => useTaskPackageCommand(runScope));
  await waitFor(() => expect(restored.result.current.busy).toBe(false));
  mockApi.mockResolvedValueOnce({ data: f.runs.queued, etag: null });
  let accepted;
  await act(async () => {
    accepted = await restored.result.current.retry();
  });
  expect(accepted).toEqual({ data: f.runs.queued, etag: null });
  expect(mockApi.mock.calls[1]).toEqual(original);
  expect(mockApi).toHaveBeenCalledTimes(2);
});
it.each(["section", "instructions", "digest", "boundary"])(
  "retains the original request after an incorrect template %s acknowledgement",
  async (field) => {
    const { f, create, createScope } = packageAuthoringCommandFixture(),
      response = structuredClone(f.template);
    if (field === "section") response.configuration.section_id = other;
    if (field === "instructions")
      response.configuration.instructions += " changed";
    if (field === "digest") response.digest = "f".repeat(64);
    if (field === "boundary") Object.assign(response, { run_created: true });
    mockApi.mockResolvedValueOnce({ data: response, etag: f.template_etag });
    const hook = renderHook(() => useTaskPackageCommand(createScope));
    await act(async () => {
      await hook.result.current.run(create);
    });
    expect(hook.result.current.pending?.body).toEqual(create.body);
    expect(
      sessionStorage.getItem(taskPackageStorageKey(createScope)),
    ).not.toBeNull();
  },
);
it("fails closed on a mixed-mode recovered command and never sends it through the legacy task path", async () => {
  const { run, runScope } = packageAuthoringCommandFixture(),
    key = taskPackageStorageKey(runScope);
  sessionStorage.setItem(
    key,
    JSON.stringify({
      version: 1,
      scope: runScope,
      state: "pending",
      pending: {
        ...run,
        expected: { ...run.expected, kind: "run" },
        key: other,
      },
    }),
  );
  const hook = renderHook(() => useTaskPackageCommand(runScope));
  await waitFor(() => expect(hook.result.current.blocked).toBe(true));
  await act(async () => {
    await hook.result.current.retry();
  });
  expect(mockApi).not.toHaveBeenCalled();
  expect(sessionStorage.getItem(key)).not.toBeNull();
});
it("does not accept a late authoring ACK into another member session or recreate account-cleared records", async () => {
  const { f, create, createScope } = packageAuthoringCommandFixture();
  let resolve!: (value: { data: typeof f.template; etag: string }) => void;
  mockApi.mockImplementation(
    () =>
      new Promise((accept) => {
        resolve = accept;
      }),
  );
  const hook = renderHook(
    ({ memberId }) => useTaskPackageCommand({ ...createScope, memberId }),
    { initialProps: { memberId: createScope.memberId } },
  );
  let pending: ReturnType<typeof hook.result.current.run>;
  act(() => {
    pending = hook.result.current.run(create);
  });
  await waitFor(() => expect(mockApi).toHaveBeenCalledTimes(1));
  clearRecordedCommands(other);
  hook.rerender({ memberId: other });
  await act(async () => {
    resolve({ data: f.template, etag: f.template_etag });
    expect(await pending!).toBeNull();
  });
  expect(sessionStorage.getItem(taskPackageStorageKey(createScope))).toBeNull();
  expect(hook.result.current.pending).toBeNull();
});

it.each([
  ["AUTHORING_PACKAGE_ORIGINAL_JOB_REQUIRED", 409, false],
  ["AUTHORING_PACKAGE_ORIGINAL_JOB_REQUIRED", 500, true],
  ["AUTHORING_PACKAGE_ORIGINAL_JOB_REQUIRED", 412, true],
  ["AUTHORING_PACKAGE_BINDING_INVALID", 409, true],
  ["TASK_PACKAGE_BINDING_INVALID", 409, true],
  ["COMMAND_RESULT_INCOMPLETE", 409, true],
] as const)(
  "handles %s at HTTP %s without losing an uncertain original run (retained=%s)",
  async (code, status, retained) => {
    const { run, runScope } = packageAuthoringCommandFixture();
    mockApi.mockRejectedValueOnce(
      new ApiError("synthetic refusal", status, code),
    );
    const hook = renderHook(() => useTaskPackageCommand(runScope));
    await act(async () => {
      await hook.result.current.run(run);
    });
    expect(!!hook.result.current.pending).toBe(retained);
    expect(!!sessionStorage.getItem(taskPackageStorageKey(runScope))).toBe(
      retained,
    );
    expect(mockApi).toHaveBeenCalledTimes(1);
  },
);
