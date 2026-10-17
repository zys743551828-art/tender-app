import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { PricingFormulaEditor } from "./PricingFormulaEditor";
import type { PricingContext } from "./contracts";
vi.mock("./contracts", async (original) => ({
  ...(await original<typeof import("./contracts")>()),
  implementedOperations: [
    "GET /api/v1/bids/{bid_id}/pricing-formula-sources",
    "POST /api/v1/bids/{bid_id}/pricing-formulas",
    "GET /api/v1/bids/{bid_id}/pricing-context",
  ],
}));
it("原页逐字段选择使用可信身份，一次登记被单位证据拒绝后保留参数/摘录，不声称成功", async () => {
  sessionStorage.clear();
  const user = userEvent.setup();
  const saved = vi.fn();
  const writes: { body: Record<string, unknown>; tag: string | null }[] = [];
  const quote =
    "以最低有效报价为基准，满分30，至少1家，本方及全部数值有效假设共同形成集合，不去极值，不作中间取整，最终四舍五入保留两位并限制0至30。金额单位：兆元，币种人民币。";
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        writes.push({
          body: JSON.parse(String(init.body)),
          tag: new Headers(init.headers).get("If-Match"),
        });
        return new Response(
          JSON.stringify({
            code: "PRICING_UNIT_WITHOUT_EVIDENCE",
            message: "完整单位声明不支持万元",
            details: { field: "amount_unit" },
          }),
          { status: 422 },
        );
      }
      return new Response(
        JSON.stringify({
          items: [
            {
              source_id: "trusted-source",
              source_revision: 7,
              document_version_id: "tender-version",
              parse_id: "trusted-parse",
              physical_page: 3,
              evidence_id: "trusted-evidence",
              filename: "计价条款.pdf",
              quote,
              source_registered: true,
            },
          ],
          next_cursor: null,
        }),
      );
    }),
  );
  const context: PricingContext = {
    bid_id: "bid",
    material_snapshot_id: "snapshot",
    material_revision: 3,
    scope: { bid_id: "bid", round_id: "round", effective_documents: [] },
    parses: [],
    source_heads: [],
  };
  render(
    <PricingFormulaEditor
      bidId="bid"
      memberId="member"
      initialContext={{ data: context, etag: '"pricing-context:3"' }}
      onSaved={saved}
      onClose={vi.fn()}
    />,
  );
  await user.type(screen.getByLabelText("公式标题"), "合成单位反例");
  await user.selectOptions(
    screen.getByLabelText("原文基准价方法"),
    "lowest_valid_ratio",
  );
  await user.type(screen.getByLabelText("价格满分"), "30");
  await user.type(screen.getByLabelText("最少有效报价数（包含本方）"), "1");
  await user.click(
    screen.getByRole("checkbox", { name: "已核对原文无最低价格边界" }),
  );
  await user.click(
    screen.getByRole("checkbox", { name: "已核对原文无最高价格边界" }),
  );
  await user.selectOptions(screen.getByLabelText("完整原文金额单位"), "万元");
  await user.selectOptions(screen.getByLabelText("原文币种"), "CNY");
  await user.selectOptions(
    screen.getByLabelText("原文最终取整规则"),
    "half_up_2dp",
  );
  await user.click(
    await screen.findByRole("checkbox", { name: /使用此原文出处/ }),
  );
  const labels = [
    "基准价方法",
    "价格满分",
    "最低价格边界",
    "最高价格边界",
    "最少有效报价数",
    "完整金额单位声明",
    "币种声明",
    "最终取整规则",
    "基准价有效集合",
    "不作去极值等排除",
    "不作中间取整",
    "分数限制于零至满分",
  ];
  for (const name of labels)
    await user.click(screen.getByRole("checkbox", { name }));
  expect(screen.queryByRole("checkbox", { name: "高于基准价系数" })).toBeNull();
  expect(screen.queryByRole("checkbox", { name: "低于基准价系数" })).toBeNull();
  await user.click(screen.getByRole("checkbox", { name: /已核对完整条款/ }));
  await user.click(
    screen.getByRole("checkbox", { name: /原文与受限参数完全一致/ }),
  );
  await user.type(
    screen.getByLabelText("参数对应原文的解释"),
    "明确合成反例：原文兆元不能按万元近似",
  );
  await user.click(screen.getByRole("button", { name: "确认并登记公式" }));
  await screen.findByText("完整单位声明不支持万元");
  expect(writes).toHaveLength(1);
  const evidence = writes[0].body.evidence_quotes as {
    supported_fields: string[];
  }[];
  expect(evidence[0].supported_fields).not.toContain("above_coefficient");
  expect(evidence[0].supported_fields).not.toContain("below_coefficient");
  expect(writes[0].tag).toBe('"pricing-context:3"');
  expect(writes[0].body).toMatchObject({
    terms_complete_confirmed: true,
    matches_source_confirmed: true,
    amount_unit: "万元",
    formula: {
      method: "lowest_valid_ratio",
      above_coefficient: "0",
      below_coefficient: "0",
    },
    evidence_quotes: [
      {
        source_id: "trusted-source",
        source_revision: 7,
        document_version_id: "tender-version",
        parse_id: "trusted-parse",
        physical_page: 3,
        evidence_id: "trusted-evidence",
        quote,
      },
    ],
  });
  expect(screen.getByLabelText("公式标题")).toHaveValue("合成单位反例");
  expect(
    screen.getByLabelText("逐字引文（保留完整计分及量尺声明）"),
  ).toHaveValue(quote);
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "确认并登记公式" }),
    ).toBeEnabled(),
  );
  expect(saved).not.toHaveBeenCalled();
  expect(
    screen.getByRole("button", { name: "重新核对生效资料，保留全部输入" }),
  ).toBeVisible();
});
