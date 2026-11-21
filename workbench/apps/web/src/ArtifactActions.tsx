import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { DocumentView } from "./contracts";
import { downloadDocument } from "./downloadDocument";
import { ErrorNotice } from "./components";
import { Evidence } from "./Evidence";

type Props = {
  bidId: string;
  documentId: string;
  isPdf: boolean;
  downloadLabel?: string;
  suggestedFilename?: string;
  expectedArtifactKind?: DocumentView["artifact_kind"];
  expectedMediaType?: string;
  previewNotice?: string;
};

/** A changed output or qualification must not retain another file's preview/request. */
export function ArtifactActions(props: Props) {
  return (
    <ScopedArtifactActions
      key={JSON.stringify([
        props.bidId,
        props.documentId,
        props.isPdf,
        props.expectedArtifactKind,
        props.expectedMediaType,
        props.suggestedFilename,
        props.previewNotice,
      ])}
      {...props}
    />
  );
}

/** Read and bind metadata before offering any output as a downloadable artifact. */
function ScopedArtifactActions({
  bidId,
  documentId,
  isPdf,
  downloadLabel = "下载此版本文件",
  suggestedFilename,
  expectedArtifactKind,
  expectedMediaType,
  previewNotice,
}: Props) {
  const [busy, setBusy] = useState<"download" | "preview" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [preview, setPreview] = useState<DocumentView | null>(null);
  const previewTrigger = useRef<HTMLElement | null>(null);
  const request = useRef<AbortController | null>(null);
  useEffect(() => {
    return () => request.current?.abort();
  }, []);
  function cancelDownload() {
    request.current?.abort();
    request.current = null;
    setBusy(null);
  }
  async function open(download: boolean) {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    const { signal } = controller;
    if (!download)
      previewTrigger.current = document.activeElement as HTMLElement | null;
    setBusy(download ? "download" : "preview");
    setError(null);
    try {
      const { data: document } = await api<DocumentView>(
        `/documents/${documentId}`,
        { signal },
      );
      signal.throwIfAborted();
      if (document.id !== documentId || document.bid_id !== bidId)
        throw new Error("文件版本与当前项目或记录不一致，请刷新核对。");
      if (
        (expectedArtifactKind &&
          document.artifact_kind !== expectedArtifactKind) ||
        (expectedMediaType && document.media_type !== expectedMediaType)
      )
        throw new Error(
          "文件用途或格式与此取件入口不一致，请刷新核对。",
        );
      if (!download) {
        if (document.media_type !== "application/pdf")
          throw new Error("该文件格式不支持 PDF 原页预览。");
        setPreview(document);
        return;
      }
      await downloadDocument(document, signal, suggestedFilename);
    } catch (failure) {
      if (!signal.aborted) setError(failure);
    } finally {
      if (request.current === controller && !signal.aborted) {
        request.current = null;
        setBusy(null);
      }
    }
  }
  return (
    <div className="artifact-actions">
      <div className="review-shortcuts">
        <button
          type="button"
          className="button secondary"
          disabled={!!busy}
          onClick={() => void open(true)}
        >
          {busy === "download" ? "正在取回并核验文件…" : downloadLabel}
        </button>
        {busy === "download" && (
          <button
            type="button"
            className="text-button"
            onClick={cancelDownload}
          >
            取消下载
          </button>
        )}
        {isPdf && (
          <button
            type="button"
            className="text-button"
            disabled={!!busy}
            onClick={() => void open(false)}
          >
            {busy === "preview" ? "正在打开预览…" : "查看此版PDF原页"}
          </button>
        )}
      </div>
      <ErrorNotice error={error} />
      {preview && (
        <Evidence
          document={preview}
          returnFocus={previewTrigger}
          onClose={() => setPreview(null)}
          contextNotice={
            previewNotice ?? "当前预览的是这条记录引用的文件版本。"
          }
        />
      )}
    </div>
  );
}
