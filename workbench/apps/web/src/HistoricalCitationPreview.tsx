import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type RefObject,
} from "react";
import { api, roleNames } from "./api";
import { ErrorNotice, Loading } from "./components";
import type { DocumentView, DownloadGrant, EvidenceView } from "./contracts";
import { executionSha } from "./executionInputValidation";
import { PdfPreview } from "./PdfPreview";
import { SourceSurface } from "./SourceSurface";

const ignorePageCount = () => undefined;

/** Historical opening uses the citation already anchored to its exact parse/physical page.
 * It never mounts the project evidence editor or requests a document's latest parse. */
export function HistoricalCitationPreview({
  document,
  citation,
  onClose,
  returnFocus,
}: {
  document: DocumentView;
  citation: EvidenceView;
  onClose: () => void;
  returnFocus: RefObject<HTMLButtonElement | null>;
}) {
  const heading = useId();
  const closeButton = useRef<HTMLButtonElement>(null);
  const [grant, setGrant] = useState<DownloadGrant | null>(null);
  const [failure, setFailure] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  const isPdf =
    document.media_type === "application/pdf" ||
    document.filename.toLowerCase().endsWith(".pdf");
  const authorized =
    citation.document_version_id === document.id &&
    Number.isSafeInteger(citation.physical_page) &&
    citation.physical_page >= 1 &&
    executionSha(document.sha256);

  useEffect(() => {
    if (!isPdf || !authorized) return;
    let active = true;
    void api<DownloadGrant>(`/artifacts/${document.id}/download`)
      .then(({ data }) => {
        if (!active) return;
        if (data.artifact_id !== document.id)
          throw new Error(
            "原件访问地址与本次固定文件版本不一致，未打开其他文件。",
          );
        setGrant(data);
      })
      .catch((error: unknown) => {
        if (active) setFailure(error);
      });
    return () => {
      active = false;
    };
  }, [attempt, authorized, document.id, isPdf]);

  const refresh = useCallback(() => {
    setGrant(null);
    setFailure(null);
    setAttempt((current) => current + 1);
  }, []);

  return (
    <SourceSurface
      bidId={document.bid_id}
      className="evidence-dialog"
      labelledBy={heading}
      initialFocus={closeButton}
      returnFocus={returnFocus}
      onClose={onClose}
    >
      {() => (
        <>
          <header className="evidence-heading">
            <div>
              <span className="eyebrow">历史引用 · 只读</span>
              <h2 id={heading}>{document.filename}</h2>
              <p>
                {roleNames[document.role]} · 文件版本 {document.file_revision}
              </p>
            </div>
            <button
              type="button"
              ref={closeButton}
              className="button secondary"
              onClick={onClose}
            >
              关闭原件
            </button>
          </header>
          {!authorized ? (
            <p role="alert">原件身份或物理页不完整，未替换为其他版本。</p>
          ) : (
            <>
              <p className="small-note">
                这里只显示本次候选绑定的原摘录与物理页。不读取最新版解析、不修改资料页范围，也不重新判定来源效力。
              </p>
              <article className="evidence-quote">
                <h3>当时解析的引用摘录</h3>
                <small>
                  物理页 {citation.physical_page}
                  {citation.printed_label
                    ? ` · 印刷页码 ${citation.printed_label}`
                    : ""}
                  {citation.source_status === "withdrawn"
                    ? " · 来源已撤回"
                    : ""}
                </small>
                <p className="identity-ref">固定解析 {citation.parse_run_id}</p>
                <p>{citation.quote}</p>
              </article>
              <section className="original-view" aria-label="固定物理页预览">
                {!isPdf && (
                  <p>此格式不能直接预览原物理页；上方保留本次引用的原摘录。</p>
                )}
                {isPdf && !!failure && (
                  <ErrorNotice error={failure} onRetry={refresh} />
                )}
                {isPdf && !grant && !failure && (
                  <Loading text="正在取得固定版本的原件…" />
                )}
                {isPdf && grant && (
                  <PdfPreview
                    url={grant.download_url}
                    filename={document.filename}
                    page={citation.physical_page}
                    expectedSha256={document.sha256}
                    byteSize={document.byte_size}
                    onPageCount={ignorePageCount}
                    onRefresh={refresh}
                  />
                )}
              </section>
            </>
          )}
        </>
      )}
    </SourceSurface>
  );
}
