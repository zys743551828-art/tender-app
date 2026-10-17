import { useState } from "react";
import { api, objectFetch } from "./api";
import type { DocumentView, DownloadGrant } from "./contracts";
import { ErrorNotice } from "./components";
import { Evidence } from "./Evidence";

/** Read and bind metadata before offering any output as a downloadable artifact. */
export function ArtifactActions({
  bidId,
  documentId,
  isPdf,
  downloadLabel = "下载生成文件",
  suggestedFilename,
}: {
  bidId: string;
  documentId: string;
  isPdf: boolean;
  downloadLabel?: string;
  suggestedFilename?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [preview, setPreview] = useState<DocumentView | null>(null);
  async function open(download: boolean) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const { data: document } = await api<DocumentView>(
        `/documents/${documentId}`,
      );
      if (document.id !== documentId || document.bid_id !== bidId)
        throw new Error("生成文件身份无法核对，未打开其他项目原件。");
      if (!download) {
        if (document.media_type !== "application/pdf")
          throw new Error("此输出不是PDF，不能作为原页预览。");
        setPreview(document);
        return;
      }
      const { data: grant } = await api<DownloadGrant>(
        `/artifacts/${documentId}/download`,
      );
      if (grant.artifact_id !== documentId)
        throw new Error("取件授权与生成文件身份不一致，请重试。");
      const response = await objectFetch(grant.download_url);
      if (!response.ok)
        throw new Error(`生成文件取回失败（${response.status}），请重试取件。`);
      const url = URL.createObjectURL(await response.blob());
      const link = window.document.createElement("a");
      link.href = url;
      link.download = suggestedFilename ?? grant.filename;
      window.document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="artifact-actions">
      <div className="review-shortcuts">
        <button
          className="button secondary"
          disabled={busy}
          onClick={() => void open(true)}
        >
          {busy ? "正在取回文件…" : downloadLabel}
        </button>
        {isPdf && (
          <button
            className="text-button"
            disabled={busy}
            onClick={() => void open(false)}
          >
            查看此版PDF原页
          </button>
        )}
      </div>
      <ErrorNotice error={error} />
      {preview && (
        <Evidence
          document={preview}
          onClose={() => setPreview(null)}
          contextNotice="这是本次固定快照生成的文件。生成成功不表示已经评审或解决风险。"
        />
      )}
    </div>
  );
}
