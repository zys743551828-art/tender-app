import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "./api";
import {
  exactAuthoringFixture,
  exactId,
} from "./authoringExactFixtures.test-support";
import { useAuthoringExactDraft } from "./useAuthoringExactDraft";

vi.mock("./api", async () => ({
  ...(await vi.importActual<typeof import("./api")>("./api")),
  api: vi.fn(),
}));
const mocked = vi.mocked(api);
beforeEach(() => {
  mocked.mockReset();
});
it("keeps an ordinary draft editable without requiring optional exact-source tables", async () => {
  const f = await exactAuthoringFixture();
  const snapshot = { ...f.snapshot, authoring_exact_sections: undefined };
  delete snapshot.authoring_exact_sections;
  mocked.mockResolvedValue({ data: snapshot, etag: null });
  const head = {
    id: f.saved.draft_id,
    bid_id: f.f.bid.id,
    revision: f.saved.draft_revision,
    snapshot_id: f.saved.snapshot_id,
    sections: [],
  };
  const hook = renderHook(() =>
    useAuthoringExactDraft(f.f.bid.id, head.id, head),
  );
  await waitFor(() =>
    expect(hook.result.current.ordinaryEditBlocked).toBe(false),
  );
  expect(hook.result.current.buildBlocked).toBe(false);
  expect(hook.result.current.hasExact).toBe(false);
  expect(mocked).toHaveBeenCalledTimes(1);
});
it.each(["ready", "not-configured", "wrong-revision", "unavailable"])(
  "preserves exact revision editing protection and uses actual build state: %s",
  async (mode) => {
    const f = await exactAuthoringFixture();
    mocked.mockImplementation(async (path) => {
      if (path.includes("/draft-snapshots/"))
        return { data: f.snapshot, etag: null };
      if (mode === "unavailable") throw new Error("schema unavailable");
      return {
        data: {
          ...f.status,
          build_available: mode !== "not-configured",
          snapshot_id:
            mode === "wrong-revision" ? exactId(99) : f.saved.snapshot_id,
        },
        etag: null,
      };
    });
    const head = {
      id: f.saved.draft_id,
      bid_id: f.f.bid.id,
      revision: f.saved.draft_revision,
      snapshot_id: f.saved.snapshot_id,
      sections: [],
    };
    const hook = renderHook(() =>
      useAuthoringExactDraft(f.f.bid.id, head.id, head),
    );
    await waitFor(() => expect(mocked).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(hook.result.current.checking).toBe(false));
    expect(hook.result.current.ordinaryEditBlocked).toBe(true);
    expect(hook.result.current.buildBlocked).toBe(mode !== "ready");
  },
);
