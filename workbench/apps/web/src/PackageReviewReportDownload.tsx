import { useEffect, useRef, useState } from "react";
import { api, objectFetch, sizeLabel } from "./api";
import type {
  DocumentView,
  DownloadGrant,
  PackageReviewReportView,
} from "./contracts";
import { ErrorNotice } from "./components";
import { Evidence } from "./Evidence";
export default function PackageReviewReportDownload({
  report,
}: {
  report: PackageReviewReportView;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null),
    [preview, setPreview] = useState<DocumentView | null>(null);
  const active = useRef(false),
    working = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  async function open(download: boolean) {
    if (!active.current || working.current || !report.result) return;
    const result = report.result;
    working.current = true;
    setBusy(true);
    setError(null);
    try {
      const { data: document } = await api<DocumentView>(
        `/documents/${result.document_version_id}`,
      );
      if (
        document.id !== result.document_version_id ||
        document.bid_id !== report.scope.bid_id ||
        document.artifact_kind !== "review_report" ||
        document.media_type !== result.media_type ||
        document.sha256 !== result.blob_digest ||
        document.byte_size !== result.byte_size
      )
        throw new Error(
          "报告文件的用途、原运行产物摘要或格式不符，未取回其他文件。",
        );
      if (!active.current) return;
      if (!download) {
        if (report.format !== "pdf")
          throw new Error("此副本不是 PDF，不能作为原页预览。");
        setPreview(document);
        return;
      }
      const { data: grant } = await api<DownloadGrant>(
        `/artifacts/${result.document_version_id}/download`,
      );
      if (
        grant.artifact_id !== result.document_version_id ||
        grant.artifact_kind !== "review_report"
      )
        throw new Error("下载授权与这份报告不符，未取回其他产物。");
      if (!active.current) return;
      const response = await objectFetch(grant.download_url);
      if (!response.ok)
        throw new Error(`报告取件失败（${response.status}），请重新取件。`);
      const bytes = await response.arrayBuffer(),
        digest = Array.from(
          new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
          (byte) => byte.toString(16).padStart(2, "0"),
        ).join("");
      if (
        bytes.byteLength !== result.byte_size ||
        digest !== result.blob_digest
      )
        throw new Error(
          "实际报告字节与已发布摘要不符，未下载该副本，请重新核对。",
        );
      if (!active.current) return;
      const url = URL.createObjectURL(
          new Blob([bytes], { type: result.media_type }),
        ),
        link = window.document.createElement("a");
      link.href = url;
      link.download = result.filename;
      window.document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      working.current = false;
      if (active.current) setBusy(false);
    }
  }
  if (!report.result) return null;
  return (
    <div className="artifact-actions">
      <p>
        {report.result.filename} · {sizeLabel(report.result.byte_size)}
      </p>
      <div className="package-review__actions">
        <button
          type="button"
          className="button primary"
          disabled={busy}
          onClick={() => void open(true)}
        >
          {busy
            ? "正在核对报告文件…"
            : `下载本份 ${report.format === "docx" ? "Word" : "PDF"} 报告`}
        </button>
        {report.format === "pdf" && (
          <button
            type="button"
            className="button secondary"
            disabled={busy}
            onClick={() => void open(false)}
          >
            查看本份报告 PDF 原页
          </button>
        )}
      </div>
      {error != null && <ErrorNotice error={error} />}
      {preview && (
        <Evidence
          document={preview}
          onClose={() => setPreview(null)}
          contextNotice="本副本固定原核查和申请时的人工意见；生成成功不表示风险已解决或具备投递资格。"
        />
      )}
    </div>
  );
}
