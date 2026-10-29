import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ReportPanel } from "./ReportPanel";
import { ArtifactActions } from "./ArtifactActions";
vi.mock("./contracts", async (original) => ({
  ...(await original<typeof import("./contracts")>()),
  implementedOperations: [
    "GET /api/v1/reviews/{id}",
    "GET /api/v1/reviews/{id}/report-context",
    "GET /api/v1/reviews/{id}/report-exports",
    "POST /api/v1/reviews/{id}/report-exports",
    "GET /api/v1/report-exports/{id}",
  ],
}));
const context = {
  review_id: "review",
  body_version_id: "historical-body",
  original_name: "历史实际受检稿.pdf",
  presentation_revision: 7,
  source_impact_revision: 2,
  context_digest: "a".repeat(64),
  current: false,
  source_state: "changed",
  supported: [
    { artifact_kind: "review_report", format: "docx" },
    { artifact_kind: "review_report", format: "pdf" },
    { artifact_kind: "annotated_review_copy", format: "pdf" },
  ],
};
const json = (value: unknown, status = 200, tag = '"report-context:7"') =>
  new Response(JSON.stringify(value), { status, headers: { ETag: tag } });
beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  vi.restoreAllMocks();
});
it("同项目的正文版本也不能经报告入口下载，取件前核对实际用途和媒体格式", async () => {
  const paths: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      paths.push(url);
      return json({
        id: "version",
        bid_id: "bid",
        artifact_kind: "bid_body",
        media_type: "application/pdf",
      });
    }),
  );
  render(
    <ArtifactActions
      bidId="bid"
      documentId="version"
      isPdf={true}
      expectedArtifactKind="review_report"
      expectedMediaType="application/pdf"
      downloadLabel="下载评审报告（PDF）"
    />,
  );
  await userEvent.click(
    screen.getByRole("button", { name: "下载评审报告（PDF）" }),
  );
  await screen.findByText(/文件用途或格式与此取件入口不一致/);
  expect(paths).toEqual(["/api/v1/documents/version"]);
});
it("先核评审项目身份，跨项目不请求context/历史或提供生成入口", async () => {
  const paths: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      paths.push(url);
      return json({ id: "review", bid_id: "another" });
    }),
  );
  render(
    <ReportPanel
      bidId="bid"
      memberId="member"
      reviewId="review"
      projectTitle="合成项目"
    />,
  );
  await screen.findByText("评审不属于当前项目，未读取其报告或生成副本。");
  expect(paths).toEqual(["/api/v1/reviews/review"]);
  expect(
    screen.queryByRole("button", { name: "生成此用途副本" }),
  ).not.toBeInTheDocument();
});
it("历史轮次保留指定原稿，PDF批注没有Word近似选项；仅真实副本成功后提供取件", async () => {
  const user = userEvent.setup();
  const writes: { body: unknown; tag: string | null }[] = [];
  let done = false;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        writes.push({
          body: JSON.parse(String(init.body)),
          tag: new Headers(init.headers).get("If-Match"),
        });
        return json(
          {
            resource_id: "report",
            resource_kind: "report",
            operation: { id: "op", bid_id: "bid" },
          },
          202,
        );
      }
      if (url.endsWith("/reviews/review"))
        return json({ id: "review", bid_id: "bid" });
      if (url.includes("report-context")) return json(context);
      if (url.includes("/report-exports/report"))
        return json({
          id: "report",
          review_id: "review",
          operation_id: "op",
          state: done ? "succeeded" : "running",
          artifact_kind: "annotated_review_copy",
          format: "pdf",
          presentation_revision: 7,
          source_impact_revision: 2,
          document_version_id: done ? "export-doc" : null,
          gaps: ["部分页面未能精确定位，批注采用物理整页"],
          error_code: null,
        });
      return json({ items: [], has_more: false, next_cursor: null });
    }),
  );
  render(
    <ReportPanel
      bidId="bid"
      memberId="member"
      reviewId="review"
      projectTitle="合成项目"
    />,
  );
  expect(await screen.findByText("历史实际受检稿.pdf")).toBeVisible();
  expect(screen.getByText(/历史固定输入，保留原受检稿/)).toBeVisible();
  expect(
    screen.queryByRole("option", { name: "批注审阅稿（Word）" }),
  ).not.toBeInTheDocument();
  await user.selectOptions(
    screen.getByLabelText("报告用途与格式"),
    "annotated_review_copy:pdf",
  );
  await user.click(screen.getByRole("button", { name: "生成此用途副本" }));
  await screen.findByText("正在生成");
  expect(
    screen.queryByRole("button", { name: "下载批注审阅稿（PDF）" }),
  ).not.toBeInTheDocument();
  expect(writes).toEqual([
    {
      body: {
        artifact_kind: "annotated_review_copy",
        format: "pdf",
        presentation_revision: 7,
        source_impact_revision: 2,
      },
      tag: '"report-context:7"',
    },
  ]);
  done = true;
  window.dispatchEvent(new Event("server-snapshot-change"));
  await screen.findByRole("button", { name: "下载批注审阅稿（PDF）" });
  expect(
    screen.getByText("部分页面未能精确定位，批注采用物理整页"),
  ).toBeVisible();
});
it("412不丢用途选择，显式重读后按新展示修订申请；未配置PDF转换可改Word", async () => {
  const user = userEvent.setup();
  let version = 7;
  let count = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        count++;
        if (count === 1) {
          version = 8;
          return json(
            { code: "REPORT_PRESENTATION_CHANGED", message: "展示政策已变化" },
            412,
          );
        }
        return json(
          { code: "REPORT_RENDERER_NOT_CONFIGURED", message: "可选择Word报告" },
          503,
        );
      }
      if (url.endsWith("/reviews/review"))
        return json({ id: "review", bid_id: "bid" });
      if (url.includes("report-context"))
        return json(
          { ...context, presentation_revision: version },
          200,
          `"report-context:${version}"`,
        );
      return json({ items: [], has_more: false, next_cursor: null });
    }),
  );
  render(
    <ReportPanel
      bidId="bid"
      memberId="member"
      reviewId="review"
      projectTitle="合成项目"
    />,
  );
  await screen.findByLabelText("报告用途与格式");
  await user.selectOptions(
    screen.getByLabelText("报告用途与格式"),
    "review_report:pdf",
  );
  await user.click(screen.getByRole("button", { name: "生成此用途副本" }));
  await screen.findByText("展示政策已变化");
  expect(screen.getByRole("button", { name: "生成此用途副本" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "重读报告展示依据" }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "生成此用途副本" }),
    ).toBeEnabled(),
  );
  expect(screen.getByLabelText("报告用途与格式")).toHaveValue(
    "review_report:pdf",
  );
  await user.click(screen.getByRole("button", { name: "生成此用途副本" }));
  await screen.findByText("可选择Word报告");
  await user.selectOptions(
    screen.getByLabelText("报告用途与格式"),
    "review_report:docx",
  );
  expect(screen.getByRole("button", { name: "生成此用途副本" })).toBeEnabled();
  expect(
    screen.queryByRole("button", { name: "恢复原报告申请结果" }),
  ).not.toBeInTheDocument();
});
