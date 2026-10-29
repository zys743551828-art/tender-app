import { useState } from "react";
import type {
  AssistantAction,
  AssistantJob,
  AuthoringDocument,
  AuthoringNode,
  Bid,
} from "./contracts";
import { Badge, ErrorNotice } from "./components";
import { ArtifactActions } from "./ArtifactActions";
import { assistantJobs, assistantReason } from "./assistantState";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import { useRecordedCommand } from "./useRecordedCommand";
import { useAssistantPolling } from "./useAssistantFeed";

const actionNames = {
  pending: "待明确处理",
  executed: "已执行并留存结果",
  rejected: "已拒绝此提议",
  expired: "提议已到期",
  stale: "依据已变化，未执行",
  failed: "执行失败",
};
function documentText(value: AuthoringDocument): string {
  const walk = (node: AuthoringNode): string =>
    node.type === "text"
      ? (node.text ?? "")
      : ("content" in node ? node.content : [])
          .map(walk)
          .join(
            ["paragraph", "heading", "listItem"].includes(node.type)
              ? "\n"
              : "",
          );
  return value.content.map(walk).join("\n");
}
export function AssistantActionCard({
  id,
  memberId,
}: {
  id: string;
  memberId: string;
}) {
  const resource = useResource<AssistantAction>(`/assistant/actions/${id}`);
  const action = resource.data?.action_id === id ? resource.data : undefined;
  const project = useResource<Bid>(
    action ? `/bids/${action.target_bid_id}` : null,
  );
  const command = useRecordedCommand(`assistant-action:${memberId}:${id}`);
  const target =
    project.data?.id === action?.target_bid_id ? project.data : undefined;
  function changed() {
    void resource.reload();
    window.dispatchEvent(new Event("server-snapshot-change"));
  }
  const resolution =
    action?.result && "assistant_resolution" in action.result
      ? action.result.assistant_resolution
      : undefined;
  return (
    <article className="assistant-action-card" aria-label="持久操作提议">
      <ResourceState
        {...resource}
        hasData={!!action}
        onRetry={() => void resource.reload()}
      />
      {resource.data && !action && (
        <p className="notice error">操作提议身份不一致，未执行其他卡片。</p>
      )}
      {action && (
        <>
          <div className="section-title">
            <h3>需要明确处理的提议</h3>
            <Badge tone={action.state === "pending" ? "warning" : ""}>
              {actionNames[action.state]}
            </Badge>
          </div>
          <ResourceState
            {...project}
            hasData={!!target}
            onRetry={() => void project.reload()}
          />
          <p>
            目标项目：<strong>{target?.title ?? "正在读取真实目标…"}</strong>
            。本卡不会由“好的”等聊天文字执行。
          </p>
          <p>{action.preview.effect}</p>
          {action.preview.kind === "request_review" && (
            <>
              <p>
                使用冻结的实际正文与资料修订{action.preview.material_revision}
                发起本轮处理；可能产生费用，受理不等于检查通过。
              </p>
              <ArtifactActions
                bidId={action.target_bid_id}
                documentId={action.preview.body_version_id}
                isPdf
                downloadLabel="核对提议中的受检稿原件"
              />
            </>
          )}
          {action.preview.kind === "generate_proposal" && (
            <p>
              按章节修订{action.preview.base_section_revision}
              生成候选，可能产生费用；不自动应用。要求：
              {action.preview.instruction}
            </p>
          )}
          {action.preview.kind === "knowledge_candidate" && (
            <>
              <h4>{action.preview.title}</h4>
              <p className="preserve-text">{action.preview.content}</p>
              <p>
                拟适用范围：{action.preview.scope}
                。只建立待完善候选，不发布、不创建项目事实。
              </p>
              {action.preview.source_version_ids.map((documentId) => (
                <ArtifactActions
                  key={documentId}
                  bidId={action.target_bid_id}
                  documentId={documentId}
                  isPdf
                  downloadLabel="核对候选知识来源原件"
                />
              ))}
            </>
          )}
          {action.preview.kind === "authoring_patch" && (
            <>
              <p>
                应用后追加正文修订。采纳不表示风险已解决，未保存的本地编辑须保留后核对。
              </p>
              <div className="assistant-patch">
                <section>
                  <h4>修改前</h4>
                  <pre>{documentText(action.preview.before)}</pre>
                </section>
                <section>
                  <h4>修改后</h4>
                  <pre>{documentText(action.preview.after)}</pre>
                </section>
              </div>
            </>
          )}
          {action.error_code && (
            <p className="notice warning">
              {assistantReason(action.error_code)}
            </p>
          )}
          {resolution && (
            <>
              <p>
                {resolution.business_effect_executed
                  ? "服务端已记录此明确操作的业务结果。"
                  : "此提议没有执行业务效果；保留真实处理结果。"}
              </p>
              {resolution.error_code && (
                <p>{assistantReason(resolution.error_code)}</p>
              )}
              {resolution.domain_result && (
                <a
                  href={
                    action.tool === "knowledge.candidate" &&
                    "id" in resolution.domain_result
                      ? `/knowledge?item=${encodeURIComponent(resolution.domain_result.id)}`
                      : `/bids/${action.target_bid_id}/${action.tool === "review.request" ? "review" : "authoring"}`
                  }
                >
                  打开此操作对应的业务工作面
                </a>
              )}
            </>
          )}
          <ErrorNotice error={command.error} />
          {action.state === "pending" && (
            <div className="review-shortcuts">
              <button
                className="button primary"
                disabled={
                  resource.loading ||
                  !!resource.error ||
                  project.loading ||
                  !!project.error ||
                  command.busy ||
                  !!command.pending ||
                  !resource.etag ||
                  !target ||
                  !!resource.error
                }
                onClick={() =>
                  void command
                    .run<AssistantAction>(
                      `/assistant/actions/${id}/resolve`,
                      { decision: "confirm" },
                      resource.etag ?? "",
                    )
                    .then(changed)
                }
              >
                {command.busy
                  ? "正在取得处理结果…"
                  : action.tool === "review.request"
                    ? "确认启动本轮评审"
                    : action.tool === "authoring.generate"
                      ? "确认生成章节候选"
                      : action.tool === "knowledge.candidate"
                        ? "确认建立知识候选"
                        : "应用这份正文修改"}
              </button>
              <button
                className="button secondary"
                disabled={
                  resource.loading ||
                  !!resource.error ||
                  command.busy ||
                  !!command.pending ||
                  !resource.etag
                }
                onClick={() =>
                  void command
                    .run<AssistantAction>(
                      `/assistant/actions/${id}/resolve`,
                      { decision: "reject" },
                      resource.etag ?? "",
                    )
                    .then(changed)
                }
              >
                拒绝此提议
              </button>
            </div>
          )}
          {command.pending && !command.busy && (
            <div className="notice warning">
              <p>
                原操作的答复尚未取得。先读取当前卡片，再恢复同一请求；不另建确认。
              </p>
              <button
                className="button secondary"
                onClick={() =>
                  void command.retry<AssistantAction>().then(changed)
                }
              >
                恢复原操作结果
              </button>
            </div>
          )}
          <button
            className="text-button"
            onClick={() => void resource.reload()}
          >
            刷新此提议的实际状态
          </button>
          <p>
            <a href={`/assistant?action=${encodeURIComponent(id)}`}>
              打开这张操作卡的固定链接
            </a>
          </p>
          <details className="identity-details">
            <summary>提议身份、基准与期限</summary>
            <p>
              基础修订{action.base_revision}；到期
              {new Date(action.expires_at).toLocaleString("zh-CN")}；记录{id}
              ；请求摘要{action.request_digest}；处理成员
              {action.resolved_by ?? "尚无明确处理人"}。
            </p>
          </details>
        </>
      )}
    </article>
  );
}

export function AssistantJobCard({
  id,
  memberId,
  conversationId,
  bidId,
}: {
  id: string;
  memberId: string;
  conversationId: string;
  bidId: string | null;
}) {
  const interval = useAssistantPolling();
  const resource = useResource<AssistantJob>(`/assistant/jobs/${id}`, interval);
  const job =
    resource.data?.id === id &&
    resource.data.conversation_id === conversationId &&
    resource.data.bid_id === bidId
      ? resource.data
      : undefined;
  const [details, setDetails] = useState(false);
  const cancel = useRecordedCommand(`assistant-cancel:${memberId}:${id}`);
  const active =
    job &&
    ["queued", "running", "cancel_requested"].includes(job.operation.state);
  return (
    <article className="assistant-job-card">
      <ResourceState
        {...resource}
        hasData={!!job}
        onRetry={() => void resource.reload()}
      />
      {resource.data && !job && (
        <p className="notice error">助手处理记录的会话范围不一致。</p>
      )}
      {job && (
        <>
          <div className="section-title">
            <h3>{job.kind === "answer" ? "本次助手答复" : "章节候选生成"}</h3>
            <Badge tone={job.requires_billing_reconciliation ? "warning" : ""}>
              {job.requires_billing_reconciliation
                ? "调用／费用待核对"
                : assistantJobs[job.operation.state]}
            </Badge>
          </div>
          <p>
            {job.cancel_requested && !job.cancellation_terminal
              ? "取消请求已收到，尚未到实际取消终态；费用另行核对。"
              : job.cancellation_terminal
                ? "服务端已记录取消终态。"
                : job.publication?.state === "published"
                  ? "回答或候选已由服务器发布，请在消息或提议中核对。"
                  : job.publication?.state === "stale"
                    ? "来源或上下文已变化，本次候选未采用。"
                    : job.operation.state === "succeeded"
                      ? "处理步骤已结束，仍需核对发布结果；不表示领域操作已执行。"
                      : "处理记录持久保存，可离开后从同一主会话恢复。"}
          </p>
          {job.requires_billing_reconciliation && (
            <p className="notice warning">
              调用已经预留或费用未知，先等待服务端核账；不要用新消息、模板或标识重复付费。
            </p>
          )}
          {(job.publication?.error_code || job.operation.error_code) && (
            <p className="notice warning">
              {assistantReason(
                job.publication?.error_code ?? job.operation.error_code ?? "",
              )}
            </p>
          )}
          <ErrorNotice error={cancel.error} />
          {active && !job.cancel_requested && (
            <button
              className="button secondary"
              disabled={cancel.busy || !!cancel.pending}
              onClick={() =>
                void cancel
                  .run<AssistantJob>(`/assistant/jobs/${id}/cancel`, {}, "")
                  .then(() => void resource.reload())
              }
            >
              请求取消这次处理
            </button>
          )}
          {cancel.pending && !cancel.busy && (
            <button
              className="button secondary"
              onClick={() =>
                void cancel
                  .retry<AssistantJob>()
                  .then(() => void resource.reload())
              }
            >
              恢复原取消请求结果
            </button>
          )}
          <button
            className="text-button"
            onClick={() => setDetails(!details)}
            aria-expanded={details}
          >
            查看调用与发布范围
          </button>
          {details && (
            <div className="small-note">
              <p>
                调用：{job.model_call?.state ?? "尚无调用账本"}；计费：
                {job.model_call?.billing_state ?? "未取得"}；发布：
                {job.publication?.state ?? "尚未发布"}。
              </p>
              <p>
                自动重试未获授权。记录{id}，操作{job.operation.id}
                ；聊天不进入正式评分。
              </p>
            </div>
          )}
        </>
      )}
    </article>
  );
}
