import { lazy, Suspense, useState } from "react";
import type {
  AssistantAction,
  RunView,
  TaskAuthoringResult,
} from "./contracts";
import { ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import {
  readTaskAuthoringProposal,
  taskAuthoringScope,
} from "./taskAuthoringProtocol";

const AssistantPatchComparison = lazy(() =>
  import("./AssistantPatchComparison").then((m) => ({
    default: m.AssistantPatchComparison,
  })),
);

const actionState: Record<AssistantAction["state"], string> = {
  pending: "待明确处理",
  executed: "已记录明确处理结果",
  rejected: "已拒绝",
  expired: "已到期",
  stale: "依据已变化，未应用",
  failed: "处理失败",
};

function explanation(state: RunView["state"], result: TaskAuthoringResult) {
  if (result.publication_state === "published")
    return "原生章节提案已发布。本任务记录的是提案发布结果，正文是否采纳以持久操作卡为准。";
  if (state === "awaiting_publication")
    return "模型候选已保存，正在等待原生提案发布。此时任务尚未成功，也不会发送完成通知。";
  if (result.publication_state === "stale")
    return "发布前章节、事实或来源依据已变化，原候选未发布为可采纳提案。请重新核对输入。";
  if (result.publication_state === "failed")
    return "原生提案发布失败；未把模型步骤完成当作任务成功。";
  if (state === "cancelled") return "原章节任务已取消，没有发布可采纳提案。";
  if (state === "failed") return "原生处理失败，没有发布可采纳提案。";
  if (state === "reconciliation_required")
    return "原调用费用待核对，没有可确认发布的章节提案；不能通过新运行标识重复付费。";
  return "已绑定原生章节任务，尚无已发布提案。";
}

function Proposal({
  bidId,
  result,
  taskStale,
}: {
  bidId: string;
  result: TaskAuthoringResult;
  taskStale: boolean;
}) {
  const resource = useResource<AssistantAction>(
    `/assistant/actions/${result.action_id}`,
  );
  let action = null,
    error: unknown = null;
  if (resource.data) {
    try {
      action = readTaskAuthoringProposal(resource.data, result, bidId);
    } catch (caught) {
      error = caught;
    }
  }
  const stale = taskStale || resource.loading || !!resource.error;
  return (
    <section aria-label="本任务原生章节提案">
      <ResourceState
        {...resource}
        hasData={!!action}
        onRetry={() => void resource.reload()}
      />
      <ErrorNotice error={error} />
      {action && (
        <>
          <h4>本次提案：{actionState[action.state]}</h4>
          {stale && (
            <p className="notice warning" role="status">
              正在重新核对最新状态；下面保留已读取的原提案，当前处理入口暂不开放。
            </p>
          )}
          <p>
            提案保存的章节修订 {action.preview.base_section_revision}
            。这里查看原稿与拟稿，不执行采纳。
          </p>
          <Suspense fallback={<p role="status">正在加载提案对照…</p>}>
            <AssistantPatchComparison
              key={`${action.action_id}:${action.request_digest}`}
              bidId={bidId}
              before={action.preview.before}
              after={action.preview.after}
            />
          </Suspense>
          {!stale && (
            <p>
              <a
                href={`/assistant?action=${encodeURIComponent(action.action_id)}`}
              >
                打开这份提案的持久操作卡
              </a>
            </p>
          )}
          <button
            type="button"
            className="text-button"
            onClick={() => void resource.reload()}
          >
            刷新这份提案的实际状态
          </button>
        </>
      )}
    </section>
  );
}

export default function TaskAuthoringResultPanel({
  bidId,
  state,
  result,
  stale,
}: {
  bidId: string;
  state: RunView["state"];
  result: TaskAuthoringResult;
  stale: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section
      className="task-authoring-result"
      aria-label="章节任务的原生发布结果"
    >
      <p className="notice warning">{taskAuthoringScope}</p>
      <p role="status">{explanation(state, result)}</p>
      <p>
        本次章节基准：修订 {result.base_section_revision}；任务没有自动改稿。
      </p>
      {result.publication_state === "published" && (
        <>
          <button
            type="button"
            className="button secondary"
            aria-expanded={open}
            disabled={stale}
            onClick={() => setOpen(!open)}
          >
            核对本任务绑定的章节提案
          </button>
          {open && <Proposal bidId={bidId} result={result} taskStale={stale} />}
        </>
      )}
      <details className="identity-details">
        <summary>原生任务、写作计划与候选身份</summary>
        <p>
          原生任务：{result.job_id}；写作计划：{result.writing_plan_id}。
        </p>
        <p>
          章节：{result.section_id}；操作：{result.operation_id}。
        </p>
        <p>
          输入摘要：{result.job_input_digest}；候选摘要：
          {result.candidate_digest ?? "尚无已保存候选"}。
        </p>
      </details>
    </section>
  );
}
