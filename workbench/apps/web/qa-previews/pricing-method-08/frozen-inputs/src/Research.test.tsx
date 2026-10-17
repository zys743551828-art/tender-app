import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { OutcomeCard, OutcomesPanel } from "./Archives";
import { Research } from "./Research";
import type {
  ResearchCapabilities,
  ResearchGroupingView,
  ResearchListedSample,
  ResearchOutcomeDetail,
} from "./contracts";

const capabilities: ResearchCapabilities = {
  historical_outcomes: true,
  source_authority_configured: false,
  official_zero_is_valid: true,
  unknown_is_not_zero: true,
  batch_dry_run: true,
  price: { available: false, digest: null, currency: null },
  formal_prediction: { mode: "unavailable", reasons: ["没有业务发布证据"] },
  model_training: "awaiting_verified_real_labels",
  model_release: "unavailable",
  requires_full_chapters: true,
  judgments_per_item: 3,
};
const outcome: ResearchOutcomeDetail = {
  id: "outcome",
  bid_id: "bid",
  submission_id: "submitted",
  score_kind: "technical_total",
  value: "0",
  maximum: "100",
  verification: "conflict",
  source_version_id: "source",
  known_at: "2026-10-16T00:00:00Z",
  verification_revision: 1,
  supersedes_id: "old",
  verification_details: null,
  current: true,
};
const sample: ResearchListedSample = {
  id: "sample",
  bid_id: "bid",
  submission_id: "submitted",
  outcome_id: "outcome",
  source_group_id: "group",
  known_at: outcome.known_at,
  admission: "pending",
  reasons: ["来源关系待核对"],
  current: true,
};
const grouping: ResearchGroupingView = {
  sample_id: sample.id,
  source_group_id: "group",
  revision: 1,
  metadata: {
    template_key: null,
    near_duplicate_key: null,
    reviewed: false,
    reason: "尚未核对",
  },
  related_sample_ids: [sample.id],
  eligible_label_pair: false,
};
function json(data: unknown, status = 200, etag?: string) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json",
      ...(etag ? { ETag: etag } : {}),
    },
  });
}
beforeEach(() => {
  sessionStorage.clear();
});
it("真实技术零分保留为0，未知不记零；当前冲突不回退旧核验记录", () => {
  const first = render(<OutcomeCard outcome={outcome} current />);
  expect(screen.getByText("0")).toBeInTheDocument();
  expect(screen.getByText("存在核验冲突")).toBeInTheDocument();
  expect(screen.getByText("当前成绩记录")).toBeInTheDocument();
  first.unmount();
  render(
    <OutcomeCard
      outcome={{
        ...outcome,
        value: null,
        maximum: null,
        score_kind: "unknown",
      }}
      current={false}
    />,
  );
  expect(screen.getByText("未知")).toBeInTheDocument();
  expect(screen.queryByText("0")).not.toBeInTheDocument();
});
it("跨项目成绩响应被拒绝展示", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      json({
        items: [outcome],
        heads: [{ bid_id: "bid", outcome_id: outcome.id }],
      }),
    ),
  );
  render(<OutcomesPanel bidId="another-project" />);
  expect(
    await screen.findByText("成绩项目身份不一致，未展示其他项目数据。"),
  ).toBeInTheDocument();
  expect(screen.queryByText("存在核验冲突")).not.toBeInTheDocument();
});
it("研究来源分组412保留输入，明确比较后才能按新令牌保存；不会启动收费批次", async () => {
  const writes: RequestInit[] = [];
  let groupReads = 0;
  const transport = vi.fn(async (url: string, options?: RequestInit) => {
    if (url === "/api/v1/research/capabilities") return json(capabilities);
    if (url === "/api/v1/research/samples")
      return json({
        items: [sample],
        next_offset: null,
        formal_model_eligible: false,
      });
    if (url === "/api/v1/outcomes/outcome") return json(outcome);
    if (url === "/api/v1/research/samples/sample/grouping") {
      if (options?.method === "POST") {
        writes.push(options);
        return writes.length === 1
          ? json({ code: "REVISION_CONFLICT", message: "分组已变化" }, 412)
          : json({ ...grouping, revision: 3 }, 200, '"group-3"');
      }
      groupReads++;
      return groupReads === 1
        ? json(grouping, 200, '"group-1"')
        : json(
            {
              ...grouping,
              revision: 2,
              metadata: { ...grouping.metadata, reason: "另一成员核对" },
            },
            200,
            '"group-2"',
          );
    }
    throw new Error(`Unexpected ${url}`);
  });
  vi.stubGlobal("fetch", transport);
  render(<Research onOpen={vi.fn()} />);
  await userEvent.click(
    await screen.findByRole("button", { name: "核对样本依据与归组" }),
  );
  const reason = await screen.findByLabelText("核对依据与理由");
  await userEvent.clear(reason);
  await userEvent.type(reason, "根据官方样本逐条核对的本地说明");
  await userEvent.click(
    screen.getByRole("button", { name: "保存来源分组核对" }),
  );
  expect(
    await screen.findByText(
      "分组已被更新。当前输入保留，请先重新读取并比较，不自动覆盖其他成员决定。",
    ),
  ).toBeInTheDocument();
  expect(reason).toHaveValue("根据官方样本逐条核对的本地说明");
  await userEvent.click(
    screen.getByRole("button", { name: "读取最新分组并比较" }),
  );
  expect(await screen.findByText("另一成员核对")).toBeInTheDocument();
  expect(writes).toHaveLength(1);
  await userEvent.click(
    screen.getByRole("button", { name: "保留上述输入，按最新分组继续保存" }),
  );
  await userEvent.click(
    screen.getByRole("button", { name: "保存来源分组核对" }),
  );
  await waitFor(() => expect(writes).toHaveLength(2));
  expect(new Headers(writes[0].headers).get("If-Match")).toBe('"group-1"');
  expect(new Headers(writes[1].headers).get("If-Match")).toBe('"group-2"');
  expect(JSON.parse(writes[1].body as string).reason).toBe(
    "根据官方样本逐条核对的本地说明",
  );
  expect(
    transport.mock.calls.filter(([, options]) => options?.method === "POST"),
  ).toHaveLength(2);
});
