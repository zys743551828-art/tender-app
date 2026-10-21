import { useState } from "react";
import type { AuthoringSnapshot, BuildView, Operation } from "./contracts";
import { ArtifactActions } from "./ArtifactActions";
import { generatedFilename } from "./artifactNames";
import { Badge } from "./components";
import { ResourceState } from "./ResourceState";
import { authoringText } from "./richEditorSchema";
import { useResource } from "./useResource";
import { validBuildView } from "./authoringBuildRecovery";
import type { ReceivedBuild } from "./authoringBuildRecovery";
import { AuthoringOutputAdoption } from "./AuthoringOutputAdoption";

const explanations: Record<string, string> = {
  RENDER_SANDBOX_NOT_ATTESTED:
    "文件已生成，正式提交前请核对字体、分页与版面；当前转换环境尚未完成正式交付验收。",
  TOC_PAGE_NUMBERS_UNKNOWN: "目录页码尚未实测，当前目录不能作为准确页码依据。",
  ACTUAL_SECTION_PAGE_RANGES_UNKNOWN:
    "各章实际物理页范围尚未测得；计划页数不代表实际页数。",
  AUTHORING_RICH_RENDER_NOT_CONFIGURED:
    "表格与图片的受控转换器未配置。可取回已生成的 Word；PDF、目录页码及章页范围仍未知。",
  PAGE_CORRESPONDENCE_UNVERIFIED:
    "页眉页脚及页码对应尚未完整核验，请核对生成原页。",
  PLACEHOLDER_CONTENT_PRESENT: "正文仍可能有待填写内容，请人工检查后再交付。",
};

export function AuthoringBuildResult({
  bidId,
  draftId,
  item,
  projectTitle,
  memberId,
  disabled = false,
  onPackages,
}: {
  bidId: string;
  draftId: string;
  item: ReceivedBuild;
  projectTitle: string;
  memberId: string;
  disabled?: boolean;
  onPackages?: () => void;
}) {
  const result = useResource<BuildView>(`/builds/${item.id}`, 2500);
  const verified = validBuildView(result.data, bidId, draftId, item.id)
    ? result.data
    : undefined;
  const operation = useResource<Operation>(
    verified ? `/operations/${verified.operation_id}` : null,
    2500,
  );
  const [showSnapshot, setShowSnapshot] = useState(false);
  const snapshot = useResource<AuthoringSnapshot>(
    showSnapshot && verified
      ? `/bids/${bidId}/draft-snapshots/${verified.draft_snapshot_id}`
      : null,
  );
  if (
    (result.data && !verified) ||
    (verified &&
      ((item.snapshotId && item.snapshotId !== verified.draft_snapshot_id) ||
        (item.revision !== null &&
          item.revision !== verified.identity.draft_revision))) ||
    (operation.data &&
      (!verified ||
        operation.data.id !== verified.operation_id ||
        operation.data.bid_id !== bidId ||
        operation.data.kind !== "build" ||
        operation.data.handler_version !== "export/1" ||
        operation.data.input_digest !== verified.identity.input_digest))
  )
    return (
      <div role="alert" className="notice error">
        生成任务或固定快照身份不一致，未展示输出或采用入口。
      </div>
    );
  const op = operation.data;
  const terminal =
    op && ["failed", "cancelled", "succeeded"].includes(op.state);
  const frozen =
    snapshot.data &&
    verified &&
    snapshot.data.snapshot_id === verified.draft_snapshot_id &&
    snapshot.data.snapshot_digest === verified.identity.snapshot_digest
      ? snapshot.data
      : undefined;
  return (
    <article className="build-result">
      <div className="section-heading">
        <strong>
          {verified
            ? `来自草稿修订 ${verified.identity.draft_revision}`
            : "正在核对固定快照"}
        </strong>
        <Badge tone={op?.state === "failed" ? "warning" : "neutral"}>
          {op?.state === "failed"
            ? "生成任务失败"
            : op?.state === "cancelled"
              ? "生成任务已取消"
              : op?.state === "succeeded"
                ? "生成任务已完成"
                : "生成处理中"}
        </Badge>
      </div>
      <ResourceState
        {...result}
        hasData={!!result.data}
        onRetry={() => void result.reload()}
      />
      <ResourceState
        {...operation}
        hasData={!!op}
        onRetry={() => void operation.reload()}
      />
      {verified && (
        <>
          <details className="coverage-details">
            <summary>核对本次固定快照身份</summary>
            <p className="small-note identity-ref">
              {verified.draft_snapshot_id}
            </p>
            <p className="small-note">
              草稿修订 {verified.identity.draft_revision}
              ；目录、版式和输出格式来自本次原请求。后续编辑不会改变此记录。
            </p>
          </details>
          <button
            type="button"
            className="text-button"
            onClick={() => setShowSnapshot((old) => !old)}
          >
            {showSnapshot ? "收起本次快照正文" : "查看本次快照正文"}
          </button>
          {showSnapshot && (
            <>
              <ResourceState
                {...snapshot}
                hasData={!!snapshot.data}
                onRetry={() => void snapshot.reload()}
              />
              {snapshot.data && !frozen && (
                <div role="alert" className="notice error">
                  快照摘要与本次构建不一致，未展示其他正文。
                </div>
              )}
              {frozen && (
                <div className="snapshot-reading">
                  <h4>{frozen.title}</h4>
                  {frozen.sections.map((section, index) => (
                    <section key={index}>
                      <strong>{section.attrs.title}</strong>
                      <pre>{authoringText(section)}</pre>
                    </section>
                  ))}
                </div>
              )}
            </>
          )}
          {verified.layout && (
            <section
              className="authoring-layout-measurements"
              aria-label="目录与章节物理页核对"
            >
              <h4>目录与章节物理页</h4>
              <p className="small-note">
                排版方式：
                {verified.layout.pagination_mode === "chapter_start_new_page"
                  ? "每章另起一页"
                  : "连续排版"}
                。
                {verified.layout.fixed_point
                  ? "本次目录页码已达到稳定核对结果。"
                  : "目录页码尚未达到稳定核对结果。"}
                此结果仅描述目录导航，不代表表格、图片或整体视觉已完成交付验收。
              </p>
              <p className="small-note">
                实际总页数：{verified.layout.page_count ?? "未知"}；已核对轮次：
                {verified.layout.iteration_count} / 3。
              </p>
              {!!verified.layout.entries.length && (
                <table>
                  <thead>
                    <tr>
                      <th>章节位置</th>
                      <th>起始物理页</th>
                      <th>末物理页</th>
                      <th>目录标注页</th>
                    </tr>
                  </thead>
                  <tbody>
                    {verified.layout.entries.map((entry, index) => (
                      <tr key={entry.section_id}>
                        <td>章节 {index + 1}</td>
                        <td>{entry.start_page ?? "未知"}</td>
                        <td>{entry.end_page ?? "未知"}</td>
                        <td>{entry.printed_toc_page ?? "未知"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          )}
          {verified.follow_up.requested && (
            <p className="notice warning">
              此历史构建曾明确请求后续核对；当前采用状态：
              {
                (
                  {
                    pending: "等待处理",
                    adopted: "已登记正文与核对请求",
                    needs_selection: "条件变化，需重新选择",
                    failed: "未完成",
                    not_requested: "未请求",
                  } as const
                )[verified.follow_up.state]
              }
              。采用回执不代表评审已完成。
            </p>
          )}
          {!verified.outputs.length && (
            <p className="small-note">
              {terminal
                ? "任务已结束，尚无可用格式输出。请查看操作状态与失败原因。"
                : "尚无格式输出；受理不表示文件已生成。"}
            </p>
          )}
          {verified.outputs.map((output) => (
            <div className="build-output" key={output.format}>
              <strong>{output.format === "docx" ? "Word" : "PDF"}</strong>
              <Badge
                tone={output.state === "succeeded" ? "success" : "warning"}
              >
                {output.state === "succeeded"
                  ? "此格式生成成功"
                  : output.state === "failed"
                    ? "此格式生成失败"
                    : "此格式正在生成"}
              </Badge>
              {output.gaps.map((gap, index) => (
                <p className="small-note" key={index}>
                  {explanations[gap] ?? gap}
                </p>
              ))}
              {op &&
                output.state === "succeeded" &&
                output.document_version_id && (
                  <ArtifactActions
                    bidId={bidId}
                    documentId={output.document_version_id}
                    isPdf={output.format === "pdf"}
                    expectedArtifactKind="bid_body"
                    expectedMediaType={
                      output.format === "pdf"
                        ? "application/pdf"
                        : "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    }
                    downloadLabel={`下载投标正文（${output.format === "docx" ? "Word" : "PDF"}）`}
                    suggestedFilename={generatedFilename(
                      projectTitle,
                      verified.draft_snapshot_id,
                      output.format,
                    )}
                  />
                )}
              {op?.state === "succeeded" &&
                output.state === "succeeded" &&
                output.document_version_id && (
                  <AuthoringOutputAdoption
                    bidId={bidId}
                    memberId={memberId}
                    build={verified}
                    documentId={output.document_version_id}
                    disabled={disabled}
                    onPackages={onPackages}
                  />
                )}
            </div>
          ))}
        </>
      )}
    </article>
  );
}
