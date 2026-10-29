import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import type { ProjectWorkSummary as Summary } from "./contracts";
import { ProjectWorkSummary } from "./ProjectWorkSummary";
import { checkedProjectSummaries } from "./projectSummaries";
import { useProjectSummaries } from "./useProjectSummaries";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: vi.fn(),
}));
const A = "00000000-0000-4000-8000-000000000001";
const B = "00000000-0000-4000-8000-000000000002";
const summary = (id = A): Summary => ({
  bid_id: id,
  phase: "working",
  archived_at: null,
  package_counts: { authority: 1, bid: 2 },
  head_members: { total: 5, parse_not_frozen: 1 },
  next_action: {
    action: "inspect_package_parses",
    reason: "核对尚未冻结的解析身份",
    target_url: `/bids/${id}/packages`,
    blocked: true,
  },
  action_scope: "package_directory",
  risk_status: "not_evaluated",
  critical_risk_count: null,
  other_risk_count: null,
  prediction_status: "not_evaluated",
  predicted_score: null,
  inventory_complete: false,
  formal_scoring_eligible: false,
  submission_eligible: false,
});
const batch = (items: Summary[]) => ({
  version: "project-work-summary/1",
  observed_at: "2026-10-23T00:00:00Z",
  items,
});
const answer = (data: unknown) => ({ data, etag: null, replay: false });

beforeEach(() => {
  vi.mocked(api).mockReset();
});

describe("项目整包摘要", () => {
  it("显示已登记的包和未冻结解析，并导航到整包工作面", async () => {
    vi.mocked(api).mockResolvedValue(answer(batch([summary()])));
    const navigate = vi.fn();
    render(<ProjectWorkSummary bidId={A} onNavigate={navigate} />);
    expect(await screen.findByText("依据包 1 · 投标包 2")).toBeInTheDocument();
    expect(screen.getByText(/1 个解析身份未冻结/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "打开整包工作面" }));
    expect(navigate).toHaveBeenCalledWith("packages");
    expect(
      screen.queryByText(/风险为零|预测分为0|全部通过/),
    ).not.toBeInTheDocument();
  });

  it.each([
    "critical_risk_count",
    "other_risk_count",
    "predicted_score",
    "inventory_complete",
    "formal_scoring_eligible",
    "submission_eligible",
  ])("拒绝将%s伪装成零或通过", (field) => {
    const value = {
      ...summary(),
      [field]:
        field.endsWith("count") || field === "predicted_score" ? 0 : true,
    };
    expect(() => checkedProjectSummaries(batch([value]), [A])).toThrow();
  });

  it("串项目的摘要不回退为零或旧单稿状态", async () => {
    vi.mocked(api).mockResolvedValue(answer(batch([summary(B)])));
    render(<ProjectWorkSummary bidId={A} onNavigate={vi.fn()} />);
    expect(
      await screen.findByText(/项目摘要身份或状态不完整/),
    ).toBeInTheDocument();
    expect(screen.getByText("整包摘要待核对")).toBeInTheDocument();
    expect(screen.queryByText("依据包 1 · 投标包 2")).not.toBeInTheDocument();
  });

  it("切换项目后丢弃旧请求的晚到结果", async () => {
    let old!: (value: ReturnType<typeof answer>) => void;
    vi.mocked(api).mockImplementation((path) =>
      path.includes(A)
        ? new Promise((resolve) => {
            old = resolve;
          })
        : Promise.resolve(answer(batch([summary(B)]))),
    );
    const view = render(<ProjectWorkSummary bidId={A} onNavigate={vi.fn()} />);
    await waitFor(() => expect(old).toBeTypeOf("function"));
    view.rerender(<ProjectWorkSummary bidId={B} onNavigate={vi.fn()} />);
    await screen.findByText("依据包 1 · 投标包 2");
    await act(async () =>
      old(
        answer(
          batch([
            { ...summary(A), package_counts: { authority: 99, bid: 99 } },
          ]),
        ),
      ),
    );
    expect(screen.queryByText("依据包 99 · 投标包 99")).not.toBeInTheDocument();
  });

  it("重新读取失败后隐藏已过期摘要，并允许显式重试", async () => {
    vi.mocked(api)
      .mockResolvedValueOnce(answer(batch([summary()])))
      .mockRejectedValueOnce(new Error("摘要读取中断"));
    render(<ProjectWorkSummary bidId={A} onNavigate={vi.fn()} />);
    await screen.findByText("依据包 1 · 投标包 2");
    fireEvent.click(screen.getByRole("button", { name: "重新核对摘要" }));
    expect(await screen.findByText("摘要读取中断")).toBeInTheDocument();
    expect(screen.getByText("整包摘要待核对")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "打开整包工作面" }),
    ).not.toBeInTheDocument();
  });

  it("大目录按20项分批，每次最多两个读取请求", async () => {
    const ids = Array.from(
      { length: 61 },
      (_, index) =>
        `00000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
    );
    const releases: (() => void)[] = [];
    vi.mocked(api).mockImplementation(
      (path) =>
        new Promise((resolve) => {
          const selected = new URL(
            path,
            "http://unit.test",
          ).searchParams.getAll("bid_id");
          releases.push(() =>
            resolve(answer(batch(selected.map((id) => summary(id))))),
          );
        }),
    );
    const { result } = renderHook(() => useProjectSummaries(ids));
    await waitFor(() => expect(api).toHaveBeenCalledTimes(2));
    expect(result.current.items.size).toBe(0);
    await act(async () => releases.splice(0).forEach((release) => release()));
    await waitFor(() => expect(api).toHaveBeenCalledTimes(4));
    await act(async () => releases.splice(0).forEach((release) => release()));
    await waitFor(() => expect(result.current.items.size).toBe(61));
  });
});
