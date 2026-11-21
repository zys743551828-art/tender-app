import { DocumentRelationNotice } from "./DocumentRelationNotice";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";
import type {
  DocumentView,
  DownloadGrant,
  DocumentEvidenceView,
} from "./contracts";
import { PdfPreview } from "./PdfPreview";
import { SourceSurface } from "./SourceSurface";
import { api, objectFetch, parseNames, roleNames, sha256Hex } from "./api";
import { Badge, ErrorNotice, Icon, Loading } from "./components";
import { contentClues } from "./contentClues";
import { EvidenceSearch } from "./EvidenceSearch";
import { PartialPageSelection } from "./PartialPageSelection";

export function Evidence({
  document,
  onClose,
  initialPage = 1,
  contextNotice,
  returnFocus,
}: {
  document: DocumentView;
  onClose: () => void;
  initialPage?: number;
  contextNotice?: string;
  returnFocus?: RefObject<HTMLElement | null>;
}) {
  const [evidenceRecord, setEvidence] = useState<DocumentEvidenceView | null>(
    null,
  );
  const [grantRecord, setGrant] = useState<
    (DownloadGrant & { attempt: number }) | null
  >(null);
  const evidence =
    evidenceRecord?.document_version_id === document.id ? evidenceRecord : null;
  const hasDigest =
    typeof document.sha256 === "string" &&
    /^[0-9a-f]{64}$/.test(document.sha256);
  const grant =
    hasDigest && grantRecord?.artifact_id === document.id ? grantRecord : null;
  const [error, setError] = useState<unknown>(null);
  const [page, setPage] = useState(initialPage);
  const [pageCount, setPageCount] = useState(0);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<unknown>(null);
  const [view, setView] = useState<"original" | "text">("original");
  const toolGroup = useId();
  const searchTool = useRef<HTMLDetailsElement>(null);
  const cluesTool = useRef<HTMLDetailsElement>(null);
  const textSwitch = useRef<HTMLButtonElement>(null);
  const clues = useMemo(() => contentClues(evidence?.items ?? []), [evidence]);
  function showTextAt(number: number, tool: HTMLDetailsElement | null) {
    setPage(number);
    setView("text");
    if (textSwitch.current && tool) {
      tool.open = false;
      textSwitch.current.focus();
    }
  }
  const closeButton = useRef<HTMLButtonElement>(null);
  const request = useRef(0);
  const downloadActive = useRef(false);
  const downloadController = useRef<AbortController | null>(null);
  const invalidate = useCallback(() => {
    request.current++;
    downloadController.current?.abort();
    downloadController.current = null;
    downloadActive.current = false;
  }, []);
  const close = useCallback(() => {
    invalidate();
    onClose();
  }, [invalidate, onClose]);
  const load = useCallback(async () => {
    const current = ++request.current;
    setError(null);
    const results = await Promise.allSettled([
      api<DocumentEvidenceView>(`/documents/${document.id}/evidence`),
      hasDigest
        ? api<DownloadGrant>(`/artifacts/${document.id}/download`)
        : null,
    ]);
    if (request.current !== current) return;
    if (results[0].status === "fulfilled") {
      const value = results[0].value.data;
      if (
        value.document_version_id === document.id &&
        value.items.every((item) => item.document_version_id === document.id)
      )
        setEvidence(value);
      else
        setError(new Error("解析依据的原件身份不一致，未展示其他文件内容。"));
    } else setError(results[0].reason);
    if (results[1].status === "fulfilled") {
      if (!results[1].value) return;
      const value = results[1].value.data;
      if (value.artifact_id === document.id)
        setGrant({ ...value, attempt: current });
      else
        setError(new Error("原件访问地址的文件身份不一致，未打开其他文件。"));
    } else setError(results[1].reason);
  }, [document.id, hasDigest]);
  async function downloadOriginal() {
    if (!downloadActive.current || downloadController.current) return;
    const controller = new AbortController();
    downloadController.current = controller;
    setDownloading(true);
    setDownloadError(null);
    try {
      const { data } = await api<DownloadGrant>(
        `/artifacts/${document.id}/download`,
      );
      if (controller.signal.aborted) return;
      if (data.artifact_id !== document.id)
        throw new Error("原件下载身份不一致，未下载其他文件。");
      const response = await objectFetch(data.download_url, {
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      if (!response.ok)
        throw new Error(
          `原件取回失败（${response.status}）。已保存的原件仍保留，请重试取件。`,
        );
      const bytes = await response.arrayBuffer();
      if (controller.signal.aborted) return;
      if (
        bytes.byteLength !== document.byte_size ||
        (await sha256Hex(bytes)) !== document.sha256
      )
        throw new Error(
          "取回字节与本版本的原件摘要或大小不一致，未保存文件。请重试取件。",
        );
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(
        new Blob([bytes], { type: document.media_type }),
      );
      const link = window.document.createElement("a");
      link.href = url;
      link.download = document.filename;
      link.style.display = "none";
      try {
        window.document.body.appendChild(link);
        link.click();
      } finally {
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    } catch (failure) {
      if (!controller.signal.aborted) setDownloadError(failure);
    } finally {
      if (!controller.signal.aborted) {
        downloadController.current = null;
        setDownloading(false);
      }
    }
  }
  useEffect(() => {
    downloadActive.current = true;
    setDownloading(false);
    setDownloadError(null);
    setPage(initialPage);
    setPageCount(0);
    setView("original");
    void load().catch(setError);
    return invalidate;
  }, [load, initialPage, invalidate, document.bid_id]);
  useEffect(() => {
    if (evidence?.coverage !== "pending") return;
    let active = true;
    const timer = window.setInterval(() => {
      const current = request.current;
      void api<DocumentEvidenceView>(`/documents/${document.id}/evidence`)
        .then(({ data }) => {
          if (!active || current !== request.current) return;
          if (
            data.document_version_id === document.id &&
            data.items.every((item) => item.document_version_id === document.id)
          )
            setEvidence(data);
          else
            setError(
              new Error("解析依据的原件身份不一致，未展示其他文件内容。"),
            );
        })
        .catch((failure: unknown) => {
          if (active && current === request.current) setError(failure);
        });
    }, 2000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [document.id, evidence?.coverage]);
  const pages = pageCount
    ? Array.from({ length: pageCount }, (_, index) => index + 1)
    : Array.from(
        new Set(evidence?.items.map((item) => item.physical_page) ?? []),
      );
  const isPdf =
    document.media_type === "application/pdf" ||
    document.filename.toLowerCase().endsWith(".pdf");
  const gaps = evidence?.gaps.map((gap, index) => <li key={index}>{gap}</li>);
  return (
    <SourceSurface
      bidId={document.bid_id}
      className="evidence-dialog"
      labelledBy="evidence-title"
      initialFocus={closeButton}
      returnFocus={returnFocus}
      onClose={close}
    >
      {(singlePane) => (
        <>
          <header className="evidence-heading">
            <div>
              <span className="eyebrow">原件与解析依据</span>
              <h2 id="evidence-title">{document.filename}</h2>
              <p>
                {roleNames[document.role]} · 版本 {document.file_revision} ·{" "}
                {document.id === document.file_head_version_id
                  ? "当前版本"
                  : "历史版本"}
              </p>
            </div>
            <button
              type="button"
              ref={closeButton}
              className="button secondary"
              onClick={close}
            >
              关闭原件
            </button>
          </header>
          <DocumentRelationNotice document={document} />
          {contextNotice && (
            <div className="notice warning evidence-gaps">
              <p>{contextNotice}</p>
            </div>
          )}
          <div className="evidence-toolbar">
            <Badge
              tone={evidence?.coverage === "complete" ? "success" : "warning"}
            >
              {parseNames[evidence?.coverage ?? document.parse_coverage]}
            </Badge>
            {pages.length > 0 && (
              <label className="page-select">
                物理页
                <select
                  value={page}
                  onChange={(event) => setPage(Number(event.target.value))}
                >
                  {pages.map((value) => (
                    <option value={value} key={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {singlePane && (
              <div
                className="source-view-switch"
                role="group"
                aria-label="查看原页或解析文本"
              >
                <button
                  type="button"
                  aria-pressed={view === "original"}
                  onClick={() => setView("original")}
                >
                  原页
                </button>
                <button
                  type="button"
                  ref={textSwitch}
                  aria-pressed={view === "text"}
                  onClick={() => setView("text")}
                >
                  解析文本
                </button>
              </div>
            )}
            {grant && (
              <button
                type="button"
                className="text-button"
                disabled={downloading}
                onClick={() => void downloadOriginal()}
              >
                {downloading ? "正在取回原件…" : "下载资料原件"}
                <Icon name="arrow" />
              </button>
            )}
          </div>
          {evidence && evidence.coverage !== "pending" && (
            <div
              className={
                singlePane
                  ? "evidence-reading-tools evidence-reading-tools--compact"
                  : "evidence-reading-tools"
              }
            >
              <details
                className="evidence-tool"
                key={`search:${document.id}:${evidence.parse_run_id}`}
                ref={searchTool}
                open={!singlePane}
                name={singlePane ? toolGroup : undefined}
              >
                <summary>查找解析文本</summary>
                <EvidenceSearch
                  items={evidence.items}
                  onPage={(number) => showTextAt(number, searchTool.current)}
                />
              </details>
              <details
                className="evidence-tool"
                key={`clues:${document.id}:${evidence.parse_run_id}`}
                ref={cluesTool}
                open={!singlePane}
                name={singlePane ? toolGroup : undefined}
              >
                <summary>内容线索</summary>
                <div className="notice evidence-gaps">
                  <div>
                    <strong>内容线索（请核对原文）</strong>
                    <p>
                      以下来自已解析文字或
                      OCR，仅用于定位，可能遗漏或误识别；不会自动分类、拆分文件或改变资料用途。
                    </p>
                    {clues.length ? (
                      <ul>
                        {clues.map((clue) => (
                          <li key={clue.label}>
                            {clue.label}：
                            <details>
                              <summary>
                                查看 {clue.pages.length} 个可能相关页
                              </summary>
                              {clue.pages.map((number) => (
                                <button
                                  key={number}
                                  type="button"
                                  className="text-button"
                                  onClick={() =>
                                    showTextAt(number, cluesTool.current)
                                  }
                                >
                                  第 {number} 页
                                </button>
                              ))}
                            </details>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p>未找到上述关键词；不能据此判断文件不包含相关内容。</p>
                    )}
                  </div>
                </div>
              </details>
              {document.role !== "official_result" &&
                ["source_original", "bid_body"].includes(
                  document.artifact_kind,
                ) &&
                ["partial", "complete"].includes(evidence.coverage) && (
                  <PartialPageSelection
                    key={`${document.id}:${evidence.parse_run_id}`}
                    document={document}
                    evidence={evidence}
                    page={page}
                    pageCount={pageCount}
                    onPage={(number) => {
                      setPage(number);
                      setView("original");
                    }}
                  />
                )}
            </div>
          )}
          <div className="evidence-error">
            <ErrorNotice
              error={error}
              onRetry={() => void load().catch(setError)}
            />
            <ErrorNotice
              error={downloadError}
              onRetry={() => void downloadOriginal()}
            />
          </div>
          {evidence?.gaps.length ? (
            <div className="notice warning evidence-gaps evidence-gap-list">
              <div>
                {singlePane && evidence.gaps.length > 1 ? (
                  <details key={`gaps:${document.id}:${evidence.parse_run_id}`}>
                    <summary>
                      <strong>以下范围尚未完整核对</strong> · 查看全部{" "}
                      {evidence.gaps.length} 项解析缺口
                    </summary>
                    <ul tabIndex={0} aria-label="全部解析缺口">
                      {gaps}
                    </ul>
                  </details>
                ) : (
                  <>
                    <strong>以下范围尚未完整核对</strong>
                    <ul>{gaps}</ul>
                  </>
                )}
              </div>
            </div>
          ) : null}
          {!isPdf && (
            <div className="notice warning evidence-gaps">
              <div>
                <strong>Word原件已保存，本次未完成对应检查</strong>
                <p>
                  当前切片尚未提供Word转换。可返回资料页，将此修改稿的PDF作为独立文件上传。所选PDF有独立版本，不自动取得Word对应检查资格。
                </p>
              </div>
            </div>
          )}
          <div
            className={`evidence-body${singlePane ? " evidence-body--single" : ""}`}
          >
            <section
              className="original-view"
              aria-label="原文件预览"
              hidden={singlePane && view !== "original"}
            >
              {isPdf && grant ? (
                <>
                  <PdfPreview
                    key={grant.attempt}
                    url={grant.download_url}
                    expectedSha256={document.sha256}
                    byteSize={document.byte_size}
                    filename={document.filename}
                    page={page}
                    onPageCount={setPageCount}
                    onRefresh={() => void load().catch(setError)}
                  />
                  <p className="preview-hint">
                    所选物理页 {page}。扫描页和空白页均按原件页序显示。
                  </p>
                </>
              ) : (
                <div className="empty-state">
                  <Icon name="file" />
                  <p>
                    {!hasDigest
                      ? "该版本缺少有效的原件 SHA-256 摘要，无法核验文件。请重新打开资料或联系管理员核对记录。"
                      : grant
                        ? "此格式暂不支持页内预览，可下载原件。"
                        : "正在取得私有原件访问地址…"}
                  </p>
                </div>
              )}
            </section>
            <section
              className="extracted-view"
              aria-label="解析文本依据"
              hidden={singlePane && view !== "text"}
            >
              <div className="section-heading">
                <h3>解析文本</h3>
              </div>
              <p className="muted">
                逐页对照原件。文本解析完成不等于规则完整提取或评审通过。
              </p>
              {!evidence && !error && <Loading />}
              {evidence && evidence.items.length === 0 && (
                <p className="small-empty">
                  当前没有可展示的文本依据。请查看解析范围与原件。
                </p>
              )}
              {evidence &&
                evidence.items.length > 0 &&
                !evidence.items.some((item) => item.physical_page === page) && (
                  <p className="small-empty">
                    此物理页未提取到文本，请查看原页及解析缺口。
                  </p>
                )}
              {evidence?.items
                .filter((item) => item.physical_page === page)
                .map((item) => (
                  <article className="evidence-quote" key={item.id}>
                    <small>
                      物理页 {item.physical_page}
                      {item.printed_label
                        ? ` · 印刷页码 ${item.printed_label}`
                        : ""}
                      {item.source_status === "withdrawn"
                        ? " · 来源已撤回"
                        : ""}
                    </small>
                    <p>{item.quote}</p>
                  </article>
                ))}
              <details className="identity-details">
                <summary>文件身份</summary>
                <dl>
                  <dt>版本ID</dt>
                  <dd>{document.id}</dd>
                  <dt>SHA-256</dt>
                  <dd>{document.sha256}</dd>
                  <dt>原件取得时间</dt>
                  <dd>
                    {new Date(document.obtained_at).toLocaleString("zh-CN")}
                  </dd>
                </dl>
              </details>
            </section>
          </div>
        </>
      )}
    </SourceSurface>
  );
}
