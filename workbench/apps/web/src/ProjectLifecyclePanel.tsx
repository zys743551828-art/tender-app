import { useState } from "react";
import type { LifecycleChangeRequest, ProjectLifecycleView } from "./contracts";
import { Badge, ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { useRecordedCommand } from "./useRecordedCommand";
import { useResource } from "./useResource";
import "./ProjectLifecyclePanel.css";

type Action = LifecycleChangeRequest["action"];
const actions: Record<Action, string> = {
  start: "开始本轮工作",
  end: "结束本轮工作",
  terminate: "终止本轮工作",
  archive: "归档项目",
  reopen: "重新打开项目",
};
const phases: Record<ProjectLifecycleView["phase"], string> = {
  preparation: "准备资料",
  working: "工作中",
  submitted: "已登记提交",
  closed: "已结项",
  terminated: "已终止",
};
const blockers = {
  OPERATIONS_IN_FLIGHT:
    "仍有后台任务：请等待或到处理记录明确请求取消并等终态。",
  UPLOADS_UNFINISHED: "仍有未结束上传：请到项目资料核对、取消或结束暂存意图。",
  BATCHES_UNFINISHED: "仍有未结束批次：请到项目资料完成或明确结束批次。",
};

function valid(value: unknown, bidId: string): value is ProjectLifecycleView {
  if (!value || typeof value !== "object") return false;
  const row = value as ProjectLifecycleView;
  return (
    row.bid_id === bidId &&
    Object.hasOwn(phases, row.phase) &&
    Number.isSafeInteger(row.revision) &&
    row.revision > 0 &&
    (row.archived_at === null || typeof row.archived_at === "string") &&
    Array.isArray(row.allowed_actions) &&
    row.allowed_actions.every((action) => Object.hasOwn(actions, action)) &&
    Array.isArray(row.archive_blockers) &&
    row.archive_blockers.every((item) => Object.hasOwn(blockers, item)) &&
    Array.isArray(row.active_operations) &&
    Array.isArray(row.unfinished_uploads) &&
    Array.isArray(row.unfinished_batches)
  );
}

export function ProjectLifecyclePanel({
  bidId,
  memberId,
  onChanged,
}: {
  bidId: string;
  memberId: string;
  onChanged: () => void;
}) {
  const path = `/bids/${bidId}/lifecycle`;
  const resource = useResource<ProjectLifecycleView>(path);
  const [intent, setIntent] = useState<{ action: Action; etag: string } | null>(
    null,
  );
  const [reason, setReason] = useState("");
  const [saved, setSaved] = useState(false);
  const command = useRecordedCommand(
    `lifecycle:${memberId}:${bidId}`,
    ({ data }) => {
      if (!valid(data, bidId))
        throw new Error(
          "项目状态回执身份不一致，保留原请求，未采用其它项目结果。",
        );
    },
  );
  const current = valid(resource.data, bidId) ? resource.data : undefined;
  const wrongIdentity = resource.data && !current;
  const pendingBody = command.pending?.body as
    | Partial<LifecycleChangeRequest>
    | undefined;
  const pendingValid =
    !command.pending ||
    (command.pending.path === path &&
      !command.pending.method &&
      !!pendingBody &&
      Object.keys(pendingBody).sort().join(",") === "action,reason" &&
      typeof pendingBody.action === "string" &&
      Object.hasOwn(actions, pendingBody.action) &&
      typeof pendingBody.reason === "string" &&
      !!pendingBody.reason.trim() &&
      pendingBody.reason.length <= 4000);
  const busy = command.busy || !!command.pending;
  const stale = !!intent && intent.etag !== resource.etag;
  const ready =
    !!current && !!resource.etag && !resource.loading && !resource.error;
  async function accept(value: unknown) {
    if (!value) return;
    setIntent(null);
    setReason("");
    setSaved(true);
    await resource.reload();
    onChanged();
    window.dispatchEvent(new Event("server-snapshot-change"));
  }
  async function refresh() {
    if (busy) return;
    await resource.reload();
    setIntent(null);
    setSaved(false);
    command.clearError();
  }
  return (
    <section
      className="panel project-lifecycle-panel"
      aria-label="项目生命周期"
    >
      <div className="section-heading">
        <h2>项目阶段与归档</h2>
        <button
          className="text-button"
          disabled={busy || resource.loading}
          onClick={() => void refresh()}
        >
          重新读取项目状态
        </button>
      </div>
      <p className="muted">
        阶段、归档和任务状态分别记录。终止或归档不会取消后台任务、伪造实际提交或删除历史；重新打开只恢复同轮工作，旧提交和报告仍冻结。
      </p>
      <ResourceState
        {...resource}
        hasData={!!current}
        onRetry={() => void refresh()}
      />
      {wrongIdentity && (
        <ErrorNotice error={new Error("项目状态身份不一致，不能操作。")} />
      )}
      {current && (
        <>
          <p>
            <Badge>{phases[current.phase]}</Badge> ·{" "}
            {current.archived_at ? "已归档，只读历史" : "未归档"}
          </p>
          {current.archive_blockers.map((item) => (
            <p className="notice warning" key={item}>
              {blockers[item]}
            </p>
          ))}
          {current.active_operations.length > 0 && (
            <a href={`/bids/${bidId}/operations`}>
              查看 {current.active_operations.length} 项在途处理
            </a>
          )}
          <div className="review-shortcuts">
            {current.allowed_actions
              .filter((action) => Object.hasOwn(actions, action))
              .map((action) => (
                <button
                  className="button secondary"
                  key={action}
                  disabled={busy || !ready || !!command.error}
                  onClick={() => {
                    setIntent({ action, etag: resource.etag! });
                    setSaved(false);
                    command.clearError();
                  }}
                >
                  {actions[action]}
                </button>
              ))}
          </div>
        </>
      )}
      {intent && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (
              ready &&
              !busy &&
              !stale &&
              !command.conflict &&
              current?.allowed_actions.includes(intent.action) &&
              reason.trim()
            )
              void command
                .run<ProjectLifecycleView>(
                  path,
                  { action: intent.action, reason: reason.trim() },
                  intent.etag,
                )
                .then(accept);
          }}
        >
          <h3>确认{actions[intent.action]}</h3>
          <label>
            本次状态变更原因
            <textarea
              required
              maxLength={4000}
              rows={3}
              value={reason}
              disabled={busy}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
          <p className="small-note">
            取消只收起本次确认，不更改服务器状态。状态变化后须重新读取并再次明确选择；原原因保留。
          </p>
          {(stale || command.conflict) && (
            <p className="notice warning">
              项目状态已变化。请重新读取项目状态，再选择当前允许的动作；不会自动套用旧确认。
            </p>
          )}
          <div className="review-shortcuts">
            <button
              className="button primary"
              disabled={
                busy ||
                !ready ||
                stale ||
                command.conflict ||
                !current?.allowed_actions.includes(intent.action) ||
                !reason.trim()
              }
            >
              确认{actions[intent.action]}
            </button>
            <button
              type="button"
              className="button secondary"
              disabled={busy}
              onClick={() => {
                setIntent(null);
                setSaved(false);
              }}
            >
              取消此次变更
            </button>
          </div>
        </form>
      )}
      <ErrorNotice error={command.error} />
      {command.pending && (
        <div className="notice warning">
          <p>
            原请求尚未取得可靠回执。先恢复同一请求，不建立另一项变更；恢复历史回执后仍重新读取当前状态。
          </p>
          {!pendingValid && (
            <p role="alert">
              恢复记录的项目或动作身份不符，已阻止发送；请核对原项目记录。
            </p>
          )}
          <button
            className="button secondary"
            disabled={command.busy || !pendingValid}
            onClick={() =>
              void command.retry<ProjectLifecycleView>().then(accept)
            }
          >
            恢复原状态变更回执
          </button>
        </div>
      )}
      {saved && (
        <p className="inline-success" role="status">
          状态变更已记录。请以上方当前状态及读取提示为准；历史文件和报告仍保留。
        </p>
      )}
    </section>
  );
}
