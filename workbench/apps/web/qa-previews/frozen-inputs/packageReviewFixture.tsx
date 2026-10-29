import { useState } from "react";
import { createRoot } from "react-dom/client";
import PackageReviewProgress from "../../src/PackageReviewProgress";
import PackageReviewComparisonWorkspace from "../../src/PackageReviewComparisonWorkspace";
import PackageReviewReportExports from "../../src/PackageReviewReportExports";
import { packageReviewReportFixture } from "./packageReviewReport";
import {
  packageReviewComparisonFixture,
  packageReviewOriginalFetch,
} from "./packageReviewComparison";
import {
  packageReviewDecisionCurrent,
  packageReviewDecisionPage,
  packageReviewDecisionReply,
} from "./packageReviewDecision";
import { dependencyPlanPage } from "./dependencyPlan";
import type {
  PackageReviewHumanDecisionView,
  SavePackageReviewHumanDecision,
} from "../../src/contracts";
import "../../src/packageReview.css";
import "../../src/packageFrozenInput.css";

const f = await packageReviewReportFixture(),
  comparison = await packageReviewComparisonFixture();
const humans: PackageReviewHumanDecisionView[] = [];
const commands = new Map<string, { body: string; value: unknown }>();
let dropNext = false;
const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
window.fetch = async (input, options) => {
  const url = new URL(String(input), window.location.origin),
    path = url.pathname.replace(/^\/api\/v1/, "");
  if (path.endsWith("/package-review-comparisons"))
    return json(comparison.page());
  if (path.endsWith("/report-context")) return json(f.context);
  if (path.endsWith("/report-exports")) {
    if (options?.method === "POST") {
      const key = new Headers(options.headers).get("Idempotency-Key")!,
        body = String(options.body),
        previous = commands.get(key);
      if (previous && previous.body !== body)
        return json(
          { code: "IDEMPOTENCY_CONFLICT", message: "合成原报告请求不符" },
          409,
        );
      commands.set(key, { body, value: f.report });
      if (dropNext) {
        dropNext = false;
        throw new TypeError("合成报告回执已丢失");
      }
      return json(f.report, 202);
    }
    return json(f.page());
  }
  if (path.endsWith(`/report-exports/${f.report.id}`)) return json(f.completed);
  if (path.endsWith("/human-decisions")) {
    if (path.includes("/requirements/")) {
      const requirementId = path.split("/requirements/")[1].split("/")[0],
        index = f.f.completed.result!.manifest.matrix.findIndex(
          (row) => row.requirement_id === requirementId,
        );
      if (index < 0)
        return json({ code: "NOT_FOUND", message: "合成行不存在" }, 404);
      if (options?.method === "POST") {
        const key = new Headers(options.headers).get("Idempotency-Key")!,
          original = commands.get(key),
          text = String(options.body);
        if (original)
          return original.body === text
            ? json(original.value, 201)
            : json(
                { code: "IDEMPOTENCY_CONFLICT", message: "合成原人工请求不符" },
                409,
              );
        const body = JSON.parse(text) as SavePackageReviewHumanDecision,
          records = humans.filter(
            (row) => row.manifest.requirement_id === requirementId,
          );
        const value = await packageReviewDecisionReply(
          f.f,
          body,
          index,
          records.length + 1,
        );
        humans.push(value);
        commands.set(key, { body: text, value });
        return json(value, 201);
      }
      return json(
        await packageReviewDecisionPage(
          f.f,
          humans.filter((row) => row.manifest.requirement_id === requirementId),
          index,
        ),
      );
    }
    return json(await packageReviewDecisionCurrent(f.f, humans));
  }
  if (path.endsWith(`/review-runs/${f.f.run.id}/input`)) return json(f.f.input);
  if (path.endsWith(`/dependency-plans/${f.f.plan.manifest.id}`))
    return json(f.f.plan);
  if (path.endsWith("/dependency-plans"))
    return json(dependencyPlanPage(f.f, [f.f.plan]));
  const original =
    packageReviewOriginalFetch(comparison.left, path) ??
    packageReviewOriginalFetch(comparison.right, path);
  if (original) return json(original);
  throw new Error("本页面仅允许合成读写，不连接业务库、模型或私有原件。");
};
function Fixture() {
  const [mode, setMode] = useState("report"),
    [width, setWidth] = useState("1200"),
    [run, setRun] = useState(f.f.completed),
    [notice, setNotice] = useState("");
  return (
    <main
      className="package-review"
      style={{
        maxWidth: Number(width),
        margin: "auto",
        padding: 16,
        boxSizing: "border-box",
        overflowWrap: "anywhere",
      }}
    >
      <h2>整包核查、对比与报告副本 · 合成界面验收</h2>
      <p>
        使用真实组件和合成 HTTP
        响应，只验证界面、恢复与分页；不连接业务库，不调用模型，不提供真实原件或有效报告字节。
      </p>
      <div className="package-review__actions">
        <label>
          内容容器宽度
          <select
            value={width}
            onChange={(event) => setWidth(event.target.value)}
          >
            {["1200", "768", "390"].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
          验收页面
          <select
            value={mode}
            onChange={(event) => setMode(event.target.value)}
          >
            <option value="report">核查结果与人工意见</option>
            <option value="comparison">两轮对比</option>
            <option value="exports">报告生成与恢复</option>
          </select>
        </label>
      </div>
      <p className="muted">
        对比左侧编号：{comparison.request.leftId}；右侧编号：
        {comparison.request.rightId}。容器宽度检查不等同于完整手机视口验收。
      </p>
      <button
        type="button"
        className="button secondary"
        onClick={() => {
          dropNext = true;
          setNotice("下一份合成报告申请故意丢回执，可按原请求恢复。");
        }}
      >
        下一份报告模拟丢回执
      </button>
      {notice && <p role="status">{notice}</p>}
      {mode === "report" && (
        <PackageReviewProgress {...f.f.props} run={run} onChange={setRun} />
      )}
      {mode === "comparison" && (
        <PackageReviewComparisonWorkspace
          memberId={f.f.props.scope.memberId}
          bidId={f.f.props.scope.bidId}
          currentRun={comparison.right.completed}
        />
      )}
      {mode === "exports" && (
        <PackageReviewReportExports {...f.f.props} run={f.f.completed} />
      )}
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<Fixture />);
