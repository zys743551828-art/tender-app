import type { ReactNode } from "react";
import { useCallback, useState } from "react";
import type {
  Cancellation,
  DocumentView,
  Operation,
  ReviewStateView,
} from "./contracts";
import { supportsApi } from "./api";
import { useCommand } from "./useCommand";
import { Badge, ErrorNotice } from "./components";
import { Evidence } from "./Evidence";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import type { WorkspacePage } from "./workspaceTypes";

export function ReviewProgress({
  state,
  loading,
  error,
  unavailable,
  onRetry,
  etag,
  onNavigate,
}: {
  state?: ReviewStateView;
  loading: boolean;
  error?: unknown;
  unavailable: boolean;
  onRetry: () => void;
  etag?: string | null;
  onNavigate: (page: WorkspacePage, reviewId?: string) => void;
}) {
  const request = state?.request;
  const [cancelling, setCancelling] = useState(false);
  const [cancelBase, setCancelBase] = useState<{
    requestId: string;
    etag: string | null;
  } | null>(null);
  const [reason, setReason] = useState("");
  const command = useCommand(
    `review-request:cancel:${state?.bid_id ?? "none"}`,
  );
  const document = useResource<DocumentView>(
    request ? `/documents/${request.body_version_id}` : null,
  );
  const operation = useResource<Operation>(
    request ? `/operations/${request.prepare_operation_id}` : null,
    request &&
      ["preparing", "queued", "running", "cancel_requested"].includes(
        request.state,
      )
      ? 3000
      : 0,
  );
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const source =
    document.data?.id === request?.body_version_id &&
    document.data?.bid_id === state?.bid_id
      ? document.data
      : undefined;
  const heading =
    request &&
    {
      preparing: "正在准备本轮要求，完成后自动开始评审，可离开",
      blocked: request.review_id ? "本轮核心核对未完成" : "要求准备未完成",
      superseded: "资料已更新，原请求已过期",
      queued: "要求已准备，正在等待本轮评审",
      running: "正在评审本轮实际正文",
      cancel_requested: "正在取消本次处理",
      completed: "本次评审处理已结束，请查看真实范围与结论",
      cancelled: "本次要求准备请求已取消",
    }[request.state];
  return (
    <>
      <ResourceState
        unavailable={unavailable}
        loading={loading}
        error={error}
        hasData={!!state}
        onRetry={onRetry}
      />
      {request && (
        <ProgressContainer completed={request.state === "completed"}>
          <section
            className={`panel review-progress ${request.state === "blocked" || request.state === "superseded" ? "attention" : ""}`}
            aria-label="本次评审进度"
          >
            <div className="section-heading">
              <div>
                <span className="eyebrow">可恢复的本次处理</span>
                <h2>{heading}</h2>
                <p className="muted">
                  {request.state === "superseded"
                    ? "原请求不会悄悄改为另一份稿件的评审，请使用当前稿明确开始。"
                    : "受理、准备与任务结束均不等于核心核对通过。"}
                </p>
              </div>
              <Badge
                tone={
                  request.state === "blocked" || request.state === "superseded"
                    ? "warning"
                    : ""
                }
              >
                {request.trigger === "automatic"
                  ? "自动接续"
                  : request.trigger === "build_follow_up"
                    ? "生成稿接续"
                    : "明确发起"}
              </Badge>
            </div>
            <ResourceState
              {...document}
              hasData={!!source}
              onRetry={() => void document.reload()}
            />
            {document.data && !source && (
              <div className="notice error" role="alert">
                本次正文身份不一致，未打开其他资料，请刷新核对。
              </div>
            )}
            <p>
              本次正文：
              <strong>
                {source
                  ? `${source.filename} · 文件版本 ${source.file_revision}`
                  : "正在读取实际版本身份…"}
              </strong>
              {source && (
                <button className="text-button" onClick={() => setOpen(true)}>
                  查看本次正文原件
                </button>
              )}
            </p>
            <p className="small-note">
              本次资料修订 {request.material_revision} · 当前资料修订{" "}
              {state.material_revision}
              {request.material_revision !== state.material_revision ||
              request.body_version_id !== state.current_body_id
                ? " · 本请求对应先前输入，请核对当前稿"
                : ""}
            </p>
            {request.state === "preparing" &&
              request.trigger === "automatic" && (
                <p className="small-note">
                  按当前服务器请求准备，旧轮仍保留；准备结束后自动接续，无须再次开始。
                </p>
              )}
            {request.gaps.length > 0 && (
              <div className="notice warning">
                <ul>
                  {request.gaps.map((gap, index) => (
                    <li key={index}>{gap}</li>
                  ))}
                </ul>
              </div>
            )}
            {request.error_code && (
              <p className="small-note">处理原因：{request.error_code}</p>
            )}
            {request.state === "blocked" && (
              <p className="small-note">
                已保存的资料和依据保留。查看影响范围后，可进入评审工作面，使用当前稿重试并继续评审。
              </p>
            )}
            <ResourceState
              {...operation}
              hasData={!!operation.data}
              onRetry={() => void operation.reload()}
            />
            {operation.data?.bid_id === state.bid_id &&
              ["failed", "cancelled"].includes(operation.data.state) &&
              request.state !== "blocked" && (
                <div className="notice warning">
                  <p>
                    本次后台步骤
                    {operation.data.state === "failed" ? "执行失败" : "已取消"}
                    。请刷新请求进度并查看处理记录；不能将此步骤当作核对完成。
                  </p>
                </div>
              )}
            <ErrorNotice error={command.error} />
            {command.conflict && (
              <div className="notice warning">
                <p>
                  本次请求已有变化，取消原因已保留。请刷新核对实际处理对象后再提交。
                </p>
                <button className="button secondary" onClick={onRetry}>
                  刷新并核对本次请求
                </button>
              </div>
            )}
            {!request.review_id &&
              ["preparing", "blocked"].includes(request.state) &&
              supportsApi(
                "POST",
                `/bids/${state.bid_id}/review-requests/${request.request_id}/cancel`,
              ) && (
                <div className="request-cancellation">
                  <button
                    className="text-button"
                    aria-expanded={cancelling}
                    onClick={() => {
                      if (!cancelling)
                        setCancelBase({
                          requestId: request.request_id,
                          etag: etag ?? null,
                        });
                      setCancelling(!cancelling);
                    }}
                  >
                    取消本次准备请求
                  </button>
                  {cancelling && (
                    <form
                      className="decision-form"
                      onSubmit={(event) => {
                        event.preventDefault();
                        if (
                          !cancelBase?.etag ||
                          cancelBase.requestId !== request.request_id ||
                          cancelBase.etag !== etag
                        )
                          return;
                        const body: Cancellation = {
                          reason: reason.trim(),
                          cancel_pending_same_input: false,
                        };
                        void command
                          .run<ReviewStateView>(
                            `/bids/${state.bid_id}/review-requests/${request.request_id}/cancel`,
                            body,
                            cancelBase.etag,
                          )
                          .then((result) => {
                            if (result) {
                              setCancelling(false);
                              onRetry();
                            }
                          });
                      }}
                    >
                      <label>
                        取消原因
                        <input
                          value={reason}
                          required
                          maxLength={2000}
                          onChange={(event) => setReason(event.target.value)}
                        />
                      </label>
                      <p className="small-note">
                        仅取消这次要求准备，已保存资料保留。其他任务共用的解析不会被一并停止；若已经开始评审，请从该轮处理记录请求取消。
                      </p>
                      {(cancelBase?.requestId !== request.request_id ||
                        cancelBase?.etag !== etag) && (
                        <p className="notice warning">
                          准备请求或当前状态已变化，取消原因仍保留。请收起此表单，核对当前稿后重新打开，不会把先前原因悄悄套用到新请求。
                        </p>
                      )}
                      <button
                        className="button secondary"
                        disabled={
                          command.busy ||
                          !cancelBase?.etag ||
                          cancelBase.requestId !== request.request_id ||
                          cancelBase.etag !== etag ||
                          !reason.trim()
                        }
                      >
                        {command.busy ? "正在请求取消…" : "取消本次准备"}
                      </button>
                    </form>
                  )}
                </div>
              )}
            <div className="review-shortcuts">
              {["blocked", "superseded"].includes(request.state) && (
                <button
                  className="text-button"
                  onClick={() => onNavigate("review")}
                >
                  {request.state === "superseded"
                    ? "核对当前稿与重新开始"
                    : "核对范围并重试评审"}
                </button>
              )}
              {request.review_id && (
                <button
                  className="text-button"
                  onClick={() =>
                    onNavigate("review", request.review_id ?? undefined)
                  }
                >
                  打开本次实际评审
                </button>
              )}
              <button
                className="text-button"
                onClick={() => onNavigate("operations")}
              >
                查看处理记录与失败范围
              </button>
              <button className="text-button" onClick={onRetry}>
                刷新实际进度
              </button>
            </div>
          </section>
        </ProgressContainer>
      )}
      {open && source && <Evidence document={source} onClose={close} />}
    </>
  );
}

function ProgressContainer({
  completed,
  children,
}: {
  completed: boolean;
  children: ReactNode;
}) {
  return completed ? (
    <details className="review-history">
      <summary>最近一次评审处理记录（不代表通过）</summary>
      {children}
    </details>
  ) : (
    <>{children}</>
  );
}
