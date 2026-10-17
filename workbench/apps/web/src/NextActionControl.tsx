import type { NextAction } from "./contracts";
import { actionTarget } from "./workspaceTypes";
import type { WorkspacePage } from "./workspaceTypes";

export function NextActionControl({
  bidId,
  action,
  onNavigate,
}: {
  bidId: string;
  action: NextAction;
  onNavigate: (page: WorkspacePage, reviewId?: string) => void;
}) {
  const target = actionTarget(bidId, action);
  if (!target)
    return (
      <p className="small-note">
        此待办暂不能直接打开，请从工作区查看对应记录；已知风险与缺口不会据此清除。
      </p>
    );
  const label: Record<WorkspacePage, string> = {
    materials: "上传与核对资料",
    authoring: "打开章节编制",
    pricing: "查看报价情景",
    outcomes: "查看实交与成绩",
    review: "查看风险与本轮处理",
    matrix: "打开本轮响应矩阵",
    rules: "核对当前规则",
    facts: "核对工程事实",
    settings: "查看项目设置",
    overview: "查看当前项目",
    operations: "查看真实处理进度",
    tasks: "查看可复用任务",
  };
  return (
    <>
      <button
        className="button primary"
        onClick={() => {
          onNavigate(target.page, target.reviewId);
          if (target.page === "review")
            window.requestAnimationFrame(() =>
              window.document
                .getElementById("review-findings")
                ?.scrollIntoView({ behavior: "smooth", block: "start" }),
            );
        }}
      >
        {label[target.page]}
      </button>
      {action.blocked && (
        <p className="small-note">
          存在待处理阻断。可以打开定位；不表示已经符合继续执行或提交条件。
        </p>
      )}
    </>
  );
}
