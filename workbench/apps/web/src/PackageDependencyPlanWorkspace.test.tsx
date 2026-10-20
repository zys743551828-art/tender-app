import { StrictMode } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Workspace from "./PackageDependencyPlanWorkspace";
import {
  dependencyPlanFixture,
  dependencyPlanAssessment,
  dependencyPlanReply,
  dependencyPlanPage,
} from "../qa-previews/frozen-inputs/dependencyPlan";
import type { DependencyPlanCandidate } from "./PackageDependencyPlanWorkspace";
import type {
  PackageDependencyPlanView,
  SavePackageDependencyPlan,
} from "./contracts";
import { dependencyPlanScope } from "./dependencyPlanProtocol";
import { dependencyPlanStorageKey } from "./dependencyPlanRecovery";
import { frozenManifestDigest } from "./packageFrozenInput";
let fixture: Awaited<ReturnType<typeof dependencyPlanFixture>>;
let candidate: DependencyPlanCandidate;
const fetchMock = vi.fn(),
  recheck = vi.fn();
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
  vi.stubGlobal("fetch", fetchMock);
  sessionStorage.clear();
  fetchMock.mockReset();
  recheck.mockReset();
  fixture = await dependencyPlanFixture();
  const request = {
    execution_input_digest: fixture.props.prepared.digest,
    purpose: "prebid_compliance" as const,
    fact_ids: [],
    dependencies: [],
  };
  candidate = {
    request,
    assessment: await dependencyPlanAssessment(fixture, request),
  };
  fetchMock.mockImplementation(async (_url: string, options?: RequestInit) => {
    if (options?.method === "POST")
      return json(
        await dependencyPlanReply(fixture, JSON.parse(String(options.body))),
        201,
      );
    throw new Error("unexpected synthetic history request");
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
function show(value: DependencyPlanCandidate | null = candidate) {
  return render(
    <StrictMode>
      <Workspace {...fixture.props} candidate={value} onRecheck={recheck} />
    </StrictMode>,
  );
}
async function prepare() {
  await userEvent.click(
    screen.getByText("保存与查阅依赖计划", { selector: "summary" }),
  );
  await userEvent.type(
    screen.getByLabelText("计划保存理由"),
    "明确保存本轮未知缺口及选择",
  );
  await userEvent.click(screen.getByRole("checkbox"));
}
const storage = () =>
  JSON.parse(
    sessionStorage.getItem(
      dependencyPlanStorageKey(dependencyPlanScope(fixture.props)),
    )!,
  );
it("does not request, save or create recovery records on mount", () => {
  show();
  expect(fetchMock).not.toHaveBeenCalled();
  expect(sessionStorage.length).toBe(0);
});
it("saves only after checked candidate, reason and explicit confirmation, preserving unknown status", async () => {
  show();
  await prepare();
  await userEvent.click(
    screen.getByRole("button", { name: "明确保存本轮计划" }),
  );
  await screen.findByRole("region", { name: "原计划保存回执" });
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const options = fetchMock.mock.calls[0][1] as RequestInit;
  expect(JSON.parse(String(options.body)).assessment_digest).toBe(
    candidate.assessment.digest,
  );
  expect(new Headers(options.headers).get("Idempotency-Key")).toBeTruthy();
  expect(storage().pending).toBeNull();
  expect(storage().lastId).toBeTruthy();
  expect(screen.getByText(/这是保存时的记录/)).toBeInTheDocument();
  expect(screen.getAllByText(/事实需求尚未核定/).length).toBeGreaterThan(0);
});
it("cannot save absent or changed candidate even with a reason and prior confirmation", async () => {
  const view = show();
  await prepare();
  view.rerender(
    <StrictMode>
      <Workspace {...fixture.props} candidate={null} onRecheck={recheck} />
    </StrictMode>,
  );
  expect(screen.getByLabelText("计划保存理由")).toHaveValue(
    "明确保存本轮未知缺口及选择",
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "明确保存本轮计划" }),
    ).toBeDisabled(),
  );
  expect(fetchMock).not.toHaveBeenCalled();
});
it("retains unknown POST and restores exact body and key after reload only on explicit action", async () => {
  let committed: PackageDependencyPlanView;
  fetchMock.mockImplementationOnce(async (_url, options: RequestInit) => {
    committed = await dependencyPlanReply(
      fixture,
      JSON.parse(String(options.body)),
    );
    throw new TypeError("synthetic lost ACK");
  });
  const first = show();
  await prepare();
  await userEvent.click(
    screen.getByRole("button", { name: "明确保存本轮计划" }),
  );
  await screen.findByRole("button", { name: "恢复原计划保存回执" });
  expect(storage().pending).not.toBeNull();
  const original = fetchMock.mock.calls[0][1] as RequestInit;
  first.unmount();
  show(null);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  fetchMock.mockImplementationOnce(async () => json(committed, 201));
  await userEvent.click(
    screen.getByRole("button", { name: "恢复原计划保存回执" }),
  );
  await screen.findByRole("region", { name: "原计划保存回执" });
  const restored = fetchMock.mock.calls[1][1] as RequestInit;
  expect(restored.body).toBe(original.body);
  expect(new Headers(restored.headers).get("Idempotency-Key")).toBe(
    new Headers(original.headers).get("Idempotency-Key"),
  );
  expect(storage().pending).toBeNull();
});
it("preserves pending on malformed ACK instead of declaring saved", async () => {
  fetchMock.mockImplementationOnce(async (_url, options: RequestInit) => {
    const value = await dependencyPlanReply(
      fixture,
      JSON.parse(String(options.body)),
    );
    Object.assign(value.manifest, { publication_authorized: true });
    value.digest = await frozenManifestDigest(value.manifest);
    return json(value, 201);
  });
  show();
  await prepare();
  await userEvent.click(
    screen.getByRole("button", { name: "明确保存本轮计划" }),
  );
  await screen.findByText(/计划历史或回执的原身份/);
  expect(storage().pending).not.toBeNull();
  expect(
    screen.queryByRole("region", { name: "原计划保存回执" }),
  ).not.toBeInTheDocument();
});
it.each([
  ["PACKAGE_INPUT_DEPENDENCIES_CHANGED", true],
  ["IDEMPOTENCY_CONFLICT", false],
] as const)(
  "handles recovered %s without silently replacing the original request",
  async (code, clear) => {
    fetchMock.mockRejectedValueOnce(new TypeError("synthetic uncertain save"));
    show();
    await prepare();
    await userEvent.click(
      screen.getByRole("button", { name: "明确保存本轮计划" }),
    );
    await screen.findByRole("button", { name: "恢复原计划保存回执" });
    fetchMock.mockResolvedValueOnce(
      json({ code, message: "合成拒绝", retryable: false, details: {} }, 409),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "恢复原计划保存回执" }),
    );
    await screen.findByText("合成拒绝");
    expect(storage().pending === null).toBe(clear);
    expect(recheck).toHaveBeenCalledTimes(clear ? 1 : 0);
  },
);
it("uses the original cursor for the next page and rejects a repeated earlier page", async () => {
  const first = await historyValue();
  const second = await dependencyPlanReply(
    fixture,
    {
      ...candidate.request,
      assessment_digest: candidate.assessment.digest,
      reason: "独立第二份历史计划",
    },
    "00000000-0000-4000-8000-000000000098",
  );
  const page = dependencyPlanPage(fixture, [first]);
  page.has_more = true;
  page.next_cursor = "opaque:next-page";
  fetchMock
    .mockResolvedValueOnce(json(page))
    .mockResolvedValueOnce(json(page))
    .mockResolvedValueOnce(json(dependencyPlanPage(fixture, [second])));
  show(null);
  await userEvent.click(
    screen.getByText("保存与查阅依赖计划", { selector: "summary" }),
  );
  await userEvent.click(screen.getByRole("button", { name: "查看已保存计划" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "查看下一页计划" }),
  );
  await screen.findByText(/计划目录未按原游标向后读取/);
  await userEvent.click(screen.getByRole("button", { name: "查看下一页计划" }));
  await screen.findByText("独立第二份历史计划");
  expect(fetchMock.mock.calls[2][0]).toContain("cursor=opaque%3Anext-page");
  expect(
    screen.queryByRole("button", { name: "查看下一页计划" }),
  ).not.toBeInTheDocument();
});
it("does not transmit when local recovery persistence fails", async () => {
  show();
  await prepare();
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("synthetic storage unavailable");
  });
  await userEvent.click(
    screen.getByRole("button", { name: "明确保存本轮计划" }),
  );
  await screen.findByText(/synthetic storage unavailable/);
  expect(fetchMock).not.toHaveBeenCalled();
});
it("preserves corrupt recovery and blocks new saves without automatic requests", async () => {
  const key = dependencyPlanStorageKey(dependencyPlanScope(fixture.props));
  sessionStorage.setItem(key, "broken synthetic record");
  show();
  await userEvent.click(
    screen.getByText("保存与查阅依赖计划", { selector: "summary" }),
  );
  expect(screen.getByText(/本机恢复记录无法核验/)).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "明确保存本轮计划" }),
  ).toBeDisabled();
  expect(fetchMock).not.toHaveBeenCalled();
  expect(sessionStorage.getItem(key)).toBe("broken synthetic record");
});
it("clears a proven new-request rejection and requests a new dependency check", async () => {
  fetchMock.mockResolvedValueOnce(
    json(
      {
        code: "PACKAGE_INPUT_DEPENDENCIES_CHANGED",
        message: "重新核对",
        retryable: false,
        details: {},
      },
      409,
    ),
  );
  show();
  await prepare();
  await userEvent.click(
    screen.getByRole("button", { name: "明确保存本轮计划" }),
  );
  await waitFor(() => expect(recheck).toHaveBeenCalledOnce());
  expect(storage().pending).toBeNull();
});
async function historyValue() {
  const body: SavePackageDependencyPlan = {
    ...candidate.request,
    assessment_digest: candidate.assessment.digest,
    reason: "此前明确保存的原计划",
  };
  return dependencyPlanReply(fixture, body);
}
it("discovers and reads original history explicitly without replacing the current candidate", async () => {
  const value = await historyValue();
  fetchMock.mockImplementation(async (url) =>
    url.includes("?limit=")
      ? json(dependencyPlanPage(fixture, [value]))
      : json(value),
  );
  show(null);
  await userEvent.click(
    screen.getByText("保存与查阅依赖计划", { selector: "summary" }),
  );
  await userEvent.click(screen.getByRole("button", { name: "查看已保存计划" }));
  await screen.findByRole("button", { name: "查看这份原计划" });
  await userEvent.click(screen.getByRole("button", { name: "查看这份原计划" }));
  await screen.findByRole("region", { name: "原计划保存回执" });
  expect(
    screen.getByRole("button", { name: "明确保存本轮计划" }),
  ).toBeDisabled();
  expect(
    fetchMock.mock.calls.every(
      ([, options]) => !options?.method || options.method === "GET",
    ),
  ).toBe(true);
  expect(sessionStorage.length).toBe(0);
});
it("rejects forged history directory qualification", async () => {
  const page = dependencyPlanPage(fixture, [await historyValue()]);
  Object.assign(page, { facts_qualified: true });
  fetchMock.mockResolvedValueOnce(json(page));
  show();
  await userEvent.click(
    screen.getByText("保存与查阅依赖计划", { selector: "summary" }),
  );
  await userEvent.click(screen.getByRole("button", { name: "查看已保存计划" }));
  await screen.findByText(/计划目录与原准备输入不符/);
  expect(
    screen.queryByRole("button", { name: "查看这份原计划" }),
  ).not.toBeInTheDocument();
});
it("ignores late history after changing the exact prepared input", async () => {
  const value = await historyValue();
  let resolve!: (r: Response) => void;
  fetchMock
    .mockImplementationOnce(async () =>
      json(dependencyPlanPage(fixture, [value])),
    )
    .mockImplementationOnce(
      () =>
        new Promise((r) => {
          resolve = r;
        }),
    );
  const view = show();
  await userEvent.click(
    screen.getByText("保存与查阅依赖计划", { selector: "summary" }),
  );
  await userEvent.click(screen.getByRole("button", { name: "查看已保存计划" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "查看这份原计划" }),
  );
  view.rerender(
    <StrictMode>
      <Workspace
        {...fixture.props}
        prepared={{ ...fixture.props.prepared, digest: "a".repeat(64) }}
        candidate={null}
        onRecheck={recheck}
      />
    </StrictMode>,
  );
  await act(async () => {
    resolve(json(value));
  });
  expect(
    screen.queryByRole("region", { name: "原计划保存回执" }),
  ).not.toBeInTheDocument();
});
