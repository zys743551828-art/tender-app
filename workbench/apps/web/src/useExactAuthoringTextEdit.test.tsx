import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";
import {
  verifyTextEditBase,
  type ExactTextEditScope,
} from "./authoringExactTextEditProtocol";
import {
  exactTextEditStorageKey,
  useExactAuthoringTextEdit,
} from "./useExactAuthoringTextEdit";
import { clearRecordedCommands } from "./recordedCommandStorage";
import native from "./test-fixtures/authoring-exact-text-edit-http.json";
import type { AuthoringDocument } from "./contracts";

vi.mock("./api", async () => ({
  ...(await vi.importActual<typeof import("./api")>("./api")),
  api: vi.fn(),
}));
const mocked = vi.mocked(api);
const scope: ExactTextEditScope = {
  memberId: native.member_id,
  bidId: native.bid_id,
  draftId: native.parent_status.draft_id,
};
const originalBase = {
  status: native.parent_status,
  section: native.parent_section,
  qualification: native.parent_qualification,
};
beforeEach(() => {
  sessionStorage.clear();
  mocked.mockReset();
});

it("persists before sending and replays the exact original after a lost ACK and remount, with no automatic retry", async () => {
  const base = await verifyTextEditBase(originalBase, scope);
  mocked.mockImplementationOnce(async () => {
    expect(
      sessionStorage.getItem(exactTextEditStorageKey(scope)),
    ).not.toBeNull();
    throw new ApiError("lost", 0, "NETWORK_ERROR");
  });
  const first = renderHook(() => useExactAuthoringTextEdit(scope));
  expect(mocked).not.toHaveBeenCalled();
  await act(async () => {
    await first.result.current.run(base, native.request, native.request_etag);
  });
  expect(first.result.current.pending).toBe(true);
  const original = mocked.mock.calls[0],
    raw = sessionStorage.getItem(exactTextEditStorageKey(scope));
  expect(JSON.parse(raw!).pending.body).toEqual(native.request);
  first.unmount();
  mocked.mockResolvedValueOnce({ data: native.ack, etag: native.ack_etag });
  const restored = renderHook(() => useExactAuthoringTextEdit(scope));
  expect(mocked).toHaveBeenCalledTimes(1);
  await act(async () => {
    await restored.result.current.retry();
  });
  expect(mocked.mock.calls[1]).toEqual(original);
  expect(sessionStorage.getItem(exactTextEditStorageKey(scope))).toBeNull();
  expect(restored.result.current.pending).toBe(false);
});

it.each(["wrong-ack", "permission", "conflict", "service"])(
  "retains an uncertain original request after %s",
  async (kind) => {
    const base = await verifyTextEditBase(originalBase, scope);
    if (kind === "wrong-ack")
      mocked.mockResolvedValueOnce({
        data: { ...native.ack, draft_id: crypto.randomUUID() },
        etag: native.ack_etag,
      });
    else
      mocked.mockRejectedValueOnce(
        new ApiError(
          "uncertain",
          kind === "permission" ? 403 : kind === "conflict" ? 409 : 503,
          "UNKNOWN",
        ),
      );
    const hook = renderHook(() => useExactAuthoringTextEdit(scope));
    await act(async () => {
      await hook.result.current.run(base, native.request, native.request_etag);
    });
    const raw = sessionStorage.getItem(exactTextEditStorageKey(scope));
    expect(hook.result.current.pending).toBe(true);
    await act(async () => {
      await hook.result.current.run(
        base,
        { ...native.request, replacement_text: "different" },
        native.request_etag,
      );
    });
    expect(mocked).toHaveBeenCalledTimes(1);
    expect(sessionStorage.getItem(exactTextEditStorageKey(scope))).toEqual(raw);
  },
);

it("requires explicit verification of the selected chapter before clearing a CAS conflict and retains the wording for rebase", async () => {
  const base = await verifyTextEditBase(originalBase, scope);
  mocked.mockRejectedValueOnce(
    new ApiError("changed", 412, "DRAFT_REVISION_CONFLICT"),
  );
  const hook = renderHook(() => useExactAuthoringTextEdit(scope));
  await act(async () => {
    await hook.result.current.run(base, native.request, native.request_etag);
  });
  expect(hook.result.current.conflict).toBe(true);
  await act(async () => {
    await hook.result.current.retry();
  });
  expect(mocked).toHaveBeenCalledTimes(1);
  await act(async () => {
    expect(await hook.result.current.acknowledgeConflict(base)).toBeNull();
  });
  expect(hook.result.current.conflict).toBe(true);
  const m = native.ack.qualification.manifest;
  const content = structuredClone(base.section.content) as AuthoringDocument;
  const node = content.content[0];
  if (node.type !== "paragraph" && node.type !== "heading")
    throw new Error("Synthetic fixture paragraph missing");
  node.content = [{ type: "text", text: native.request.replacement_text }];
  const fresh = await verifyTextEditBase(
    {
      status: {
        ...base.status,
        draft_revision: native.ack.draft_revision,
        snapshot_id: native.ack.snapshot_id,
        snapshot_digest: native.ack.snapshot_digest,
        exact_sections: [
          {
            ...base.status.exact_sections[0],
            section_revision_id: m.section_revision_id,
            section_revision: m.section_revision,
            section_digest: m.section_digest,
            qualification_id: m.id,
            qualification_digest: native.ack.qualification.digest,
          },
        ],
      },
      section: { ...base.section, revision: m.section_revision, content },
      qualification: native.ack.qualification,
    },
    scope,
  );
  await act(async () => {
    expect(await hook.result.current.acknowledgeConflict(fresh)).toEqual(
      native.request,
    );
  });
  expect(sessionStorage.getItem(exactTextEditStorageKey(scope))).toBeNull();
});

it.each(["malformed", "wrong-scope"])(
  "keeps %s storage and blocks replacement requests",
  async (kind) => {
    const base = await verifyTextEditBase(originalBase, scope);
    const raw =
      kind === "malformed"
        ? "broken JSON"
        : JSON.stringify({
            version: 1,
            scope: { ...scope, bidId: crypto.randomUUID() },
            state: "pending",
            pending: {},
          });
    sessionStorage.setItem(exactTextEditStorageKey(scope), raw);
    const hook = renderHook(() => useExactAuthoringTextEdit(scope));
    expect(hook.result.current.blocked).toBe(true);
    await act(async () => {
      await hook.result.current.run(base, native.request, native.request_etag);
      await hook.result.current.retry();
    });
    expect(mocked).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(exactTextEditStorageKey(scope))).toBe(raw);
  },
);

it.each(["account", "unmount", "record"])(
  "rejects a late ACK after %s change",
  async (kind) => {
    const base = await verifyTextEditBase(originalBase, scope);
    let finish!: (value: { data: unknown; etag: string }) => void;
    mocked.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const hook = renderHook(
      ({ memberId }) => useExactAuthoringTextEdit({ ...scope, memberId }),
      { initialProps: { memberId: scope.memberId } },
    );
    let sending!: ReturnType<typeof hook.result.current.run>;
    act(() => {
      sending = hook.result.current.run(
        base,
        native.request,
        native.request_etag,
      );
    });
    await waitFor(() => expect(mocked).toHaveBeenCalledTimes(1));
    const raw = sessionStorage.getItem(exactTextEditStorageKey(scope));
    if (kind === "account") {
      clearRecordedCommands();
      hook.rerender({ memberId: crypto.randomUUID() });
    }
    if (kind === "unmount") hook.unmount();
    if (kind === "record")
      sessionStorage.setItem(exactTextEditStorageKey(scope), "replaced");
    await act(async () => {
      finish({ data: native.ack, etag: native.ack_etag });
      expect(await sending).toBeNull();
    });
    expect(sessionStorage.getItem(exactTextEditStorageKey(scope))).toBe(
      kind === "account" ? null : kind === "record" ? "replaced" : raw,
    );
  },
);

it("recovers every batch item after a lost ACK with the original key, condition and frozen base", async () => {
  const { syntheticMultiTextEdit } = await import(
    "./authoringMultiTextEdit.test-support"
  );
  const f = await syntheticMultiTextEdit();
  mocked.mockRejectedValueOnce(new ApiError("lost", 0, "NETWORK_ERROR"));
  const first = renderHook(() => useExactAuthoringTextEdit(f.scope));
  await act(async () => {
    await first.result.current.run(
      f.pending.base,
      f.pending.body,
      f.pending.etag,
    );
  });
  expect(first.result.current.pending).toBe(true);
  const original = mocked.mock.calls[0];
  first.unmount();
  mocked.mockResolvedValueOnce({ data: f.ack, etag: f.etag });
  const restored = renderHook(() => useExactAuthoringTextEdit(f.scope));
  expect(mocked).toHaveBeenCalledTimes(1);
  await act(async () => {
    await restored.result.current.retry();
  });
  expect(mocked.mock.calls[1]).toEqual(original);
  expect(restored.result.current.pending).toBe(false);
  expect(sessionStorage.getItem(exactTextEditStorageKey(f.scope))).toBeNull();
});

it("retains the entire batch on CAS conflict and discards a late response after member switch", async () => {
  const { syntheticMultiTextEdit } = await import(
    "./authoringMultiTextEdit.test-support"
  );
  const f = await syntheticMultiTextEdit();
  mocked.mockRejectedValueOnce(
    new ApiError("changed", 412, "REVISION_CONFLICT"),
  );
  const first = renderHook(() => useExactAuthoringTextEdit(f.scope));
  await act(async () => {
    await first.result.current.run(
      f.pending.base,
      f.pending.body,
      f.pending.etag,
    );
  });
  expect(first.result.current.conflict).toBe(true);
  expect(first.result.current.original?.body).toEqual(f.pending.body);
  first.unmount();
  sessionStorage.clear();
  let finish!: (value: { data: unknown; etag: string }) => void;
  mocked.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const hook = renderHook(
    ({ selected }) => useExactAuthoringTextEdit(selected),
    { initialProps: { selected: f.scope } },
  );
  let running!: Promise<unknown>;
  act(() => {
    running = hook.result.current.run(
      f.pending.base,
      f.pending.body,
      f.pending.etag,
    );
  });
  await waitFor(() => expect(mocked).toHaveBeenCalledTimes(2));
  const saved = sessionStorage.getItem(exactTextEditStorageKey(f.scope));
  hook.rerender({ selected: { ...f.scope, memberId: crypto.randomUUID() } });
  await act(async () => {
    finish({ data: f.ack, etag: f.etag });
    await running;
  });
  expect(hook.result.current.pending).toBe(false);
  expect(sessionStorage.getItem(exactTextEditStorageKey(f.scope))).toBe(saved);
});
