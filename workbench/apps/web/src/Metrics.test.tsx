import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { it, expect, vi } from "vitest";
import { Metrics } from "./Metrics";
const value = {
  scope: {
    period_from: null,
    period_to: null,
    as_of: "2026-01-01T00:00:00Z",
    verification_scope: "ledger",
    scope_note: "按实交时间、有效头统计",
    definition: "fr011-ledger/v1",
    excluded_submission_counts: {},
    identity_submission_conflicts: [],
    head_authorities: [],
    effective_head_digest: "d",
  },
  effective_submissions: 1,
  known_outcomes: 0,
  unknown_outcomes: 1,
  conflicted_outcomes: 0,
  unusable_outcomes: 0,
  stage_counts: { candidate: 0, awarded: 0 },
  verification_counts: { pending: 0, verified: 0 },
  excluded_result_counts: {},
  shortlist_rate: { numerator: 0, denominator: 0, value: null },
  win_rate: { numerator: 0, denominator: 0, value: null },
  qualification: {
    identified: null,
    resolved: null,
    dismissed: null,
    open: null,
    open_at_submission: null,
    known_snapshot_submissions: 0,
    unknown_snapshot_submissions: 1,
    known_current_review_submissions: 0,
    unknown_current_review_submissions: 1,
    official_rejections: 0,
    scope_note: "历史快照未知",
  },
  online_error: {
    prediction_pairs: 19,
    needed_pairs: 20,
    online_error_state: "insufficient",
    mae: null,
    bias: null,
    excluded_pair_counts: {},
    scope_note: "未足20对",
  },
  model_qualification_granted: false,
};
it("零分母与未知风险不补零；少于20对隐藏误差；筛选只读且按明确提交应用", async () => {
  const urls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      urls.push(url);
      return new Response(
        JSON.stringify(
          url.includes("/bids")
            ? { items: [], has_more: false, next_cursor: null }
            : value,
        ),
      );
    }),
  );
  const u = userEvent.setup();
  render(<Metrics />);
  await screen.findByText("按实交时间、有效头统计");
  expect(screen.getAllByText("暂无可评价结果")).toHaveLength(2);
  expect(screen.getByText(/尚无足够有效配对/)).toBeVisible();
  expect(screen.getAllByText("未知").length).toBeGreaterThan(0);
  await u.selectOptions(screen.getByLabelText("统计口径"), "verified_only");
  expect(urls.some((url) => url.includes("verified_only"))).toBe(false);
  await u.click(screen.getByRole("button", { name: "更新统计范围" }));
  await screen.findByText("历史快照未知");
  expect(urls.some((url) => url.includes("verified_only"))).toBe(true);
  expect(
    within(
      screen.getByRole("heading", { name: "在线预测误差" }).parentElement!,
    ).queryByText(/^百分制 MAE/),
  ).toBeNull();
});
