import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { PackageHistoricalResearch } from "./PackageHistoricalResearch";
import type { HistoryPending } from "./packageHistoricalResearchProtocol";
import {
  historyRecoveryKey,
  readHistoryRecovery,
  writeHistoryRecovery,
} from "./packageHistoricalResearchRecovery";

// Explicit frontend fault simulations. Native PG response replay is exercised
// separately; these fixtures do not certify historical evidence or model quality.
const id = (n: number) =>
  `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const member = id(1),
  sha = "a".repeat(64);
const filters = {
  bid_id: null,
  scope_id: null,
  protocol_id: null,
  cohort_id: null,
};
function directory(configured = true, items: unknown[] = [], extra = {}) {
  return {
    version: "package-history-directory/1",
    kind: "admissions",
    filters,
    observed_at: "2026-10-22T01:00:00Z",
    currentness_rechecked: false,
    research_only: true,
    formal_eligibility: "unavailable",
    qualification_granted: false,
    status: configured ? "observed" : "unavailable",
    schema_configured: configured,
    items,
    total: configured ? items.length : null,
    observation_digest: configured ? sha : null,
    complete_observation: configured,
    has_more: configured ? false : null,
    next_cursor: null,
    ...extra,
  };
}
function admissionItem(n: number) {
  return {
    id: id(n),
    kind: "admission",
    created_at: "2026-10-21T00:00:00Z",
    current_status: "not_rechecked",
    bid_id: id(n + 10),
    scope_id: id(n + 20),
    submission_id: id(n + 30),
    outcome_id: id(n + 40),
    digest: sha,
    origin: "synthetic",
    state: "mechanism_candidate",
    historical_as_of: "2025-05-01T00:00:00Z",
    label_known_at: "2025-05-02T00:00:00Z",
  };
}
const pending = (): HistoryPending => ({
  kind: "protocol",
  path: "/package-historical-research/protocols",
  key: id(9),
  etag: null,
  body: {
    method_digest: sha,
    seed: 17,
    bootstrap_iterations: 100,
    reason: "恢复原先明确冻结的合成机制协议",
  },
  expected: {},
});
const json = (body: unknown, status = 200, etag?: string) =>
  new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      ...(etag ? { ETag: etag } : {}),
    },
  });
beforeEach(() => {
  sessionStorage.clear();
  vi.restoreAllMocks();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      throw new Error("unexpected request");
    }),
  );
});

it("does not fetch labels or create a research job merely by opening the workbench", () => {
  render(<PackageHistoricalResearch memberId={member} />);
  expect(
    screen.getByRole("heading", { name: "整包历史研究" }),
  ).toBeInTheDocument();
  expect(screen.getByText(/尚未接通完整图文三评特征/)).toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();
});

it("distinguishes an unavailable directory with unknown count from an observed empty directory", async () => {
  const transport = vi
    .fn()
    .mockResolvedValueOnce(json(directory(false)))
    .mockResolvedValueOnce(json(directory()));
  vi.stubGlobal("fetch", transport);
  render(<PackageHistoricalResearch memberId={member} />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "读取准入资料目录" }));
  expect(
    await screen.findByText(/准入资料目录尚未配置，记录数量未知/),
  ).toBeInTheDocument();
  expect(
    screen.queryByText(/本次已观察到的准入资料目录为空/),
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "读取准入资料目录" }));
  expect(
    await screen.findByText("本次已观察到的准入资料目录为空。"),
  ).toBeInTheDocument();
  expect(
    transport.mock.calls.every(
      ([, options]) => (options as RequestInit).method === "GET",
    ),
  ).toBe(true);
});

it("refuses to merge pages from different directory observations and preserves the first page", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        json(
          directory(true, [admissionItem(100)], {
            total: 2,
            has_more: true,
            next_cursor: "cursor-one",
          }),
        ),
      )
      .mockResolvedValueOnce(
        json(
          directory(true, [admissionItem(200)], {
            total: 2,
            observation_digest: "b".repeat(64),
          }),
        ),
      ),
  );
  render(<PackageHistoricalResearch memberId={member} />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "读取准入资料目录" }));
  await user.click(
    await screen.findByRole("button", { name: "加载更多准入资料" }),
  );
  expect(await screen.findByText(/目录观察已变化/)).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "核对资料 1 的准入详情" }),
  ).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "核对资料 2 的准入详情" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText(`记录 ${id(100)}`)).toBeInTheDocument();
});

it("rejects a repeated item across otherwise matching pages", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        json(
          directory(true, [admissionItem(100)], {
            total: 2,
            has_more: true,
            next_cursor: "cursor-one",
          }),
        ),
      )
      .mockResolvedValueOnce(
        json(directory(true, [admissionItem(100)], { total: 2 })),
      ),
  );
  render(<PackageHistoricalResearch memberId={member} />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "读取准入资料目录" }));
  await user.click(
    await screen.findByRole("button", { name: "加载更多准入资料" }),
  );
  expect(await screen.findByText(/目录出现重复记录/)).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "核对资料 2 的准入详情" }),
  ).not.toBeInTheDocument();
});

it("discards a late directory response after the member changes", async () => {
  let finish!: (value: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
    ),
  );
  const view = render(<PackageHistoricalResearch memberId={member} />);
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "读取准入资料目录" }));
  view.rerender(<PackageHistoricalResearch memberId={id(2)} />);
  finish(json(directory(true, [admissionItem(100)])));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "读取准入资料目录" }),
    ).toBeEnabled(),
  );
  expect(screen.queryByText(`记录 ${id(100)}`)).not.toBeInTheDocument();
});

it("retains unsent time boundaries and reason when moving between research steps", async () => {
  render(<PackageHistoricalResearch memberId={member} />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "2. 冻结研究方案" }));
  await user.type(screen.getByLabelText("冻结研究组的原因"), "保留未发送方案");
  const split = screen.getByLabelText("实交分界（北京时间 UTC+08:00）");
  await user.type(split, "2025-06-01T09:30");
  await user.click(screen.getByRole("button", { name: "3. 任务与结果" }));
  await user.click(screen.getByRole("button", { name: "2. 冻结研究方案" }));
  expect(screen.getByLabelText("冻结研究组的原因")).toHaveValue(
    "保留未发送方案",
  );
  expect(split).toHaveValue("2025-06-01T09:30");
  expect(fetch).not.toHaveBeenCalled();
});

it("replays the identical stored request across failed transport, step changes and remount", async () => {
  const original = pending();
  writeHistoryRecovery(member, "research", original);
  const writes: RequestInit[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url, options) => {
      writes.push(options as RequestInit);
      throw new Error("connection lost");
    }),
  );
  const user = userEvent.setup(),
    first = render(<PackageHistoricalResearch memberId={member} />);
  await user.click(screen.getByRole("button", { name: "恢复原研究请求结果" }));
  await screen.findByText(/暂时无法连接服务/);
  await user.click(screen.getByRole("button", { name: "3. 任务与结果" }));
  expect(
    screen.getByRole("button", { name: "恢复原研究请求结果" }),
  ).toBeEnabled();
  first.unmount();
  render(<PackageHistoricalResearch memberId={member} />);
  await user.click(screen.getByRole("button", { name: "恢复原研究请求结果" }));
  await waitFor(() => expect(writes).toHaveLength(2));
  expect(writes[0].body).toBe(JSON.stringify(original.body));
  expect(writes[1]).toEqual(writes[0]);
  expect(new Headers(writes[0].headers).get("Idempotency-Key")).toBe(
    original.key,
  );
  expect(new Headers(writes[0].headers).has("If-Match")).toBe(false);
  expect(readHistoryRecovery(member)).toEqual(original);
});

it("keeps an ambiguous successful but invalid ACK and does not select its foreign protocol", async () => {
  const original = pending();
  writeHistoryRecovery(member, "research", original);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => json({ id: id(999) }, 201, '"wrong"')),
  );
  render(<PackageHistoricalResearch memberId={member} />);
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "恢复原研究请求结果" }));
  expect(
    await screen.findByText(/历史研究记录的身份、完整内容或回执无法核对/),
  ).toBeInTheDocument();
  expect(readHistoryRecovery(member)).toEqual(original);
  expect(screen.queryByText("本次明确选择的协议")).not.toBeInTheDocument();
});

it.each([401, 403, 503])(
  "keeps the original request on a %i failure that can precede replay",
  async (status) => {
    const original = pending();
    writeHistoryRecovery(member, "research", original);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json(
          { code: "TEST_PRE_REPLAY_GUARD", message: "当前读取依赖不可用" },
          status,
        ),
      ),
    );
    render(<PackageHistoricalResearch memberId={member} />);
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "恢复原研究请求结果" }));
    expect(await screen.findByText("当前读取依赖不可用")).toBeInTheDocument();
    expect(readHistoryRecovery(member)).toEqual(original);
  },
);

it("performs no write when recovery storage cannot be persisted", async () => {
  writeHistoryRecovery(member, "research", pending());
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new DOMException("quota", "QuotaExceededError");
  });
  render(<PackageHistoricalResearch memberId={member} />);
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "恢复原研究请求结果" }));
  expect(
    await screen.findByText(/浏览器未能保存历史研究原请求/),
  ).toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();
});

it("preserves corrupt stored intent, blocks writes, and still allows read-only discovery", async () => {
  sessionStorage.setItem(historyRecoveryKey(member), "{broken");
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => json(directory())),
  );
  render(<PackageHistoricalResearch memberId={member} />);
  expect(screen.getByText(/本地历史研究恢复记录损坏/)).toBeInTheDocument();
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "读取准入资料目录" }));
  expect(
    await screen.findByText("本次已观察到的准入资料目录为空。"),
  ).toBeInTheDocument();
  expect(sessionStorage.getItem(historyRecoveryKey(member))).toBe("{broken");
});

it("does not restore another member's pending request", () => {
  writeHistoryRecovery(member, "research", pending());
  render(<PackageHistoricalResearch memberId={id(2)} />);
  expect(
    screen.queryByRole("region", { name: "待恢复的原研究请求" }),
  ).not.toBeInTheDocument();
  expect(
    within(
      screen.getByRole("navigation", { name: "整包历史研究步骤" }),
    ).getByRole("button", { name: "1. 选择已准入资料" }),
  ).toHaveAttribute("aria-current", "step");
  expect(readHistoryRecovery(member)).toEqual(pending());
});
