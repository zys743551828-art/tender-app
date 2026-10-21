import { useState } from "react";
import { ApiError } from "./api";
import type { RunView } from "./contracts";
import type { TemplateView, TaskKindPage } from "./taskTriggerContracts";
import { Badge, ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import { useRecordedCommand } from "./useRecordedCommand";
import {
  exactPackageTaskScope,
  isExactPackageTask,
  taskNames,
  taskScopes,
  triggerDescription,
} from "./taskState";
import { assistantReason } from "./assistantState";
import { TaskTemplateEditor } from "./TaskTemplateEditor";
import { ExactPackageTaskRunControl } from "./ExactPackageTaskRunControl";
import { ExactPackageTaskScope } from "./ExactPackageTaskScope";
import { emptyPackageNavigationState } from "./packageNavigation";
import { isExactPackageAuthoring } from "./taskPackageAuthoringProtocol";
import { packageAuthoringScope } from "./packageAuthoringInputProtocol";
import { PackageAuthoringRunControl } from "./PackageAuthoringRunControl";
import { taskPackageStorageKey } from "./useTaskPackageCommand";

export function TaskTemplateCard({
  bidId,
  memberId,
  id,
  kinds,
  onChanged,
  onRun,
  executionBlocked = false,
}: {
  bidId: string;
  memberId: string;
  id: string;
  kinds: TaskKindPage | undefined;
  onChanged: () => void;
  onRun: (id: string) => void;
  executionBlocked?: boolean;
}) {
  const resource = useResource<TemplateView>(
    `/bids/${bidId}/task-definitions/${id}`,
  );
  const item =
    resource.data?.id === id && resource.data.bid_id === bidId
      ? resource.data
      : undefined;
  const pause = useRecordedCommand(`task-pause:${memberId}:${bidId}:${id}`);
  const run = useRecordedCommand(`task-run:${memberId}:${bidId}:${id}:start`);
  const [edit, setEdit] = useState(false);
  const [editorMounted, setEditorMounted] = useState(false);
  const [editorState, setEditorState] = useState(emptyPackageNavigationState);
  const [exactRunState, setExactRunState] = useState(
    emptyPackageNavigationState,
  );
  const [error, setError] = useState<unknown>(null);
  const capability = kinds?.items.find(
    (capability) => capability.task_kind === item?.configuration.task_kind,
  );
  const feeBlocked =
    executionBlocked ||
    (run.error instanceof ApiError &&
      run.error.code === "MODEL_CALL_REQUIRES_RECONCILIATION");
  const unavailable = !capability || capability.execution === "unavailable";
  const exact = item && isExactPackageTask(item.configuration);
  const authoring = item && isExactPackageAuthoring(item.configuration);
  let authoringRecovery = false;
  try {
    authoringRecovery =
      sessionStorage.getItem(
        taskPackageStorageKey({
          kind: "authoring_run",
          bidId,
          memberId,
          identity: id,
        }),
      ) !== null;
  } catch {
    /* An unavailable store is handled inside the command control. */
  }
  const exactBusy = exactRunState.busy || exactRunState.pending;
  const editBlocked =
    editorState.busy || editorState.pending || editorState.dirty;
  function changed() {
    void resource.reload();
    onChanged();
  }
  function accept(value: RunView | undefined) {
    if (!value) return;
    if (value.bid_id !== bidId) {
      setError(new Error("运行项目身份不一致，未采用其他任务结果。"));
      return;
    }
    onRun(value.id);
    onChanged();
  }
  return (
    <article className="panel task-template-card">
      <ResourceState
        {...resource}
        hasData={!!item}
        onRetry={() => void resource.reload()}
      />
      {resource.data && !item && (
        <p className="notice error">任务模板身份不一致。</p>
      )}
      {item && (
        <>
          <div className="section-title">
            <h3>{item.configuration.name}</h3>
            <Badge>{item.paused ? "已暂停后续触发" : "当前模板"}</Badge>
          </div>
          <p>
            {taskNames[item.configuration.task_kind]} · 固定版本{item.revision}
          </p>
          <p className="preserve-text">{item.configuration.instructions}</p>
          <p className="small-note">
            {authoring
              ? packageAuthoringScope
              : exact
                ? exactPackageTaskScope
                : taskScopes[item.configuration.task_kind]}
          </p>
          {isExactPackageTask(item.configuration) && (
            <ExactPackageTaskScope
              bidId={bidId}
              selection={item.configuration.source_selection.input}
            />
          )}
          <p>{triggerDescription(item.configuration.trigger)}</p>
          {item.configuration.source_selection?.mode ===
            "exact_package_trigger" && (
            <p className="notice neutral">
              只唤醒本模板已保存的确切输入；需独立调度服务启用后处理。手动执行须先核对输入并将模板明确保存为手动模式。已受理的原运行不随改版或暂停而消失。
            </p>
          )}
          {item.next_run_at && (
            <p>
              下一次计划时刻：
              {new Date(item.next_run_at).toLocaleString("zh-CN", {
                timeZone: "Asia/Shanghai",
              })}
              （Asia/Shanghai）
            </p>
          )}
          {capability?.reason && !authoring && (
            <p className="notice warning">
              {assistantReason(capability.reason)}
            </p>
          )}
          {item.configuration.task_kind === "scoring_review" && unavailable && (
            <p className="notice warning">
              评分尚未具备正式资格，不能运行；保存的模板不授予资格。
            </p>
          )}
          {feeBlocked && (
            <p className="notice warning">
              已有运行费用待核对，不能通过当前模板或新版本重复付费。
            </p>
          )}
          {["denial_check", "chapter_suggestion"].includes(
            item.configuration.task_kind,
          ) && (
            <p className="small-note">
              明确运行可能请求模型处理并产生费用；受理不表示候选已生成或核对已完成。
            </p>
          )}
          <ErrorNotice
            error={
              error ?? pause.error ?? (exact || authoring ? null : run.error)
            }
          />
          <div className="review-shortcuts">
            <button
              className="button secondary"
              disabled={
                resource.loading ||
                !!resource.error ||
                pause.busy ||
                !!pause.pending ||
                exactBusy ||
                run.busy ||
                !!run.pending
              }
              onClick={() => {
                setEditorMounted(true);
                setEdit(!edit);
              }}
              aria-expanded={edit}
            >
              修改并保存新版本
            </button>
            <button
              className="button secondary"
              disabled={
                resource.loading ||
                !!resource.error ||
                pause.busy ||
                !!pause.pending ||
                exactBusy ||
                editBlocked ||
                !resource.etag
              }
              onClick={() =>
                void pause
                  .run<TemplateView>(
                    `/bids/${bidId}/task-definitions/${id}/pause`,
                    { paused: !item.paused },
                    resource.etag ?? "",
                  )
                  .then(changed)
              }
            >
              {item.paused ? "恢复后续触发" : "暂停后续触发"}
            </button>
            {!exact && !authoring && (
              <button
                className="button primary"
                disabled={
                  resource.loading ||
                  !!resource.error ||
                  item.paused ||
                  unavailable ||
                  feeBlocked ||
                  run.busy ||
                  !!run.pending ||
                  !resource.etag
                }
                onClick={() =>
                  void run
                    .run<RunView>(
                      `/bids/${bidId}/task-definitions/${id}/runs`,
                      { rerun: false },
                      resource.etag ?? "",
                    )
                    .then((value) => accept(value?.data))
                }
              >
                手动运行当前版本
              </button>
            )}
          </div>
          <p className="small-note">
            保存／修改不运行。暂停只影响未来触发，取消在途任务须到该运行记录明确操作；重复点击同输入可能恢复原运行，不另建重复付费任务。
          </p>
          {exact && (
            <ExactPackageTaskRunControl
              key={`${memberId}:${bidId}:${id}`}
              bidId={bidId}
              memberId={memberId}
              template={item}
              etag={resource.etag}
              kinds={kinds}
              disabled={
                resource.loading ||
                !!resource.error ||
                pause.busy ||
                !!pause.pending ||
                editBlocked ||
                executionBlocked
              }
              onRun={onRun}
              onChanged={changed}
              onStateChange={setExactRunState}
            />
          )}
          {!exact && !authoring && run.pending && !run.busy && (
            <button
              className="button secondary"
              onClick={() =>
                void run.retry<RunView>().then((value) => accept(value?.data))
              }
            >
              恢复原运行受理结果
            </button>
          )}
          {pause.pending && !pause.busy && (
            <button
              className="button secondary"
              onClick={() => void pause.retry<TemplateView>().then(changed)}
            >
              恢复原暂停或恢复操作结果
            </button>
          )}
          {(exact || authoring ? editorMounted : edit) && (
            <div hidden={!edit}>
              <TaskTemplateEditor
                key={
                  exact || authoring
                    ? `${memberId}:${bidId}:${id}`
                    : `${id}:${item.version_id}`
                }
                bidId={bidId}
                memberId={memberId}
                template={item}
                etag={resource.etag}
                onSaved={() => {
                  setEdit(false);
                  setEditorMounted(false);
                  changed();
                }}
                onClose={() => setEdit(false)}
                onStateChange={setEditorState}
              />
            </div>
          )}
          <details className="identity-details">
            <summary>模板、固定版本与摘要</summary>
            <p>
              模板{id}；版本{item.version_id}；摘要{item.digest}
              。当前状态不会改写既有运行冻结身份。
            </p>
          </details>
        </>
      )}
      {(authoring || authoringRecovery) && (
        <PackageAuthoringRunControl
          key={`${memberId}:${bidId}:${id}`}
          bidId={bidId}
          memberId={memberId}
          id={id}
          template={item}
          etag={resource.etag}
          kinds={kinds}
          disabled={
            resource.loading ||
            !!resource.error ||
            pause.busy ||
            !!pause.pending ||
            editBlocked ||
            executionBlocked
          }
          onRun={onRun}
          onChanged={changed}
          onStateChange={setExactRunState}
        />
      )}
    </article>
  );
}
