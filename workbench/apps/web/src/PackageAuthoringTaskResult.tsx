import { lazy, Suspense, useState } from "react";
import type { AssistantAction } from "./contracts";
import { ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import { PackageAuthoringInputDetails } from "./PackageAuthoringInput";
import { packageAuthoringScope } from "./packageAuthoringInputProtocol";
import {
  readPackageAuthoringProposal,
  type PackageAuthoringRunView,
} from "./taskPackageAuthoringProtocol";
import { taskRunNames } from "./taskState";

const AssistantPatchComparison = lazy(() =>
  import("./AssistantPatchComparison").then((m) => ({
    default: m.AssistantPatchComparison,
  })),
);
function Proposal({
  run,
  stale,
}: {
  run: PackageAuthoringRunView;
  stale: boolean;
}) {
  const resource = useResource<AssistantAction>(
    `/assistant/actions/${run.result.action_id}`,
  );
  let action: ReturnType<typeof readPackageAuthoringProposal> | null = null,
    error: unknown = null;
  if (resource.data)
    try {
      action = readPackageAuthoringProposal(
        resource.data,
        run.bid_id,
        run.result,
      );
    } catch (caught) {
      error = caught;
    }
  return (
    <section aria-label="固定整包章节候选对照">
      <ResourceState
        {...resource}
        hasData={!!action}
        onRetry={() => void resource.reload()}
      />
      <ErrorNotice error={error} />
      {action && (
        <>
          <p>
            保存的章节基准：修订 {action.preview.base_section_revision}
            。候选已发布供核对，尚未采纳正文。
          </p>
          <Suspense fallback={<p role="status">正在加载完整正文对照…</p>}>
            <AssistantPatchComparison
              key={`${action.action_id}:${action.request_digest}`}
              bidId={run.bid_id}
              before={action.preview.before}
              after={action.preview.after}
            />
          </Suspense>
          <p className="notice neutral">
            此候选目前可核对、拒绝；正文采纳和交付包构建尚不可用。
          </p>
          {!stale && !resource.loading && !resource.error && (
            <a
              href={`/assistant?action=${encodeURIComponent(action.action_id)}`}
            >
              打开这份固定整包候选操作卡
            </a>
          )}
        </>
      )}
    </section>
  );
}
export default function PackageAuthoringTaskResult({
  run,
  stale,
}: {
  run: PackageAuthoringRunView;
  stale: boolean;
}) {
  const [open, setOpen] = useState(false);
  const state = run.result.publication_state;
  const explanation =
    state === "published"
      ? "章节候选已由服务器发布；任务成功表示候选可供核对，正文尚未采纳。"
      : state === "stale"
        ? "发布前依据已变化，原候选没有成为可处理提议。"
        : state === "failed"
          ? "候选发布失败，不能把模型步骤完成当作编写完成。"
          : run.state === "awaiting_publication"
            ? "候选已保存，仍在等待发布；尚无可核对的正式候选卡。"
            : run.state === "cancelled"
              ? "本次运行已取消，未发布章节候选。"
              : run.state === "reconciliation_required"
                ? "原模型调用费用待核对，不能另建运行重复付费。"
                : "已受理固定输入，尚无已发布章节候选。";
  return (
    <section aria-label="固定整包编写运行结果">
      <p>{packageAuthoringScope}</p>
      {stale && (
        <p className="notice warning" role="status">
          最新读取尚未通过核验。下面保留上次已核验快照，写操作和处理入口暂不可用。
        </p>
      )}
      <p>
        {stale ? "上次已核验任务状态" : "当前任务状态"}：
        {taskRunNames[run.state]}。
      </p>
      <p role="status">{explanation}</p>
      <PackageAuthoringInputDetails
        key={`${run.bid_id}:${run.result.authoring_input_id}:${run.result.authoring_input_digest}`}
        bidId={run.bid_id}
        selection={run.frozen_manifest.context.input}
      />
      {state === "published" && (
        <>
          <button
            type="button"
            className="button secondary"
            aria-expanded={open}
            disabled={stale}
            onClick={() => setOpen(!open)}
          >
            核对固定整包章节候选的原稿与拟稿
          </button>
          {open && (
            <Proposal key={run.result.action_id} run={run} stale={stale} />
          )}
        </>
      )}
      <details className="identity-details">
        <summary>本次候选与发布关联</summary>
        <p>
          编写任务：{run.result.job_id}；写作计划：{run.result.writing_plan_id}
          ；候选摘要：{run.result.candidate_digest ?? "尚无"}；原运行成员：
          {run.frozen_manifest.actor_id}。
        </p>
        <p>本记录保留自己的原输入；模板后来改版不会替换这些身份。</p>
      </details>
    </section>
  );
}
