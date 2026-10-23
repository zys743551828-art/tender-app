import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";
import type { PackageTechnicalScopeView } from "./contracts";
import { PackageTechnicalEligibility } from "./PackageTechnicalEligibility";
import { readHistoryRecovery } from "./packageHistoricalResearchRecovery";
import {
  PackageScopeRegistrationContext,
  type PackageScopeRegistration,
} from "./packageScopeGuard";
import raw from "./test-fixtures/package-history-ui-complete-http.json";

vi.mock("./api", async (load) => ({
  ...(await load<typeof import("./api")>()),
  api: vi.fn(),
  supportsApi: () => true,
}));

type NativeResponse = {
  name: string;
  method: string;
  path: string;
  query: Record<string, unknown>;
  request_body: unknown;
  body: unknown;
  etag: string | null;
};
const native = raw.responses as NativeResponse[];
function response(name: string) {
  const row = native.find((entry) => entry.name === name);
  if (!row) throw new Error(`Missing native HTTP response: ${name}`);
  return row;
}
const saved = response("saved_scope").body as PackageTechnicalScopeView;
const original = response("admission_created").request_body as {
  submission_id: string;
  outcome_id: string;
  proof_id: string;
  reason: string;
};
const memberId = raw.actor_id;
const workspace = `admission:${saved.manifest.preview.manifest.scope.bid_id}:${saved.manifest.id}`;
const mocked = vi.mocked(api);

function nativeReply(name: string) {
  const row = response(name);
  return { data: row.body, etag: row.etag };
}
function readNative(path: string) {
  const url = new URL(path, "http://native-history-ui.test");
  const row = ["scope_submissions", "scope_outcomes", "admission_context"]
    .map(response)
    .find(
      (entry) =>
        entry.path.replace(/^\/api\/v1/, "") === url.pathname &&
        Object.entries(entry.query).every(
          ([key, value]) => url.searchParams.get(key) === String(value),
        ) &&
        Object.keys(entry.query).length === [...url.searchParams].length,
    );
  if (!row) throw new Error(`Unexpected integration request: ${path}`);
  return { data: row.body, etag: row.etag };
}

beforeEach(() => {
  sessionStorage.clear();
  mocked.mockReset();
  mocked.mockImplementation(async (path, options) =>
    options?.method === "POST"
      ? nativeReply("admission_created")
      : readNative(path),
  );
});

function mountedWorkspace() {
  const entries = new Map<symbol, PackageScopeRegistration>();
  const register = vi.fn(
    (token: symbol, registration: PackageScopeRegistration) => {
      entries.set(token, registration);
      return () => {
        if (entries.get(token) === registration) entries.delete(token);
      };
    },
  );
  const mounted = render(
    <PackageScopeRegistrationContext.Provider value={register}>
      <PackageTechnicalEligibility saved={saved} memberId={memberId} />
    </PackageScopeRegistrationContext.Provider>,
  );
  return {
    ...mounted,
    state: () => ({
      busy: [...entries.values()].some((entry) => entry.state.busy),
      pending: [...entries.values()].some((entry) => entry.state.pending),
      dirty: [...entries.values()].some((entry) => entry.state.dirty),
    }),
  };
}

function purpose(value: "historical_backtest" | "current_prebid") {
  fireEvent.change(screen.getByLabelText("技术范围检查用途"), {
    target: { value },
  });
}
async function selectHistoricalPair() {
  purpose("historical_backtest");
  fireEvent.click(screen.getByRole("button", { name: "读取实交记录" }));
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("检查所用实交记录"))
        .getAllByRole("option")
        .some(
          (item) =>
            (item as HTMLOptionElement).value === original.submission_id,
        ),
    ).toBe(true),
  );
  fireEvent.change(screen.getByLabelText("检查所用实交记录"), {
    target: { value: original.submission_id },
  });
  fireEvent.click(screen.getByRole("button", { name: "读取该实交的成绩记录" }));
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("检查所用成绩记录"))
        .getAllByRole("option")
        .some(
          (item) => (item as HTMLOptionElement).value === original.outcome_id,
        ),
    ).toBe(true),
  );
  fireEvent.change(screen.getByLabelText("检查所用成绩记录"), {
    target: { value: original.outcome_id },
  });
}
const readButton = () =>
  screen.getByRole("button", { name: "读取所选记录的严格准入依据" });
const saveButton = () =>
  screen.getByRole("button", { name: "明确保存这份历史研究准入" });
const writes = () =>
  mocked.mock.calls.filter(([, options]) => options?.method === "POST");

function enterDraft() {
  fireEvent.change(screen.getByLabelText("严格历史准入核验回执"), {
    target: { value: original.proof_id },
  });
  fireEvent.change(screen.getByLabelText("严格历史准入原因"), {
    target: { value: original.reason },
  });
}
async function ready() {
  await selectHistoricalPair();
  fireEvent.click(readButton());
  await screen.findByLabelText("严格历史准入依据");
  enterDraft();
  fireEvent.click(
    screen.getByRole("checkbox", {
      name: "已核对所选实交、成绩和回执，仅保存回溯研究准入",
    }),
  );
  expect(saveButton()).toBeEnabled();
}
function beforeUnload() {
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  return event;
}
function noNewAdmissionAction() {
  for (const name of [
    "读取所选记录的严格准入依据",
    "明确保存这份历史研究准入",
  ]) {
    const action = screen.queryByRole("button", { name });
    if (action) expect(action).toBeDisabled();
  }
}

it("retains the actual selected pair and unsent proof/reason across purpose changes without new requests", async () => {
  mountedWorkspace();
  await ready();
  const reads = mocked.mock.calls.length;
  purpose("current_prebid");
  noNewAdmissionAction();
  expect(mocked.mock.calls).toHaveLength(reads);
  expect(writes()).toHaveLength(0);
  purpose("historical_backtest");
  expect(screen.getByLabelText("检查所用实交记录")).toHaveValue(
    original.submission_id,
  );
  expect(screen.getByLabelText("检查所用成绩记录")).toHaveValue(
    original.outcome_id,
  );
  expect(screen.getByLabelText("严格历史准入核验回执")).toHaveValue(
    original.proof_id,
  );
  expect(screen.getByLabelText("严格历史准入原因")).toHaveValue(
    original.reason,
  );
  expect(mocked.mock.calls).toHaveLength(reads);
  expect(writes()).toHaveLength(0);
});

it("recovers the original pending request while another purpose is active and releases its shared guard only after the exact ACK", async () => {
  let attempts = 0;
  mocked.mockImplementation(async (path, options) => {
    if (options?.method !== "POST") return readNative(path);
    attempts++;
    if (attempts === 1)
      throw new ApiError("回执未确认", 0, "NETWORK_ERROR", undefined, true);
    return nativeReply("admission_created");
  });
  const mounted = mountedWorkspace();
  await ready();
  fireEvent.click(saveButton());
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "恢复原准入请求结果" }),
    ).toBeEnabled(),
  );
  const pending = readHistoryRecovery(memberId, workspace);
  expect(pending?.body).toMatchObject(original);
  expect(mounted.state()).toMatchObject({ pending: true });
  purpose("current_prebid");
  expect(
    screen.getByRole("button", { name: "恢复原准入请求结果" }),
  ).toBeEnabled();
  expect(readHistoryRecovery(memberId, workspace)).toEqual(pending);
  expect(beforeUnload().defaultPrevented).toBe(true);
  noNewAdmissionAction();
  expect(writes()).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "恢复原准入请求结果" }));
  await waitFor(() =>
    expect(readHistoryRecovery(memberId, workspace)).toBeNull(),
  );
  expect(writes()).toHaveLength(2);
  expect(writes()[1]).toEqual(writes()[0]);
  expect(mounted.state()).toEqual({
    busy: false,
    pending: false,
    dirty: false,
  });
  expect(beforeUnload().defaultPrevented).toBe(false);
});

it("registers busy and unsent draft state with the shared scope guard and releases it only on explicit clearing", async () => {
  const mounted = mountedWorkspace();
  await selectHistoricalPair();
  let finish!: (value: ReturnType<typeof nativeReply>) => void;
  mocked.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  fireEvent.click(readButton());
  await waitFor(() => expect(mounted.state().busy).toBe(true));
  await act(async () => finish(nativeReply("admission_context")));
  await screen.findByLabelText("严格历史准入依据");
  enterDraft();
  expect(mounted.state()).toEqual({ busy: false, pending: false, dirty: true });
  purpose("current_prebid");
  expect(mounted.state().dirty).toBe(true);
  expect(beforeUnload().defaultPrevented).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: /清空.*未发送/ }));
  expect(mounted.state()).toEqual({
    busy: false,
    pending: false,
    dirty: false,
  });
  expect(beforeUnload().defaultPrevented).toBe(false);
  purpose("historical_backtest");
  const reason = screen.queryByLabelText("严格历史准入原因");
  const proof = screen.queryByLabelText("严格历史准入核验回执");
  if (reason) expect(reason).toHaveValue("");
  if (proof) expect(proof).toHaveValue("");
  expect(writes()).toHaveLength(0);
});
