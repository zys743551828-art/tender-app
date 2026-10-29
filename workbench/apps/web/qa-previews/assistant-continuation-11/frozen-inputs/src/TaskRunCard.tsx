import { useState } from "react";
import type { Operation, RunView, TemplateVersionView } from "./contracts";
import { Badge, ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import { useRecordedCommand } from "./useRecordedCommand";
import { taskNames, taskRunNames, triggerDescription } from "./taskState";
import { useAssistantPolling } from "./useAssistantFeed";
import { ArtifactActions } from "./ArtifactActions";
import { assistantReason } from "./assistantState";

export function TaskRunCard({
  bidId,
  id,
  memberId,
}: {
  bidId: string;
  id: string;
  memberId: string;
}) {
  const poll = useAssistantPolling();
  const resource = useResource<RunView>(`/bids/${bidId}/task-runs/${id}`, poll);
  const run =
    resource.data?.id === id && resource.data.bid_id === bidId
      ? resource.data
      : undefined;
  const definitionId =
    typeof run?.frozen_manifest.definition_id === "string"
      ? run.frozen_manifest.definition_id
      : null;
  const version = useResource<TemplateVersionView>(
    run && definitionId
      ? `/bids/${bidId}/task-definitions/${definitionId}/versions/${run.definition_version_id}`
      : null,
  );
  const config =
    version.data?.id === run?.definition_version_id &&
    version.data?.bid_id === bidId &&
    version.data.definition_id === definitionId
      ? version.data
      : undefined;
  const operationId = run?.final_operation_id ?? run?.root_operation_id;
  const operation = useResource<Operation>(
    operationId ? `/operations/${operationId}` : null,
    poll,
  );
  const actualOperation =
    operation.data &&
    operation.data.id === operationId &&
    operation.data.bid_id === bidId
      ? operation.data
      : undefined;
  const command = useRecordedCommand(
    `task-run:${memberId}:${bidId}:${id}:cancel`,
  );
  const [reason, setReason] = useState("");
  const [cancelOpen, setCancelOpen] = useState(false);
  const bodyId =
    typeof run?.frozen_manifest.context === "object" &&
    run.frozen_manifest.context !== null &&
    "body_version_id" in run.frozen_manifest.context &&
    typeof run.frozen_manifest.context.body_version_id === "string"
      ? run.frozen_manifest.context.body_version_id
      : null;
  return (
    <article className="panel task-run-card">
      <ResourceState
        {...resource}
        hasData={!!run}
        onRetry={() => void resource.reload()}
      />
      {resource.data && !run && (
        <p className="notice error">任务运行身份不一致，未显示其他项目。</p>
      )}
      {run && (
        <>
          <div className="section-title">
            <h3>
              {config
                ? taskNames[config.config.definition.task_kind]
                : "固定版本任务"}
            </h3>
            <Badge
              tone={
                [
                  "failed",
                  "blocked",
                  "unknown",
                  "reconciliation_required",
                ].includes(run.state)
                  ? "warning"
                  : ""
              }
            >
              {taskRunNames[run.state]}
            </Badge>
          </div>
          {run.coverage === "registered_effectivity_only_semantic_unknown" ? (
            <p className="notice warning">
              已登记补遗关系核对：
              {run.state === "succeeded"
                ? "已汇总已登记关系，语义影响尚未检查。"
                : "本次只处理已登记关系；语义影响尚未检查，运行尚未完成。"}
            </p>
          ) : (
            <p className="small-note">
              任务未创建正式确认、提交、核验或发布。操作结束与业务通过分别核对，章节提案不会自动改稿。
            </p>
          )}
          {["unknown", "reconciliation_required"].includes(run.state) && (
            <p className="notice warning">
              结果或费用待核对。不能通过新模板、新版本或新运行标识重复付费；请等待服务端核账。
            </p>
          )}
          {run.state === "cancel_requested" && (
            <p className="notice warning">
              取消请求已收到，尚未记录取消终态；在途调用可能已产生费用。
            </p>
          )}
          {run.error_code && (
            <p className="notice warning">{assistantReason(run.error_code)}</p>
          )}
          <ResourceState
            {...version}
            hasData={!!config}
            onRetry={() => void version.reload()}
          />
          {config && (
            <details className="coverage-details">
              <summary>本次冻结的模板版本{config.revision}与目标</summary>
              <p>{config.config.definition.name}</p>
              <p className="preserve-text">{config.instructions}</p>
              <p>
                {triggerDescription(config.config.definition.trigger)}，
                {config.config.paused
                  ? "此版本处于暂停状态"
                  : "此版本可用于触发"}
                ；运行不随当前模板改动。
              </p>
            </details>
          )}
          {bodyId && (
            <ArtifactActions
              bidId={bidId}
              documentId={bodyId}
              isPdf
              downloadLabel="核对本次冻结受检稿原件"
            />
          )}
          {config?.config.definition.task_kind === "supplement_impact" && (
            <a href={`/bids/${bidId}/materials`}>
              核对已登记资料与补遗效力关系
            </a>
          )}
          {config?.config.definition.task_kind === "chapter_suggestion" && (
            <a href={`/bids/${bidId}/authoring`}>
              到章节编制核对实际提案，未自动应用
            </a>
          )}
          <ErrorNotice error={command.error} />
          <ResourceState
            {...operation}
            hasData={!!actualOperation}
            onRetry={() => void operation.reload()}
          />
          {actualOperation &&
            ["queued", "running"].includes(actualOperation.state) && (
              <button
                className="text-button"
                onClick={() => setCancelOpen(!cancelOpen)}
                aria-expanded={cancelOpen}
              >
                取消本次在途处理
              </button>
            )}
          {cancelOpen &&
            actualOperation &&
            ["queued", "running"].includes(actualOperation.state) && (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void command
                    .run<Operation>(
                      `/operations/${operationId}/cancel`,
                      {
                        reason: reason.trim(),
                        cancel_pending_same_input: false,
                      },
                      operation.etag ?? "",
                    )
                    .then(() => {
                      void operation.reload();
                      void resource.reload();
                    });
                }}
              >
                <label>
                  取消原因
                  <input
                    required
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                    disabled={command.busy || !!command.pending}
                  />
                </label>
                <button
                  className="button secondary"
                  disabled={
                    !reason.trim() ||
                    !operation.etag ||
                    command.busy ||
                    !!command.pending
                  }
                >
                  请求取消当前处理
                </button>
              </form>
            )}
          {command.pending && !command.busy && (
            <button
              className="button secondary"
              onClick={() =>
                void command.retry<Operation>().then(() => {
                  void operation.reload();
                  void resource.reload();
                })
              }
            >
              恢复原取消请求结果
            </button>
          )}
          <details className="identity-details">
            <summary>固定输入、处理阶段与原始结果</summary>
            <p>
              阶段{run.stage}；运行{id}；定义版本{run.definition_version_id}
              ；原始操作{run.root_operation_id}；后续操作
              {run.final_operation_id ?? "尚无"}。
            </p>
            <pre>
              {JSON.stringify(
                { frozen_manifest: run.frozen_manifest, result: run.result },
                null,
                2,
              )}
            </pre>
          </details>
        </>
      )}
    </article>
  );
}
