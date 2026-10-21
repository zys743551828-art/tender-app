import { useEffect, useRef, useState } from "react";
import { api, objectFetch } from "./api";
import type {
  DocumentParseView,
  DocumentView,
  DownloadGrant,
} from "./contracts";
import { ErrorNotice } from "./components";
import { PdfPreview } from "./PdfPreview";

/** Raw original only: /documents/:id/evidence returns the latest parse, not this historical parse. */
export default function DocumentParseOriginal({
  view,
}: {
  view: DocumentParseView;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null),
    [url, setUrl] = useState(""),
    [page, setPage] = useState(1),
    [pageCount, setPageCount] = useState(0);
  const active = useRef(false),
    working = useRef(false),
    objectUrl = useRef("");
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    };
  }, []);
  function close() {
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    objectUrl.current = "";
    setUrl("");
    setPageCount(0);
    setPage(1);
  }
  async function open() {
    if (!active.current || working.current) return;
    working.current = true;
    setBusy(true);
    setError(null);
    try {
      const expected = view.context.document,
        { data: document } = await api<DocumentView>(
          `/documents/${view.document_version_id}`,
        );
      if (
        !document ||
        document.id !== view.document_version_id ||
        document.bid_id !== view.bid_id ||
        document.sha256 !== expected.sha256 ||
        document.byte_size !== expected.byte_size ||
        document.media_type !== "application/pdf" ||
        document.artifact_kind !== expected.artifact_kind ||
        document.file_id !== expected.file_id ||
        document.file_revision !== expected.file_revision ||
        document.role !== expected.role
      )
        throw new Error(
          "原件的项目、版本或字节摘要与这次解析不符，未打开其他文件。",
        );
      if (!active.current) return;
      const { data: grant } = await api<DownloadGrant>(
        `/artifacts/${view.document_version_id}/download`,
      );
      if (
        !grant ||
        grant.artifact_id !== view.document_version_id ||
        grant.artifact_kind !== expected.artifact_kind ||
        typeof grant.download_url !== "string"
      )
        throw new Error("原件访问授权与这次解析不符，未打开其他文件。");
      if (!active.current) return;
      const response = await objectFetch(grant.download_url);
      if (!response.ok)
        throw new Error(`原件取回失败（${response.status}），请重试。`);
      const bytes = await response.arrayBuffer(),
        digest = Array.from(
          new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
          (byte) => byte.toString(16).padStart(2, "0"),
        ).join("");
      if (bytes.byteLength !== expected.byte_size || digest !== expected.sha256)
        throw new Error(
          "取回的 PDF 字节与本次解析绑定的原件摘要不符，未展示该文件。",
        );
      if (!active.current) return;
      close();
      objectUrl.current = URL.createObjectURL(
        new Blob([bytes], { type: "application/pdf" }),
      );
      setUrl(objectUrl.current);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      working.current = false;
      if (active.current) setBusy(false);
    }
  }
  return (
    <div className="document-parse__original">
      <button
        type="button"
        className="button secondary"
        disabled={busy}
        onClick={() => void open()}
      >
        {busy ? "正在核对原件…" : "查看本次解析绑定的 PDF 原页"}
      </button>
      {error !== null && <ErrorNotice error={error} />}
      {url && (
        <section aria-label="解析绑定的 PDF 原页">
          <p>
            正在查看这次解析绑定的原文件物理页。历史解析的覆盖范围以上方记录为准。
          </p>
          <div className="document-parse__actions">
            <button type="button" className="button secondary" onClick={close}>
              关闭原页
            </button>
            <button
              type="button"
              className="button secondary"
              disabled={page <= 1}
              onClick={() => setPage((value) => value - 1)}
            >
              上一物理页
            </button>
            <label>
              物理页{" "}
              <input
                type="number"
                min={1}
                max={pageCount || 1}
                value={page}
                onChange={(event) => {
                  const number = Number(event.target.value);
                  if (
                    Number.isInteger(number) &&
                    number >= 1 &&
                    number <= pageCount
                  )
                    setPage(number);
                }}
              />
            </label>
            <span>/ {pageCount || "…"}</span>
            <button
              type="button"
              className="button secondary"
              disabled={!pageCount || page >= pageCount}
              onClick={() => setPage((value) => value + 1)}
            >
              下一物理页
            </button>
          </div>
          <PdfPreview
            url={url}
            filename={view.context.document.filename}
            page={page}
            onPageCount={setPageCount}
            onRefresh={() => void open()}
          />
        </section>
      )}
    </div>
  );
}
