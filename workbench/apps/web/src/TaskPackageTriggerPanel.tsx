import { useEffect, useRef, useState } from "react";
import { ApiError } from "./api";
import { Badge, ErrorNotice } from "./components";
import { ExactPackageTaskScope } from "./ExactPackageTaskScope";
import { ResourceState } from "./ResourceState";
import { useAssistantPolling } from "./useAssistantFeed";
import { usePackageScopeGuard } from "./packageScopeGuard";
import {
  taskTriggerIntentEtag,
  validateTaskTriggerIntent,
} from "./taskPackageProtocol";
import type { PackageTriggerIntentView } from "./taskTriggerContracts";
import { useResource } from "./useResource";
import { useTaskPackageCommand } from "./useTaskPackageCommand";
import { useTaskTriggerPage } from "./useTaskTriggerPage";

const states: Record<PackageTriggerIntentView["state"], string> = {
  pending: "等待核对原输入",
  accepted: "已关联原生运行",
  blocked: "本次触发受阻",
  cancelled: "已取消本次触发",
};
const reasons: Record<string, string> = {
  TASK_TEMPLATE_PAUSED: "原触发后模板已暂停，本次未启动新工作。",
  TASK_PACKAGE_TEMPLATE_CHANGED: "原模板版本已经变化，本次未转用新版本或新包。",
  PROJECT_WORK_CLOSED: "项目已结束或归档，本次未启动新工作。",
  TASK_EVENT_SUPERSEDED:
    "原资料事件已被后续更新替代，本次未改用后来的事件或包。",
  TASK_PACKAGE_SCHEDULE_CHANGED: "原定时配置已变化，本次未转用新计划。",
  MODEL_CALL_REQUIRES_RECONCILIATION:
    "已有调用费用待核对，不能通过新触发重复调用。",
  TASK_TRIGGER_CANCELLED: "本次尚未关联原生运行的触发已取消。",
};

export function TaskPackageTriggerPanel({
  bidId,
  memberId,
  onRun,
}: {
  bidId: string;
  memberId: string;
  onRun: (id: string) => void;
}) {
  const [selected, setSelected] = useState(() =>
    new URLSearchParams(window.location.search).get("task_trigger"),
  );
  const [open, setOpen] = useState(!!selected);
  const poll = useAssistantPolling();
  const page = useTaskTriggerPage(bidId, open, poll);
  useEffect(() => {
    const changed = () => {
      const id = new URLSearchParams(window.location.search).get(
        "task_trigger",
      );
      setSelected(id);
      if (id) setOpen(true);
    };
    window.addEventListener("popstate", changed);
    return () => window.removeEventListener("popstate", changed);
  }, []);
  function select(id: string) {
    const query = new URLSearchParams(window.location.search);
    query.set("task_trigger", id);
    window.history.pushState({}, "", `${window.location.pathname}?${query}`);
    setSelected(id);
  }
  return (
    <section className="panel" aria-label="整包事件与定时触发记录">
      <button
        className="text-button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        整包事件与定时触发记录
      </button>
      <p className="small-note">
        每次触发均保留原模板与确切输入。页面不启动调度；“已关联原生运行”不等于核查完成。
      </p>
      {open && (
        <>
          <ResourceState
            {...page}
            hasData={!!page.data}
            onRetry={() => void page.reload()}
          />
          <ErrorNotice error={page.moreError} />
          {page.items.map((item) => (
            <button
              type="button"
              className="history-row"
              key={item.id}
              onClick={() => select(item.id)}
            >
              {item.trigger === "schedule" ? "定时" : "资料事件"} ·{" "}
              {states[item.state]} ·{" "}
              {new Date(item.created_at).toLocaleString("zh-CN", {
                timeZone: "Asia/Shanghai",
              })}
              （Asia/Shanghai）
            </button>
          ))}
          {page.data && page.items.length === 0 && (
            <p className="small-empty">
              尚无持久触发记录。保存模板本身不会建立运行。
            </p>
          )}
          {page.hasMore && (
            <button
              type="button"
              className="text-button"
              disabled={page.moreBusy}
              onClick={() => void page.more()}
            >
              加载更多触发记录
            </button>
          )}
          {selected && (
            <TaskPackageTriggerDetail
              key={`${memberId}:${bidId}:${selected}`}
              bidId={bidId}
              memberId={memberId}
              id={selected}
              onRun={onRun}
              onChanged={() => void page.reload()}
            />
          )}
        </>
      )}
    </section>
  );
}

export function TaskPackageTriggerDetail({
  bidId,
  memberId,
  id,
  onRun,
  onChanged,
}: {
  bidId: string;
  memberId: string;
  id: string;
  onRun: (id: string) => void;
  onChanged: () => void;
}) {
  const path = `/bids/${bidId}/task-package-trigger-intents/${id}`;
  const poll = useAssistantPolling();
  const resource = useResource<unknown>(path, poll);
  const [checked, setChecked] = useState<{
    source: unknown;
    item: PackageTriggerIntentView;
  } | null>(null);
  const original = useRef<PackageTriggerIntentView | null>(null);
  const [failure, setFailure] = useState<unknown>(null);
  const [reason, setReason] = useState("");
  const [ack, setAck] = useState<PackageTriggerIntentView | null>(null);
  const command = useTaskPackageCommand({
    kind: "trigger_cancel",
    memberId,
    bidId,
    identity: id,
  });
  const pending = !!command.pending || command.blocked;
  usePackageScopeGuard(`task-trigger-cancel:${memberId}:${bidId}:${id}`, {
    busy: command.busy,
    pending,
    dirty: !!reason.trim() && !ack,
  });
  useEffect(() => {
    setFailure(null);
    if (!resource.data) return;
    try {
      const item = validateTaskTriggerIntent(resource.data, bidId, id);
      if (resource.etag !== taskTriggerIntentEtag(item))
        throw new Error("原触发的修订摘要无法核验，不能取消其他输入。");
      validateTaskTriggerIntent(item, bidId, id, original.current ?? undefined);
      original.current = item;
      setChecked({ source: resource.data, item });
    } catch (error) {
      setFailure(error);
    }
  }, [resource.data, resource.etag, bidId, id]);
  const item = checked?.item;
  const stale =
    resource.loading ||
    !!resource.error ||
    !!failure ||
    checked?.source !== resource.data;
  function accept(value: PackageTriggerIntentView | undefined) {
    if (!value) return;
    setAck(value);
    setReason("");
    void resource.reload();
    onChanged();
  }
  async function cancel() {
    if (
      !item ||
      item.state !== "pending" ||
      stale ||
      pending ||
      command.busy ||
      !reason.trim()
    )
      return;
    const response = await command.run({
      path: path + "/cancel",
      method: "POST",
      body: { reason: reason.trim() },
      etag: taskTriggerIntentEtag(item),
      expected: { kind: "trigger_cancel", intent: item },
    });
    accept(response?.data);
    if (!response) void resource.reload();
  }
  return (
    <article
      className="exact-package-task-command"
      aria-label="固定整包触发详情"
    >
      <ResourceState
        {...resource}
        hasData={!!item}
        onRetry={() => void resource.reload()}
      />
      <ErrorNotice error={failure ?? command.error} />
      {item && (
        <>
          <div className="section-title">
            <h3>这次固定输入的触发</h3>
            <Badge>{states[item.state]}</Badge>
          </div>
          {stale && (
            <p className="notice warning">
              保留上次已核对的触发快照；当前读取尚未通过核验，暂停新的取消操作。
            </p>
          )}
          <p>
            {item.trigger === "schedule"
              ? `原计划时刻：${new Date(item.scheduled_at!).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" })}（Asia/Shanghai）`
              : "由已入库的资料事件唤醒，所选包仍是原保存输入。"}
          </p>
          {item.state === "pending" && (
            <p className="notice neutral">
              独立调度服务尚未完成本次原输入核对；此页面只读取和取消，不启动运行。
            </p>
          )}
          {item.error_code && (
            <p className="notice warning">
              {reasons[item.error_code] ??
                "原输入的当前条件未通过，未启动新工作。请核对原模板和来源。"}
            </p>
          )}
          <ExactPackageTaskScope bidId={bidId} selection={item.selection} />
          <details className="identity-details">
            <summary>原事件、模板版本与触发摘要</summary>
            <p>模板版本：{item.definition_version_id}</p>
            <p>触发标识：{item.id}</p>
            {item.trigger_event_id && <p>资料事件：{item.trigger_event_id}</p>}
            <p>输入摘要：{item.input_digest}</p>
            {item.error_code && <p>状态代码：{item.error_code}</p>}
          </details>
          {item.state === "accepted" && item.run_id && (
            <>
              <p>
                {item.reused
                  ? "这次触发复用同输入的原运行，未另建重复核查。"
                  : "这次触发已关联原生运行，后续状态与取消以该运行记录为准。"}
              </p>
              <button
                type="button"
                className="button secondary"
                onClick={() => onRun(item.run_id!)}
              >
                查看这次真实运行与取消入口
              </button>
            </>
          )}
          <a
            className="text-link"
            href={`/bids/${bidId}/tasks?task_template=${item.definition_id}`}
          >
            核对模板当前版本与明确输入
          </a>
          {item.state === "pending" && (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void cancel();
              }}
            >
              <label>
                取消本次触发的原因
                <textarea
                  aria-label="取消本次触发的原因"
                  required
                  maxLength={1000}
                  rows={2}
                  value={reason}
                  disabled={stale || pending || command.busy}
                  onChange={(event) => setReason(event.target.value)}
                />
              </label>
              <button
                className="button secondary"
                disabled={stale || pending || command.busy || !reason.trim()}
              >
                取消这次尚未运行的触发
              </button>
            </form>
          )}
        </>
      )}
      {ack && (
        <p className="notice neutral">
          原取消请求回执：{states[ack.state]}
          。这是该请求的原回执，当前状态另从服务器读取。
        </p>
      )}
      {command.error instanceof ApiError &&
        command.error.code === "TASK_TRIGGER_ALREADY_ACCEPTED" && (
          <p className="notice warning">
            原触发已关联运行，请重新读取这份记录并从该运行入口取消。
          </p>
        )}
      {pending && (
        <p className="notice warning">
          原取消请求尚未取得可信回执。刷新或读取当前记录不会清除原请求，也不会换键重复提交。
        </p>
      )}
      {command.pending && !command.busy && (
        <button
          type="button"
          className="button secondary"
          onClick={() =>
            void command.retry().then((value) => accept(value?.data))
          }
        >
          恢复原取消请求结果
        </button>
      )}
      {command.blocked && (
        <p className="notice error">
          本地恢复记录无法核验；保留原记录，暂停新写入。
        </p>
      )}
    </article>
  );
}
