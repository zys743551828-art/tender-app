import { useCallback, useEffect, useState } from "react";
import { supportsApi } from "./api";
import type { DiagnosticPage, Operation, ReviewView } from "./contracts";
import { Badge, ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { useCommand } from "./useCommand";
import { useResource } from "./useResource";

export function OperationCenter({
  bidId,
  currentOperationId: projectedOperationId,
  preparationOperationId,
  reviewId,
}: {
  bidId: string;
  currentOperationId?: string;
  preparationOperationId?: string;
  reviewId?: string;
}) {
  const review = useResource<ReviewView>(
    reviewId ? `/reviews/${reviewId}` : null,
  );
  const currentOperationId =
    review.data?.bid_id === bidId
      ? review.data.operation_id
      : projectedOperationId;
  const [ids, setIds] = useState<string[]>([]);
  useEffect(() => {
    const load = () => {
      try {
        const saved = JSON.parse(
          localStorage.getItem(`tender:operations:${bidId}`) ?? "[]",
        ) as string[];
        setIds([
          ...new Set([
            ...(currentOperationId ? [currentOperationId] : []),
            ...(preparationOperationId ? [preparationOperationId] : []),
            ...saved,
          ]),
        ]);
      } catch {
        setIds([
          ...(currentOperationId ? [currentOperationId] : []),
          ...(preparationOperationId ? [preparationOperationId] : []),
        ]);
      }
    };
    load();
    window.addEventListener("operations-updated", load);
    return () => window.removeEventListener("operations-updated", load);
  }, [bidId, currentOperationId, preparationOperationId]);
  const [completed, setCompleted] = useState<Record<string, boolean>>({});
  const reportState = useCallback((id: string, succeeded: boolean) => {
    setCompleted((old) =>
      old[id] === succeeded ? old : { ...old, [id]: succeeded },
    );
  }, []);
  const ended = ids.filter((id) => completed[id]);
  const ongoing = ids.filter((id) => !completed[id]);
  return (
    <section className="operation-center">
      <div className="panel">
        <div className="section-heading">
          <div>
            <h2>处理记录</h2>
            <details className="identity-details">
              <summary>处理记录的恢复范围</summary>
              <p>
                服务器当前准备／评审与此浏览器收到的受理记录；实际状态从服务端重新读取。关闭页面不取消任务。
              </p>
            </details>
          </div>
        </div>
        {ids.length === 0 && (
          <p className="small-empty">
            尚未收到可恢复的任务记录。上传原件或明确开始评审后，会显示对应处理过程。
          </p>
        )}
      </div>
      <ResourceState
        {...review}
        hasData={!!review.data}
        onRetry={() => void review.reload()}
      />
      {review.data && review.data.bid_id !== bidId && (
        <div className="notice error" role="alert">
          评审任务项目身份不一致，未使用其操作记录。
        </div>
      )}
      {ongoing.map((id) => (
        <OperationCard key={id} id={id} bidId={bidId} onState={reportState} />
      ))}
      {ended.length > 0 && (
        <details className="coverage-details completed-operations">
          <summary>已完成 {ended.length} 项处理</summary>
          <p className="small-note">
            处理结束不等于核对通过；风险、覆盖缺口与待办仍在对应工作面保留。
          </p>
          {ended.map((id) => (
            <OperationCard
              key={id}
              id={id}
              bidId={bidId}
              onState={reportState}
            />
          ))}
        </details>
      )}
    </section>
  );
}

const states = {
  queued: "等待处理",
  running: "正在处理",
  cancel_requested: "正在取消",
  succeeded: "执行已结束",
  failed: "执行失败",
  cancelled: "已取消",
};
function operationName(kind: string) {
  if (kind.includes("prepare")) return "评审要求准备";
  if (kind.includes("review")) return "本轮评审";
  if (kind.includes("parse")) return "资料解析";
  if (kind.includes("verify")) return "原件核验";
  if (kind.includes("commit")) return "资料入库";
  return "后台处理";
}
function OperationCard({
  id,
  bidId,
  onState,
}: {
  id: string;
  bidId: string;
  onState: (id: string, succeeded: boolean) => void;
}) {
  const resource = useResource<Operation>(`/operations/${id}`, 3000);
  const operation = resource.data;
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const diagnostics = useResource<DiagnosticPage>(
    showDiagnostics ? `/operations/${id}/diagnostics` : null,
  );
  const [reason, setReason] = useState("");
  const [cancelOpen, setCancelOpen] = useState(false);
  const command = useCommand(`operation:cancel:${id}`);
  const belongs = operation?.bid_id === bidId;
  useEffect(() => {
    if (operation)
      onState(
        id,
        operation.bid_id === bidId && operation.state === "succeeded",
      );
  }, [operation, id, bidId, onState]);
  return (
    <article className="panel operation-card">
      <div className="section-heading">
        <div>
          <h3>资料与评审处理</h3>
          {belongs && <p className="muted">{operationName(operation.kind)}</p>}
        </div>
        {belongs && (
          <Badge tone={operation.state === "failed" ? "warning" : ""}>
            {states[operation.state]}
          </Badge>
        )}
      </div>
      <ResourceState
        {...resource}
        hasData={!!operation}
        onRetry={() => void resource.reload()}
      />
      {operation && !belongs && (
        <div className="notice error">
          此任务不属于当前项目，不显示或执行其操作。
        </div>
      )}
      {belongs && (
        <div className="operation-content">
          {operation.state !== "succeeded" && (
            <p className="muted">
              {operation.state === "cancel_requested"
                ? "取消请求已收到，等待服务端记录终态；外部调用可能已经产生费用。"
                : operation.state === "failed"
                  ? "已完成的有效记录保留。请查看失败范围，再从对应资料或评审发起新的处理尝试。"
                  : "后台处理可在离开页面后继续，重新打开将按业务记录恢复。"}
            </p>
          )}
          <div className="operation-actions">
            <button
              className="text-button"
              onClick={() => setShowDiagnostics(!showDiagnostics)}
              aria-expanded={showDiagnostics}
            >
              查看字段与范围详情
            </button>
            {["queued", "running"].includes(operation.state) &&
              supportsApi("POST", `/operations/${id}/cancel`) && (
                <button
                  className="text-button"
                  onClick={() => setCancelOpen(!cancelOpen)}
                  aria-expanded={cancelOpen}
                >
                  取消本次处理
                </button>
              )}
          </div>
          {showDiagnostics && (
            <>
              <p className="small-note">
                记录标识：{operation.id} · 执行版本：{operation.handler_version}
              </p>
              <ResourceState
                {...diagnostics}
                hasData={!!diagnostics.data}
                onRetry={() => void diagnostics.reload()}
              />
              {diagnostics.data?.items.map((item) => (
                <div className="diagnostic-item" key={item.id}>
                  <strong>{item.message}</strong>
                  <small>
                    {item.field_path} ·{" "}
                    {item.action === "rejected" ? "本项未采用" : "本项待核对"}
                  </small>
                </div>
              ))}
              {diagnostics.data?.items.length === 0 && (
                <p className="small-empty">
                  没有已记录的字段校验详情。此列表为空不代表业务检查通过。
                </p>
              )}
            </>
          )}
          {cancelOpen && (
            <form
              className="decision-form"
              onSubmit={(event) => {
                event.preventDefault();
                void command
                  .run<Operation>(
                    `/operations/${id}/cancel`,
                    { reason: reason.trim(), cancel_pending_same_input: false },
                    resource.etag,
                  )
                  .then((result) => {
                    if (result) {
                      setCancelOpen(false);
                      void resource.reload();
                    }
                  });
              }}
            >
              <label>
                取消原因
                <input
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  required
                />
              </label>
              <p className="muted">
                仅请求取消所选尝试，不撤销已确认决定，不承诺外部调用退款。
              </p>
              <ErrorNotice error={command.error} />
              {command.conflict && (
                <button
                  type="button"
                  className="text-button"
                  onClick={() => void resource.reload()}
                >
                  状态已变化，刷新后重新核对
                </button>
              )}
              <button
                className="button secondary"
                disabled={command.busy || !resource.etag || !reason.trim()}
              >
                请求取消本次处理
              </button>
            </form>
          )}
        </div>
      )}
    </article>
  );
}
