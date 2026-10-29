import { useEffect, useState } from "react";
import { supportsApi } from "./api";
import type {
  Bid,
  RunPage,
  TemplatePage,
  TaskKindPage,
  TaskNotificationPage,
  TaskScheduleRecoveryPage,
} from "./contracts";
import { taskTemplatesContractReady } from "./contracts";
import { Badge, ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import { useTaskPage } from "./useTaskPage";
import { TaskTemplateEditor } from "./TaskTemplateEditor";
import { TaskTemplateCard } from "./TaskTemplateCard";
import { TaskRunCard } from "./TaskRunCard";
import { taskNames, taskScopes, taskRunNames } from "./taskState";
import { assistantReason } from "./assistantState";
import { useAssistantPolling } from "./useAssistantFeed";

export function TaskPanel({
  bidId,
  memberId,
}: {
  bidId: string;
  memberId: string;
}) {
  const [creating, setCreating] = useState(false);
  const [selectedRun, setSelectedRun] = useState(() =>
    new URLSearchParams(window.location.search).get("run"),
  );
  const [showRuns, setShowRuns] = useState(false);
  const [showNotifications, setShowNotifications] = useState(false);
  const [showRecoveries, setShowRecoveries] = useState(false);
  const bid = useResource<Bid>(`/bids/${bidId}`);
  const kinds = useResource<TaskKindPage>("/task-kinds");
  const templates = useTaskPage<TemplatePage>(
    `/bids/${bidId}/task-definitions?limit=20`,
    0,
    (page) => (page.has_more ? page.next_cursor : null),
  );
  const poll = useAssistantPolling();
  const runs = useTaskPage<RunPage>(
    `/bids/${bidId}/task-runs?limit=20`,
    poll,
    (page) => page.next_after,
    "after",
  );
  const notifications = useTaskPage<TaskNotificationPage>(
    `/bids/${bidId}/task-notifications?limit=20`,
    showNotifications ? poll : 0,
    (page) => page.next_after,
    "after",
  );
  const recoveries = useTaskPage<TaskScheduleRecoveryPage>(
    `/bids/${bidId}/task-schedule-recoveries?limit=20`,
    showRecoveries ? poll : 0,
    (page) => page.next_after,
    "after",
  );
  useEffect(() => {
    const sync = () =>
      setSelectedRun(new URLSearchParams(window.location.search).get("run"));
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);
  const feeBlocked = runs.items.some(
    (run) =>
      run.bid_id === bidId &&
      ["unknown", "reconciliation_required"].includes(run.state),
  );
  const selected = selectedRun;
  function openRun(id: string) {
    const params = new URLSearchParams(window.location.search);
    params.set("run", id);
    window.history.pushState({}, "", `${window.location.pathname}?${params}`);
    setSelectedRun(id);
  }
  function changed() {
    void templates.reload();
    void bid.reload();
    void runs.reload();
  }
  if (!taskTemplatesContractReady)
    return (
      <section className="panel">
        <h2>可复用任务</h2>
        <p className="notice warning">
          服务器任务契约尚未就绪；已保存业务记录保留。
        </p>
      </section>
    );
  return (
    <div className="task-workspace">
      <section className="panel">
        <div className="section-title">
          <h2>可复用任务</h2>
          <Badge>保存不运行 · 正式动作仍需明确处理</Badge>
        </div>
        <p className="muted">
          把反复使用的说明保存为固定版本。默认手动；明确选事件或定时才建立后续触发，模板不会替人确认规则、提交标书、核成绩或发布知识。
        </p>
        <ResourceState
          {...kinds}
          hasData={!!kinds.data}
          onRetry={() => void kinds.reload()}
        />
        {kinds.data && (
          <details className="coverage-details">
            <summary>四类任务的实际能力与边界</summary>
            {kinds.data.items.map((item) => (
              <div key={item.task_kind}>
                <h3>{taskNames[item.task_kind]}</h3>
                <p>{taskScopes[item.task_kind]}</p>
                {item.reason && (
                  <p className="notice warning">
                    {assistantReason(item.reason)}
                  </p>
                )}
              </div>
            ))}
          </details>
        )}
        <button
          className="button primary"
          disabled={!bid.etag}
          onClick={() => setCreating(!creating)}
          aria-expanded={creating}
        >
          新建任务模板
        </button>
        {supportsApi("POST", `/bids/${bidId}/task-definition-drafts`) && (
          <TaskDraftPanel
            bidId={bidId}
            memberId={memberId}
            bidEtag={bid.etag}
            onSaved={changed}
          />
        )}
      </section>
      {creating && (
        <TaskTemplateEditor
          bidId={bidId}
          memberId={memberId}
          template={null}
          etag={bid.etag}
          onSaved={() => {
            setCreating(false);
            changed();
          }}
          onClose={() => setCreating(false)}
        />
      )}
      <ResourceState
        {...templates}
        hasData={!!templates.data}
        onRetry={() => void templates.reload()}
      />
      <ErrorNotice error={templates.moreError} />
      {templates.items.some((item) => item.bid_id !== bidId) && (
        <p className="notice error">
          模板目录项目身份不一致，未显示其他项目记录。
        </p>
      )}
      {templates.data && !templates.items.length && (
        <p className="panel small-empty">
          尚无保存的模板。无需建立模板也能走现有PDF核对与人工编制路径。
        </p>
      )}
      {templates.items
        .filter((item) => item.bid_id === bidId)
        .map((item) => (
          <TaskTemplateCard
            key={item.id}
            bidId={bidId}
            memberId={memberId}
            id={item.id}
            kinds={kinds.data}
            onChanged={changed}
            onRun={openRun}
            executionBlocked={feeBlocked}
          />
        ))}
      {templates.hasMore && (
        <button
          className="button secondary"
          disabled={templates.moreBusy}
          onClick={() => void templates.more()}
        >
          加载更多任务模板
        </button>
      )}
      <section className="panel">
        <button
          className="text-button"
          onClick={() => setShowRuns(!showRuns)}
          aria-expanded={showRuns}
        >
          服务器运行历史
        </button>
        <p className="small-note">
          按服务器持久分页发现，不依赖此浏览器保存的标识；次序为服务器稳定顺序，不冒称时间排序。
        </p>
        {showRuns && (
          <>
            <ResourceState
              {...runs}
              hasData={!!runs.data}
              onRetry={() => void runs.reload()}
            />
            <ErrorNotice error={runs.moreError} />
            {runs.items
              .filter((item) => item.bid_id === bidId)
              .map((item) => (
                <button
                  className="history-row"
                  key={item.id}
                  onClick={() => openRun(item.id)}
                >
                  打开固定任务 · {taskRunNames[item.state]} ·{" "}
                  {item.id.slice(0, 8)}
                </button>
              ))}
            {runs.data && !runs.items.length && (
              <p className="small-empty">尚无受理运行。</p>
            )}
            {runs.hasMore && (
              <button
                className="text-button"
                disabled={runs.moreBusy}
                onClick={() => void runs.more()}
              >
                加载更多运行
              </button>
            )}
          </>
        )}
      </section>
      {selected && (
        <TaskRunCard
          key={selected}
          bidId={bidId}
          memberId={memberId}
          id={selected}
        />
      )}
      <section className="panel">
        <button
          className="text-button"
          onClick={() => setShowNotifications(!showNotifications)}
          aria-expanded={showNotifications}
        >
          运行通知
        </button>
        {showNotifications && (
          <>
            <ResourceState
              {...notifications}
              hasData={!!notifications.data}
              onRetry={() => void notifications.reload()}
            />
            <ErrorNotice error={notifications.moreError} />
            {notifications.items.map((item) => (
              <article className="notification-row" key={item.id}>
                <p>
                  {new Date(item.created_at).toLocaleString("zh-CN")} ·{" "}
                  {item.payload.state}
                </p>
                {item.payload.error_code && (
                  <p>{assistantReason(item.payload.error_code)}</p>
                )}
                <button
                  className="text-button"
                  onClick={() => openRun(item.payload.run_id)}
                >
                  打开这次真实运行
                </button>
              </article>
            ))}
            {notifications.data && !notifications.items.length && (
              <p className="small-empty">
                尚无已持久保存的通知；空列表不代表后台任务全部完成。
              </p>
            )}
            {notifications.hasMore && (
              <button
                className="text-button"
                disabled={notifications.moreBusy}
                onClick={() => void notifications.more()}
              >
                加载更多通知
              </button>
            )}
          </>
        )}
      </section>
      <section className="panel">
        <button
          className="text-button"
          onClick={() => setShowRecoveries(!showRecoveries)}
          aria-expanded={showRecoveries}
        >
          漏时与计划恢复记录
        </button>
        {showRecoveries && (
          <>
            <ResourceState
              {...recoveries}
              hasData={!!recoveries.data}
              onRetry={() => void recoveries.reload()}
            />
            <ErrorNotice error={recoveries.moreError} />
            {recoveries.items.map((item) => (
              <article className="notification-row" key={item.id}>
                <p>
                  下一计划时刻
                  {new Date(item.payload.next_fire_at).toLocaleString("zh-CN", {
                    timeZone: "Asia/Shanghai",
                  })}
                  （Asia/Shanghai）。自动补跑
                  {item.payload.automatic_catchup_runs}次。
                </p>
                {item.payload.missed && (
                  <p className="notice warning">
                    错过
                    {new Date(item.payload.missed.from).toLocaleString("zh-CN")}
                    至
                    {new Date(item.payload.missed.through).toLocaleString(
                      "zh-CN",
                    )}
                    的时段已跳过，未枚举次数，不自动补历史。
                  </p>
                )}
                <TaskTemplateCard
                  bidId={bidId}
                  memberId={memberId}
                  id={item.payload.definition_id}
                  kinds={kinds.data}
                  onChanged={changed}
                  onRun={openRun}
                  executionBlocked={feeBlocked}
                />
                <p className="small-note">
                  如仍需要，使用当前模板卡片的“手动运行当前版本”一次启动当前输入，不重放错过的历史。
                </p>
              </article>
            ))}
            {recoveries.data && !recoveries.items.length && (
              <p className="small-empty">尚无计划漏时恢复记录。</p>
            )}
            {recoveries.hasMore && (
              <button
                className="text-button"
                disabled={recoveries.moreBusy}
                onClick={() => void recoveries.more()}
              >
                加载更多恢复记录
              </button>
            )}
          </>
        )}
      </section>
    </div>
  );
}
// Loaded only when the implemented server exposes private persistent drafts.
import { TaskDraftPanel } from "./TaskDraftPanel";
