import { useState } from "react";
import { supportsApi } from "./api";
import type { Accepted, ReviewView } from "./contracts";
import type {
  ReportContextView,
  ReportExportPage,
  ReportExportView,
  ReportRequest,
} from "./contracts";
import { ArtifactActions } from "./ArtifactActions";
import { Badge, ErrorNotice } from "./components";
import { rememberOperation } from "./operationStorage";
import { ResourceState } from "./ResourceState";
import { useDirectory } from "./useDirectory";
import { useRecordedCommand } from "./useRecordedCommand";
import { useResource } from "./useResource";

export function ReportPanel({
  bidId,
  memberId,
  reviewId,
  projectTitle,
}: {
  bidId: string;
  memberId: string;
  reviewId: string;
  projectTitle: string;
}) {
  const available = supportsApi("GET", `/reviews/${reviewId}/report-context`);
  const identity = useResource<ReviewView>(
    available ? `/reviews/${reviewId}` : null,
  );
  const validIdentity =
    identity.data?.id === reviewId && identity.data.bid_id === bidId;
  const context = useResource<ReportContextView>(
    validIdentity ? `/reviews/${reviewId}/report-context` : null,
  );
  const history = useDirectory<ReportExportPage>(
    validIdentity ? `/reviews/${reviewId}/report-exports?limit=20` : null,
  );
  const command = useRecordedCommand(`report:${memberId}:${bidId}:${reviewId}`);
  const [received, setReceived] = useState<string[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [selection, setSelection] = useState("review_report:docx");
  const [needsReread, setNeedsReread] = useState(false);
  const data = context.data?.review_id === reviewId ? context.data : undefined;
  const foreign = context.data && !data;
  const wrongHistory = history.items.some(
    (item) => item.review_id !== reviewId,
  );
  const ids = [
    ...new Set([...received, ...history.items.map((item) => item.id)]),
  ];
  async function accepted(result: Accepted) {
    if (result.resource_kind !== "report" || result.operation.bid_id !== bidId)
      throw new Error("报告受理身份与本项目不一致，请重读报告历史核对。");
    rememberOperation(bidId, result.operation.id);
    setReceived((old) => [
      result.resource_id,
      ...old.filter((id) => id !== result.resource_id),
    ]);
    await history.reload();
  }
  async function create() {
    setError(null);
    try {
      const selected = data?.supported.find(
        (item) => `${item.artifact_kind}:${item.format}` === selection,
      );
      if (!data || !selected || !context.etag || context.error || needsReread)
        throw new Error("请读取本轮报告展示依据，并选择实际支持的格式。");
      const body: ReportRequest = {
        ...selected,
        presentation_revision: data.presentation_revision,
        source_impact_revision: data.source_impact_revision,
      };
      const result = await command.run<Accepted>(
        `/reviews/${reviewId}/report-exports`,
        body,
        context.etag,
      );
      if (result) await accepted(result.data);
    } catch (failure) {
      setError(failure);
    }
  }
  if (!available) return null;
  return (
    <section className="panel report-panel">
      <div className="section-heading">
        <div>
          <h2>评审报告与原页批注</h2>
          <p className="small-note">
            指定评审轮次 {reviewId.slice(0, 8)}
            。报告和批注副本独立保存，不能作为干净投标正文登记。
          </p>
        </div>
        <button
          type="button"
          className="text-button"
          disabled={command.busy || !!command.pending}
          onClick={() => {
            void context.reload().then(() => command.clearError());
            void history.reload();
            setNeedsReread(false);
          }}
        >
          重读报告展示依据
        </button>
      </div>
      <ResourceState
        {...identity}
        hasData={!!identity.data}
        onRetry={() => void identity.reload()}
      />
      {identity.data && !validIdentity && (
        <div className="notice error" role="alert">
          评审不属于当前项目，未读取其报告或生成副本。
        </div>
      )}
      <ResourceState
        {...context}
        hasData={!!data}
        onRetry={() => void context.reload()}
      />
      {foreign && (
        <div className="notice error" role="alert">
          报告上下文轮次不一致，未使用其他评审的正文。
        </div>
      )}
      {data && (
        <>
          <div
            className={`notice ${data.current && data.source_state === "effective" ? "neutral" : "warning"}`}
          >
            <div>
              <strong>{data.original_name}</strong>
              <p>
                {data.current
                  ? "对应当前评审输入"
                  : "历史固定输入，保留原受检稿"}{" "}
                · 展示修订 {data.presentation_revision} · 来源影响修订{" "}
                {data.source_impact_revision}
              </p>
              {data.source_state !== "effective" && (
                <p>
                  来源状态已变化或待核验（{data.source_state}
                  ），导出会保留相应影响说明，不形成当前可提交结论。
                </p>
              )}
            </div>
          </div>
          <form
            className="report-form"
            onSubmit={(event) => {
              event.preventDefault();
              void create();
            }}
          >
            <label>
              报告用途与格式
              <select
                value={selection}
                disabled={command.busy || !!command.pending}
                onChange={(event) => setSelection(event.target.value)}
              >
                {!data.supported.some(
                  (item) =>
                    `${item.artifact_kind}:${item.format}` === selection,
                ) && (
                  <option value={selection}>
                    原选择当前不支持，请重新选择
                  </option>
                )}
                {data.supported.map((item) => (
                  <option
                    key={`${item.artifact_kind}:${item.format}`}
                    value={`${item.artifact_kind}:${item.format}`}
                  >
                    {reportLabel(item)}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="button secondary"
              disabled={
                command.busy ||
                !!command.pending ||
                !!context.error ||
                context.loading ||
                needsReread ||
                command.conflict ||
                !data.supported.some(
                  (item) =>
                    `${item.artifact_kind}:${item.format}` === selection,
                )
              }
            >
              {command.busy ? "正在申请生成…" : "生成此用途副本"}
            </button>
          </form>
          <p className="small-note">
            申请受理后继续显示实际生成状态；成功时按此版本取件。Word原页批注当前不支持。
          </p>
        </>
      )}
      <ErrorNotice error={error ?? command.error} />
      {command.conflict && (
        <p className="small-note">
          展示政策或来源影响已经变化。请重读依据后明确生成，原报告继续保留。
        </p>
      )}
      {command.pending && !command.busy && (
        <div className="notice warning">
          <div>
            <strong>报告申请结果尚未取得</strong>
            <p>恢复同一申请，保留原格式与展示身份，不另建一次生成意图。</p>
            <button
              type="button"
              className="button secondary"
              disabled={command.busy}
              onClick={() =>
                void command.retry<Accepted>().then(async (result) => {
                  if (result)
                    try {
                      await accepted(result.data);
                    } catch (failure) {
                      setError(failure);
                    }
                })
              }
            >
              恢复原报告申请结果
            </button>
          </div>
        </div>
      )}
      <h3>已保存的报告与批注副本</h3>
      <ResourceState
        {...history}
        hasData={!!history.data}
        onRetry={() => void history.reload()}
      />
      <ErrorNotice error={history.moreError} />
      {wrongHistory ? (
        <div className="notice error" role="alert">
          报告历史轮次身份不一致，未展示其他轮次产物。
        </div>
      ) : (
        ids.map((id) => (
          <ReportCard
            key={id}
            bidId={bidId}
            reviewId={reviewId}
            id={id}
            projectTitle={projectTitle}
            onContextChanged={() => setNeedsReread(true)}
          />
        ))
      )}
      {history.data && !ids.length && (
        <p className="small-empty">
          本轮暂无已申请的报告。不会提供空文件或用投标正文冒充报告。
        </p>
      )}
      {history.hasMore && (
        <button
          type="button"
          className="text-button"
          disabled={history.moreBusy}
          onClick={() => void history.loadMore()}
        >
          加载更早的报告副本
        </button>
      )}
    </section>
  );
}

function reportLabel(item: Pick<ReportRequest, "artifact_kind" | "format">) {
  return `${item.artifact_kind === "review_report" ? "评审报告" : "批注审阅稿"}（${item.format === "docx" ? "Word" : "PDF"}）`;
}
function ReportCard({
  bidId,
  reviewId,
  id,
  projectTitle,
  onContextChanged,
}: {
  bidId: string;
  reviewId: string;
  id: string;
  projectTitle: string;
  onContextChanged: () => void;
}) {
  const resource = useResource<ReportExportView>(`/report-exports/${id}`, 2500);
  const report = resource.data;
  const valid = report?.id === id && report.review_id === reviewId;
  const stateNames = {
    queued: "等待生成",
    running: "正在生成",
    cancel_requested: "正在取消",
    succeeded: "生成完成",
    failed: "生成失败",
    cancelled: "已取消",
  };
  return (
    <article className="report-card">
      <ResourceState
        {...resource}
        hasData={!!report}
        onRetry={() => void resource.reload()}
      />
      {report && !valid && (
        <div className="notice error" role="alert">
          报告副本身份不一致，未提供其他轮次文件。
        </div>
      )}
      {valid && (
        <>
          <div className="section-heading">
            <strong>{reportLabel(report)}</strong>
            <Badge tone={report.state === "failed" ? "warning" : ""}>
              {stateNames[report.state]}
            </Badge>
          </div>
          <p className="small-note">
            副本 {report.id.slice(0, 8)} · 展示修订{" "}
            {report.presentation_revision} · 来源影响修订{" "}
            {report.source_impact_revision}
          </p>
          {report.gaps.map((gap, index) => (
            <p className="small-note" key={index}>
              {gap === "RENDER_SANDBOX_NOT_ATTESTED"
                ? "当前为本地构建，转换隔离尚未达到生产验收要求，请核对版面。"
                : gap === "ANNOTATION_WITHOUT_BODY_RANGE"
                  ? "部分问题没有可定位的正文片段，列在首页问题索引；不表示首页正文违反。批注只定位到物理页，不提供逐字高亮。"
                  : gap}
            </p>
          ))}
          {report.state === "failed" && (
            <div className="notice error" role="alert">
              <div>
                <strong>此副本生成失败</strong>
                <p>
                  {report.error_code ?? "请重读处理状态查看失败原因"}
                  。原受检稿及其他已生成副本保留。
                </p>
                <button
                  type="button"
                  className="text-button"
                  onClick={onContextChanged}
                >
                  重新核对展示依据后再申请
                </button>
              </div>
            </div>
          )}
          {report.state === "succeeded" && report.document_version_id && (
            <ArtifactActions
              bidId={bidId}
              documentId={report.document_version_id}
              isPdf={report.format === "pdf"}
              downloadLabel={`下载${reportLabel(report)}`}
              suggestedFilename={filename(projectTitle, report)}
              expectedArtifactKind={report.artifact_kind}
              expectedMediaType={
                report.format === "pdf"
                  ? "application/pdf"
                  : "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              }
            />
          )}
          {report.state === "succeeded" && !report.document_version_id && (
            <div className="notice warning">
              生成状态尚未提供真实文件版本，请刷新核对后取件。
            </div>
          )}
        </>
      )}
    </article>
  );
}
function filename(title: string, report: ReportExportView) {
  const safe =
    Array.from(title.replace(/[<>:"/\\|?*]/g, "_"))
      .map((char) => (char.charCodeAt(0) < 32 ? "_" : char))
      .slice(0, 48)
      .join("")
      .trim() || "投标项目";
  return `${safe}_${report.artifact_kind === "review_report" ? "评审报告" : "批注审阅稿"}_${report.id.slice(0, 12)}.${report.format}`;
}
