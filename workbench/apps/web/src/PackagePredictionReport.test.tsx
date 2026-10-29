import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api, objectFetch } from "./api";
import { PackagePredictionReport } from "./PackagePredictionReport";
vi.mock("./api", async (load) => ({
  ...(await load<typeof import("./api")>()),
  api: vi.fn(),
  objectFetch: vi.fn(),
}));
vi.mock("./PackageReviewEvidence", () => ({
  default: () => <span>原件入口</span>,
}));
const p = {
  bidId: "bid",
  scopeId: "scope",
  commandId: "cmd",
  certificateId: "cert",
};
function report(extra: object = {}) {
  return {
    data: {
      schema: "package-formal-prediction-report/1",
      command_id: p.commandId,
      bid_id: p.bidId,
      scope_id: p.scopeId,
      certificate_id: p.certificateId,
      state: "hidden",
      score: null,
      limitations: ["逐字引文"],
      topics: [
        {
          rule_id: "rule",
          observations: { specificity: "supported" },
          rule_maximum: null,
          observed_band_gap: null,
          evidence: [
            {
              evidence_id: "e",
              document_version_id: "d",
              parse_run_id: "r",
              physical_page: 1,
              quote: "原文",
              file_digest: "a".repeat(64),
            },
          ],
        },
      ],
      ...extra,
    },
    etag: null,
    headers: new Headers(),
  };
}
beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(objectFetch).mockReset();
});
it("shows hidden evidence without score fields and invalidates parent snapshot first", async () => {
  const refresh = vi.fn();
  vi.mocked(api).mockResolvedValue(report());
  render(<PackagePredictionReport {...p} onRefresh={refresh} />);
  fireEvent.click(screen.getByText("复验并查看预测报告"));
  expect(refresh).toHaveBeenCalledOnce();
  await screen.findByText("原文");
  expect(screen.getByText("原件入口")).toBeTruthy();
  expect(screen.queryByText(/条款满分/)).toBeNull();
});
it.each([
  { certificate_id: "wrong" },
  { score: { value: "50" } },
  { topics: [null] },
])("rejects malformed or leaking projection", async (extra) => {
  vi.mocked(api).mockResolvedValue(report(extra));
  render(<PackagePredictionReport {...p} />);
  fireEvent.click(screen.getByText("复验并查看预测报告"));
  await screen.findByText(/报告身份或隐藏设置不匹配/);
  expect(screen.queryByText("原文")).toBeNull();
});
it("discards responses after scope switch", async () => {
  let finish!: (v: ReturnType<typeof report>) => void;
  vi.mocked(api).mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  const view = render(<PackagePredictionReport {...p} />);
  fireEvent.click(screen.getByText("复验并查看预测报告"));
  view.rerender(<PackagePredictionReport {...p} scopeId="other" />);
  await act(async () => {
    finish(report());
  });
  expect(screen.queryByText("原文")).toBeNull();
});
it.each([409, 200])(
  "never downloads rejected or cacheable Word bytes (%s)",
  async (status) => {
    vi.mocked(objectFetch).mockResolvedValue(
      new Response("old", {
        status,
        headers: {
          "content-type":
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
      }),
    );
    render(<PackagePredictionReport {...p} />);
    fireEvent.click(screen.getByText("复验并下载 Word 报告"));
    await screen.findByText(/未下载旧文件/);
    expect(objectFetch).toHaveBeenCalledWith(
      expect.stringContaining("report.docx"),
      { cache: "no-store" },
    );
  },
);
