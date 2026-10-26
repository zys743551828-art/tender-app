import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "./api";
import { PackagePredictionPipeline } from "./PackagePredictionPipeline";
vi.mock("./api", async (load) => ({
  ...(await load<typeof import("./api")>()),
  api: vi.fn(),
}));
const p = { bidId: "bid", scopeId: "scope", memberId: "member" };
const id = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa";
function result(state = "queued", extra: object = {}) {
  return {
    data: {
      schema: "package-prediction-pipeline/1",
      actor_id: p.memberId,
      bid_id: p.bidId,
      scope_id: p.scopeId,
      state,
      command_id: id,
      certificate_id: id,
      review_id: id,
      context_digest: "a".repeat(64),
      report_ready: state === "ready",
      provider_requests: 0,
      ...extra,
    },
    etag: null,
  };
}
beforeEach(() => vi.mocked(api).mockReset());
it("recovers existing intent and uses its selected review in the unified report", async () => {
  vi.mocked(api)
    .mockResolvedValueOnce(result())
    .mockResolvedValueOnce(result("ready"));
  render(<PackagePredictionPipeline {...p} />);
  await screen.findByText("预测已排队");
  fireEvent.click(screen.getByText("恢复已有评审意图"));
  await screen.findByText(/四部分统一报告可生成/);
  expect(screen.getByLabelText("完成评审编号")).toHaveValue(id);
  expect(vi.mocked(api).mock.calls[1][1]).toMatchObject({
    method: "POST",
    body: {},
  });
  vi.mocked(api).mockResolvedValueOnce({
    data: {
      schema: "package-unified-review-report/1",
      snapshot_id: "b".repeat(64),
      bid_id: p.bidId,
      scope_id: p.scopeId,
      command_id: id,
      review_id: id,
      sections: [
        ["一、核查", []],
        ["二、问题", []],
        ["三、可能的失分点", []],
        ["四、报价", ["未知"]],
      ],
      documents: [],
      matrix: [],
    },
    etag: null,
  });
  fireEvent.click(screen.getByText("复验统一报告"));
  await screen.findByText("四、报价");
  expect(vi.mocked(api).mock.calls[2][0]).toContain(`review_id=${id}`);
  expect(screen.queryByText(/正式预测：/)).toBeNull();
});
it.each([
  { actor_id: "other" },
  { scope_id: "other" },
  { report_ready: true },
  { context_digest: "invalid" },
])("rejects malformed or foreign pipeline result", async (extra) => {
  vi.mocked(api).mockResolvedValue(result("queued", extra));
  render(<PackagePredictionPipeline {...p} />);
  await screen.findByText(/自动预测回执身份/);
  expect(screen.queryByText("预测已排队")).toBeNull();
});
it("discards late status after switching scope and never shows stale report", async () => {
  let finish!: (r: ReturnType<typeof result>) => void;
  vi.mocked(api)
    .mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    )
    .mockResolvedValueOnce(
      result("waiting_start", {
        scope_id: "next",
        command_id: null,
        certificate_id: null,
        review_id: null,
        context_digest: null,
      }),
    );
  const view = render(<PackagePredictionPipeline {...p} />);
  view.rerender(<PackagePredictionPipeline {...p} scopeId="next" />);
  await act(async () => finish(result("ready")));
  await screen.findByText("等待从现有核查入口开始评审");
  expect(screen.queryByLabelText("完成评审编号")).toBeNull();
});
it("cancels the exact immutable command and clears report on refresh", async () => {
  vi.mocked(api)
    .mockResolvedValueOnce(result())
    .mockResolvedValueOnce(result("cancelled"));
  render(<PackagePredictionPipeline {...p} />);
  await screen.findByText("预测已排队");
  fireEvent.click(screen.getByText("取消自动预测意图"));
  await screen.findByText("预测意图已取消");
  expect(vi.mocked(api).mock.calls[1][1]).toMatchObject({
    method: "POST",
    body: { command_id: id },
  });
});
it("shows ambiguity without presenting an arbitrary candidate", async () => {
  vi.mocked(api).mockResolvedValue(
    result("certificate_ambiguous", {
      command_id: null,
      certificate_id: null,
      review_id: null,
      context_digest: null,
    }),
  );
  render(<PackagePredictionPipeline {...p} />);
  await screen.findByText("存在多个合格认证，已阻止自动选择");
  expect(screen.queryByLabelText("完成评审编号")).toBeNull();
});

it("is composed in the existing project material workspace", async () => {
  const { PackageMaterialExecution } = await import(
    "./PackageMaterialExecution"
  );
  const raw = await import("./test-fixtures/technical-execution-http.json");
  const saved = raw.default
    .scope as unknown as import("./contracts").PackageTechnicalScopeView;
  const bid = saved.manifest.preview.manifest.scope.bid_id;
  vi.mocked(api).mockResolvedValue(
    result("waiting_review", {
      bid_id: bid,
      scope_id: saved.manifest.id,
      command_id: null,
      certificate_id: null,
      review_id: null,
      context_digest: null,
    }),
  );
  render(<PackageMaterialExecution saved={saved} memberId={p.memberId} />);
  await screen.findByText("等待本冻结范围的核查完成");
  expect(screen.getByLabelText("完整材料执行申请")).toBeTruthy();
  expect(vi.mocked(api).mock.calls[0][0]).toBe(
    `/bids/${bid}/technical-scopes/${saved.manifest.id}/prediction-pipeline`,
  );
});
