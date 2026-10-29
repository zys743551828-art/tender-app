import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { PricingPanel } from "./PricingPanel";
import { PricingResults } from "./PricingResults";
import { pricingInputDigest } from "./pricingInput";
import type {
  PricingFrozenResult,
  PricingFormulaManifest,
  PricingRequest,
} from "./contracts";
const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
  "node:crypto",
);

vi.mock("./contracts", async (original) => ({
  ...(await original<typeof import("./contracts")>()),
  implementedOperations: [
    "GET /api/v1/bids/{bid_id}/settings",
    "GET /api/v1/bids/{bid_id}/pricing-context",
    "GET /api/v1/bids/{bid_id}/pricing-formula-sources",
    "GET /api/v1/bids/{bid_id}/pricing-formulas",
    "POST /api/v1/bids/{bid_id}/pricing-formulas",
    "GET /api/v1/bids/{bid_id}/pricing-formulas/{id}",
    "POST /api/v1/bids/{bid_id}/pricing-simulations",
    "POST /api/v1/bids/{bid_id}/pricing-plans",
    "GET /api/v1/bids/{bid_id}/pricing-plans",
    "GET /api/v1/bids/{bid_id}/pricing-plans/{id}",
  ],
}));
const manifest = {
  schema: "pricing-formula/1",
  bid_id: "bid",
  formula_version_id: "formula",
  title: "合成最低比值法",
  amount_unit: "万元",
  currency: "CNY",
  rounding_policy: "half_up_2dp",
  confirmed_at: "2020-01-01T00:00:00Z",
  evidence_quotes: [],
  material_snapshot_id: null,
  material_revision: 1,
  applicability_scope: {
    bid_id: "bid",
    round_id: "round",
    effective_documents: [],
  },
  interpretation: {
    baseline_set: "own_and_all_numerically_eligible_assumptions",
    exclusions: "none",
    random_parameters: "none",
    intermediate_rounding: "none",
    clamping: "zero_to_maximum",
  },
  terms_complete_confirmed: true,
  matches_source_confirmed: true,
  reason: "明确合成机制夹具",
  confirmed_by: "actor",
  calculator: {
    name: "bounded-decimal-price-calculator",
    version: 1,
    implementation_sha256: "e".repeat(64),
  },
  source_authority: {
    scope: { bid_id: "bid", round_id: "round", effective_documents: [] },
    ancestor_heads: [],
  },
  formula: {
    method: "lowest_valid_ratio",
    maximum: "30",
    minimum_price: null,
    maximum_price: null,
    minimum_valid_bids: 3,
    above_coefficient: "0",
    below_coefficient: "0",
  },
} satisfies PricingFormulaManifest;
const formula = {
  formula_version_id: "formula",
  formula_digest: "d".repeat(64),
  formula: manifest,
  current_applicability: { applicable: true, reasons: [] },
};
const json = (value: unknown, tag = '"formula:1"', status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { ETag: tag } });
const request: PricingRequest = {
  formula_version_id: "formula",
  candidate_price: "100.00",
  competitor_price_assumptions: ["90", "90"],
  rounding_policy: "half_up_2dp",
  candidate_prices: [],
  curve_range: null,
  amount_unit: "万元",
  currency: "CNY",
};
async function simulation(input: PricingRequest) {
  return {
    id: `sim-${input.candidate_price}`,
    formula_version_id: "formula",
    formula_digest: formula.formula_digest,
    input_digest: await pricingInputDigest(input, formula.formula_digest),
    formula_evidence_ids: [],
    price_score: null,
    eligible: true,
    notes: ["有效报价假设数量不足"],
    candidate_price: input.candidate_price,
    maximum: "30",
    baseline_price: null,
    valid_price_count: 1,
    candidates: [],
    curve: [],
    calculation_steps: [],
    assumptions: [],
    technical_exchange_note: "不能直接换算技术分",
    excluded_competitor_assumptions: [],
    input,
    formula_snapshot: manifest,
    created_by: "actor",
    created_at: "2020-01-01T00:00:00Z",
    current_applicability: { applicable: true, reasons: [] },
  };
}
function reads(url: string, enabled = true): Response {
  if (url.endsWith("/settings"))
    return json({ bid_id: "bid", revision: 1, settings: { pricing: enabled } });
  if (url.includes("pricing-formulas/formula")) return json(formula);
  if (url.includes("pricing-formulas"))
    return json({
      items: [{ ...formula, title: manifest.title }],
      next_cursor: null,
    });
  if (url.includes("pricing-plans"))
    return json({ items: [], next_cursor: null });
  throw new Error("unexpected read");
}
beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  vi.restoreAllMocks();
  vi.stubGlobal("crypto", webcrypto);
});

it("本地input digest与后端规范JSON SHA一致，重复对手假设不去重", async () => {
  expect(await pricingInputDigest(request, formula.formula_digest)).toBe(
    "c796c86b3a2f087622bea3ca2e7e5c4dba7efff4b40c789f6efbe6c17f37fb13",
  );
});
it("关闭模块时直接链接不请求公式/结果，历史不删除、不自动执行", async () => {
  const paths: string[] = [];
  const settings = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      paths.push(url);
      return reads(url, false);
    }),
  );
  render(<PricingPanel bidId="bid" memberId="member" onSettings={settings} />);
  await screen.findByText("本项目报价辅助已关闭");
  expect(paths).toEqual(["/api/v1/bids/bid/settings"]);
  await userEvent.click(
    screen.getByRole("button", { name: "在项目设置中开启报价辅助" }),
  );
  expect(settings).toHaveBeenCalledOnce();
});
it("400ms情景更新保持dirty输入，迟到旧响应不替换新情景，未知分数不变零且试算不保存方案", async () => {
  const user = userEvent.setup();
  let release: (value: Response) => void = () => {};
  const writes: PricingRequest[] = [];
  let saves = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        if (url.endsWith("pricing-plans")) {
          saves++;
          return json({});
        }
        const input = JSON.parse(String(init.body)) as PricingRequest;
        writes.push(input);
        if (writes.length === 1)
          return new Promise<Response>((done) => {
            release = done;
          });
        return json(await simulation(input), '"simulation:new"', 201);
      }
      return reads(url);
    }),
  );
  render(<PricingPanel bidId="bid" memberId="member" onSettings={vi.fn()} />);
  await screen.findByRole("option", { name: /合成最低比值法/ });
  await user.selectOptions(
    await screen.findByLabelText("选择已确认公式"),
    "formula",
  );
  const candidate = await screen.findByLabelText("本方候选报价");
  await user.type(candidate, "100");
  await user.click(screen.getByRole("button", { name: "试算当前情景" }));
  await waitFor(() => expect(writes).toHaveLength(1));
  await user.clear(candidate);
  await user.type(candidate, "110");
  release(json(await simulation(writes[0]), '"simulation:old"', 201));
  await waitFor(() => expect(writes).toHaveLength(2));
  await screen.findByText(/本方 110 万元/);
  expect(candidate).toHaveValue("110");
  expect(screen.getByText("未知", { selector: "strong" })).toBeVisible();
  expect(screen.queryByText(/本方 100 万元/)).not.toBeInTheDocument();
  expect(screen.getByText("符合本公式价格区间")).toBeVisible();
  expect(saves).toBe(0);
  await user.clear(candidate);
  await user.type(candidate, "120");
  expect(screen.getByText(/以下保留上次结果，待更新/)).toBeVisible();
  expect(
    screen.getByRole("button", { name: "保存当前情景方案" }),
  ).toBeDisabled();
});
it("设置响应缺字段时保留核心页面，不冒充已开启/已关闭，也不读取报价结果", async () => {
  const paths: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      paths.push(url);
      return json({ bid_id: "bid", revision: 1 });
    }),
  );
  render(<PricingPanel bidId="bid" memberId="member" onSettings={vi.fn()} />);
  await screen.findByText("报价设置尚未完整核对");
  expect(paths).toEqual(["/api/v1/bids/bid/settings"]);
  expect(screen.queryByText("本项目报价辅助已关闭")).not.toBeInTheDocument();
});
it("未知曲线点断开且真实零保留；每点展示自己的基准价与有效数", () => {
  const point = (price: string, score: string | null, baseline: string) => ({
    price,
    score,
    eligible: true,
    notes: score === null ? ["数量不足"] : [],
    baseline_price: baseline,
    valid_price_count: 2,
    calculation_steps: [`本点基准=${baseline}`],
  });
  const result = {
    id: "sim",
    formula_version_id: "formula",
    formula_digest: "d".repeat(64),
    input_digest: "a".repeat(64),
    formula_evidence_ids: [],
    price_score: "0.00",
    eligible: true,
    notes: [],
    candidate_price: "100",
    maximum: "30",
    baseline_price: "80",
    valid_price_count: 2,
    candidates: [],
    curve: [
      point("90", "20", "80"),
      point("100", null, "85"),
      point("110", "0.00", "90"),
    ],
    calculation_steps: [],
    assumptions: [],
    technical_exchange_note: "不换算技术分",
    excluded_competitor_assumptions: [],
  } satisfies PricingFrozenResult;
  const { container } = render(
    <PricingResults result={result} input={request} formula={manifest} />,
  );
  expect(screen.getByText("0.00", { selector: "strong" })).toBeVisible();
  expect(container.querySelectorAll("polyline")).toHaveLength(2);
  expect(screen.getByText("价格分 未知")).toBeInTheDocument();
  expect(screen.getByText(/基准价 85/)).toBeInTheDocument();
});
it("来源变化409阻止自动重试，保留本方/对手输入，明确核对后才继续", async () => {
  const user = userEvent.setup();
  let count = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        count++;
        return json(
          { code: "PRICING_SOURCE_CHANGED", message: "原文量尺已变化" },
          '"tag"',
          409,
        );
      }
      return reads(url);
    }),
  );
  render(<PricingPanel bidId="bid" memberId="member" onSettings={vi.fn()} />);
  await screen.findByRole("option", { name: /合成最低比值法/ });
  await user.selectOptions(
    await screen.findByLabelText("选择已确认公式"),
    "formula",
  );
  await user.type(await screen.findByLabelText("本方候选报价"), "100");
  await user.type(
    screen.getByLabelText("对手报价假设（每行一个，最多200项）"),
    "90\n90",
  );
  await user.click(screen.getByRole("button", { name: "试算当前情景" }));
  await screen.findByText("原文量尺已变化");
  await user.type(screen.getByLabelText("本方候选报价"), "1");
  await new Promise((done) => setTimeout(done, 450));
  expect(count).toBe(1);
  expect(
    screen.getByLabelText("对手报价假设（每行一个，最多200项）"),
  ).toHaveValue("90\n90");
  expect(screen.getByRole("button", { name: "试算当前情景" })).toBeDisabled();
  await user.click(
    screen.getByRole("button", { name: "重新核对公式依据，保留情景" }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "试算当前情景" })).toBeEnabled(),
  );
  expect(count).toBe(1);
});

it("保存条件412后旧模拟不能再次保存，重读公式后仍须明确重新试算取得新条件", async () => {
  const user = userEvent.setup();
  let simulations = 0;
  let saves = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        if (url.endsWith("pricing-plans")) {
          saves++;
          return json(
            { code: "REVISION_CONFLICT", message: "情景保存条件已变化" },
            '"current-simulation"',
            412,
          );
        }
        simulations++;
        const input = JSON.parse(String(init.body)) as PricingRequest;
        return json(
          { ...(await simulation(input)), id: `simulation-${simulations}` },
          `"simulation:${simulations}"`,
          201,
        );
      }
      return reads(url);
    }),
  );
  render(<PricingPanel bidId="bid" memberId="member" onSettings={vi.fn()} />);
  await screen.findByRole("option", { name: /合成最低比值法/ });
  await user.selectOptions(screen.getByLabelText("选择已确认公式"), "formula");
  await user.type(await screen.findByLabelText("本方候选报价"), "100");
  await user.click(screen.getByRole("button", { name: "试算当前情景" }));
  await screen.findByText("未知", { selector: "strong" });
  await user.type(
    screen.getByLabelText("保存此情景的理由"),
    "保存未知分数及数量缺口",
  );
  await user.click(screen.getByRole("button", { name: "保存当前情景方案" }));
  await screen.findByText("情景保存条件已变化");
  expect(
    screen.getByRole("button", { name: "保存当前情景方案" }),
  ).toBeDisabled();
  await user.click(
    screen.getByRole("button", { name: "重新核对公式依据，保留情景" }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "试算当前情景" })).toBeEnabled(),
  );
  expect(
    screen.getByRole("button", { name: "保存当前情景方案" }),
  ).toBeDisabled();
  expect(screen.getByLabelText("本方候选报价")).toHaveValue("100");
  expect(screen.getByLabelText("保存此情景的理由")).toHaveValue(
    "保存未知分数及数量缺口",
  );
  await user.click(screen.getByRole("button", { name: "试算当前情景" }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "保存当前情景方案" }),
    ).toBeEnabled(),
  );
  expect(simulations).toBe(2);
  expect(saves).toBe(1);
});
