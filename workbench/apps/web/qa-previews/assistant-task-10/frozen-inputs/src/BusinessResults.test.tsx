import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, it, expect, vi } from "vitest";
import { BusinessResults } from "./BusinessResults";
import type { SubmissionView } from "./contracts";
const submission: SubmissionView = {
  id: "submission",
  bid_id: "bid",
  body_version_id: "body",
  review_id: null,
  kind: "offline_fact",
  submitted_at: "2020-01-01T00:00:00Z",
  recorded_by: "actor",
  gate_checked: false,
  evidence_ref: "body",
  current: true,
  supersedes_id: null,
  identity: {
    bidder_id: "company",
    bidder_name: "合成公司",
    round_id: "round",
    engineering_project_id: "project",
    engineering_title: "合成工程",
    region: null,
    engineering_type: null,
    lot: null,
    round_no: 1,
    binding_status: "confirmed",
    authority_id: "authority",
    digest: "digest",
  },
  original_name: "body.pdf",
  artifact_kind: "bid_body",
  checks_label: "未完整检查",
  open_risk_snapshot: null,
  platform_submission_verified: false,
  explanation: "合成机制",
  correction_reason: null,
};
const result = {
  id: "result",
  bid_id: "bid",
  submission_id: "submission",
  stage: "candidate",
  source_type: "user_reported",
  source_version_id: null,
  evidence_refs: [],
  announced_at: null,
  known_at: "2020-02-02T00:00:00Z",
  reason: "仅有候选公示，不能当中标",
  supersedes_id: null,
  correction_reason: null,
  created_by: "actor",
  created_at: "2020-02-02T00:00:00Z",
  verification: "pending",
  verification_authority_id: null,
  verification_details: null,
  head_revision: 1,
  head_authority_id: "authority",
  current: true,
  usable: true,
  unusable_reasons: [],
};
const page = (current: typeof result | null) => ({
  bid_id: "bid",
  submission_id: "submission",
  current_result: current,
  head_revision: current ? 1 : 0,
  head_authority_id: null,
  items: current ? [current] : [],
  next_offset: null,
  total: current ? 1 : 0,
});
const json = (body: unknown, tag = '"result:0"', status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ETag: tag } });
beforeEach(() => {
  sessionStorage.clear();
  vi.restoreAllMocks();
});
it("结果一次追加不自动核验；CAS失败保留候选输入并显式重读当前头", async () => {
  const u = userEvent.setup();
  let saved = false;
  let first = true;
  const writes: { body: Record<string, unknown>; tag: string | null }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        writes.push({
          body: JSON.parse(String(init.body)),
          tag: new Headers(init.headers).get("If-Match"),
        });
        if (first) {
          first = false;
          return json(
            { code: "PRECONDITION_FAILED", message: "头已变化" },
            "",
            412,
          );
        }
        saved = true;
        return json(result, '"result:1"', 201);
      }
      if (url.includes("submission-documents"))
        return json({ items: [], has_more: false, next_cursor: null });
      if (url.includes("business-results/")) return json(result, '"result:1"');
      return json(
        page(saved ? result : null),
        first ? '"result:0"' : '"result:changed"',
      );
    }),
  );
  render(
    <BusinessResults bidId="bid" memberId="member" submission={submission} />,
  );
  await u.click(
    screen.getByRole("button", { name: "登记／查看此实交的实际结果" }),
  );
  await u.click(await screen.findByRole("button", { name: "登记实际结果" }));
  await u.selectOptions(screen.getByLabelText("真实阶段"), "candidate");
  await u.type(screen.getByLabelText("实际获知时间"), "2020-02-02T00:00");
  await u.type(
    screen.getByLabelText("事实说明与来源理由"),
    "仅有候选公示，不能当中标",
  );
  await u.click(screen.getByRole("button", { name: "保存实际结果" }));
  await screen.findByText("头已变化");
  expect(screen.getByLabelText("真实阶段")).toHaveValue("candidate");
  expect(writes).toHaveLength(1);
  await u.click(
    screen.getByRole("button", { name: "读取当前结果依据，保留输入" }),
  );
  await u.click(screen.getByRole("button", { name: "保存实际结果" }));
  await screen.findByRole("button", { name: "追加更正实际结果" });
  expect(writes).toHaveLength(2);
  expect(writes[0].tag).toBe('"result:0"');
  expect(writes[1].tag).toBe('"result:changed"');
  expect(writes[1].body).toMatchObject({
    stage: "candidate",
    source_type: "user_reported",
    submission_id: "submission",
  });
  expect(screen.getAllByText("未核实报送").length).toBeGreaterThan(0);
  expect(screen.queryByText("已中标")).toBeNull();
});
it("pending实交身份只读；历史结果不借当前身份解锁新增", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => json(page(null))),
  );
  const u = userEvent.setup();
  render(
    <BusinessResults
      bidId="bid"
      memberId="member"
      submission={{ ...submission, identity: null }}
    />,
  );
  await u.click(
    screen.getByRole("button", { name: "登记／查看此实交的实际结果" }),
  );
  await screen.findByText(/新增结果需当前实际提交具有可靠/);
  expect(screen.queryByRole("button", { name: "登记实际结果" })).toBeNull();
});
it("普通用户报送不能一键核实成官方结果；服务端核实仍绑定强结果头", async () => {
  const writes: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") writes.push(init.body);
      if (url.includes("/business-results/result"))
        return json(result, '"result:1"');
      return json(page(result), '"result:1"');
    }),
  );
  const u = userEvent.setup();
  render(
    <BusinessResults bidId="bid" memberId="member" submission={submission} />,
  );
  await u.click(
    screen.getByRole("button", { name: "登记／查看此实交的实际结果" }),
  );
  await u.click(
    await screen.findByRole("button", { name: "核实／标注此结果" }),
  );
  await screen.findByText("缺少官方来源，请先追加更正结果内容。");
  expect(screen.getByRole("button", { name: "核实此结果" })).toBeDisabled();
  expect(writes).toHaveLength(0);
});
