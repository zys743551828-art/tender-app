import type { HistoricalImportRecord } from "./contracts";
import { ArtifactActions } from "./ArtifactActions";

const historicalScoreNames = {
  technical_total: "技术总分",
  comprehensive_total: "综合总分",
  unknown: "成绩口径未知",
};
export function HistoricalImportRecordDetails({
  record,
  allowDownloads = false,
}: {
  record: HistoricalImportRecord;
  allowDownloads?: boolean;
}) {
  return (
    <div className="historical-import-original">
      <dl>
        <dt>外部记录</dt>
        <dd>{record.external_record_id}</dd>
        <dt>实际提交</dt>
        <dd>{record.submitted_at}</dd>
        <dt>成绩口径</dt>
        <dd>{historicalScoreNames[record.score_kind]}</dd>
        <dt>得分 / 满分</dt>
        <dd>
          {record.value === null
            ? "未知"
            : `${record.value} / ${record.maximum}`}
        </dd>
        <dt>成绩取得</dt>
        <dd>{record.known_at ?? "未记录"}</dd>
      </dl>
      <p className="historical-import-explanation">{record.explanation}</p>
      <details>
        <summary>核对确切项目与原件版本</summary>
        <dl>
          <dt>项目</dt>
          <dd>{record.bid_id}</dd>
          <dt>实交正文</dt>
          <dd>{record.actual_document_version_id}</dd>
          <dt>实交证明</dt>
          <dd>{record.evidence_ref}</dd>
          <dt>成绩原件</dt>
          <dd>{record.source_version_id ?? "无"}</dd>
        </dl>
        {allowDownloads && (
          <div className="historical-import-toolbar">
            <ArtifactActions
              bidId={record.bid_id}
              documentId={record.actual_document_version_id}
              isPdf={false}
              downloadLabel="下载确切实交正文"
            />
            <ArtifactActions
              bidId={record.bid_id}
              documentId={record.evidence_ref}
              isPdf={false}
              downloadLabel="下载实交证明原件"
            />
            {record.source_version_id && (
              <ArtifactActions
                bidId={record.bid_id}
                documentId={record.source_version_id}
                isPdf={false}
                downloadLabel="下载官方成绩原件"
              />
            )}
          </div>
        )}
      </details>
    </div>
  );
}
