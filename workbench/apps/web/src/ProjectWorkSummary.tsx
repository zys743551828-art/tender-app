import type { ProjectWorkSummary as Summary } from "./contracts";
import { ErrorNotice } from "./components";
import { summaryPage } from "./projectSummaries";
import { useProjectSummaries } from "./useProjectSummaries";

export function ProjectPackageCounts({ summary }: { summary?: Summary }) {
  if (!summary) return <span className="small-note">整包摘要待核对</span>;
  return (
    <div>
      <span>
        依据包 {summary.package_counts.authority} · 投标包{" "}
        {summary.package_counts.bid}
      </span>
      <p className="small-note">
        当前包修订共 {summary.head_members.total} 个文件成员
        {summary.head_members.parse_not_frozen > 0 &&
          `，${summary.head_members.parse_not_frozen} 个解析身份未冻结`}
      </p>
    </div>
  );
}

export function ProjectWorkSummary({
  bidId,
  onNavigate,
}: {
  bidId: string;
  onNavigate: (page: "packages" | "work-context") => void;
}) {
  const resource = useProjectSummaries([bidId]);
  const summary = resource.items.get(bidId);
  return (
    <section className="panel" aria-label="项目整包摘要">
      <div className="section-heading">
        <h2>整包工作概况</h2>
        <button
          className="text-button"
          onClick={() => void resource.reload()}
          disabled={resource.loading}
        >
          重新核对摘要
        </button>
      </div>
      <ErrorNotice error={resource.error} />
      <ProjectPackageCounts summary={summary} />
      <p className="small-note">
        登记数量与解析身份不代表资料齐全；当前整包风险和技术预测仍须选择确切输入后核对。
      </p>
      {summary && (
        <>
          <p>{summary.next_action.reason}</p>
          <button
            className="button primary"
            onClick={() => onNavigate(summaryPage(summary))}
          >
            {summaryPage(summary) === "work-context"
              ? "查看历史工作记录"
              : "打开整包工作面"}
          </button>
        </>
      )}
    </section>
  );
}
