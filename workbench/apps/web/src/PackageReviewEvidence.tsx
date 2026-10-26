import { useCallback, useEffect, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import type { DocumentView, EvidenceView } from "./contracts";
import { ErrorNotice } from "./components";
import { Evidence } from "./Evidence";
import type {
  PackageReviewDocument,
  PackageReviewQuote,
} from "./packageReviewProtocol";

export default function PackageReviewEvidence({
  bidId,
  document: expected,
  quote,
}: {
  bidId: string;
  document: Pick<
    PackageReviewDocument,
    "document_version_id" | "parse_run_id" | "file_digest"
  > &
    Partial<PackageReviewDocument>;
  quote: Pick<
    PackageReviewQuote,
    "evidence_id" | "document_version_id" | "physical_page" | "quote"
  > &
    Partial<PackageReviewQuote>;
}) {
  const active = useRef(false),
    loading = useRef(false);
  const sourceTrigger = useRef<HTMLElement | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  const [source, setSource] = useState<{
    document: DocumentView;
    notice?: string;
  } | null>(null);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const close = useCallback(() => setSource(null), []);
  const available =
    supportsApi("GET", `/evidence/${quote.evidence_id}`) &&
    supportsApi("GET", `/documents/${quote.document_version_id}`);
  async function open() {
    if (!active.current || loading.current || !available) return;
    sourceTrigger.current = document.activeElement as HTMLElement | null;
    loading.current = true;
    setBusy(true);
    setError(null);
    try {
      const { data: evidence } = await api<EvidenceView>(
        `/evidence/${quote.evidence_id}`,
      );
      if (
        evidence?.id !== quote.evidence_id ||
        evidence.document_version_id !== expected.document_version_id ||
        evidence.parse_run_id !== expected.parse_run_id ||
        evidence.physical_page !== quote.physical_page ||
        typeof evidence.quote !== "string" ||
        !evidence.quote.includes(quote.quote)
      )
        throw new Error(
          "引用的解析版本、物理页或逐字内容与本次结果不符，未打开其他原页。",
        );
      if (!active.current) return;
      const { data: document } = await api<DocumentView>(
        `/documents/${quote.document_version_id}`,
      );
      if (
        document?.id !== expected.document_version_id ||
        document.bid_id !== bidId ||
        document.sha256 !== expected.file_digest
      )
        throw new Error("原件的项目、文件版本或字节摘要不符，未打开其他文件。");
      if (!active.current) return;
      const notice =
        evidence.source_status === "withdrawn"
          ? "此引用来源当前已撤回。本页用于核对本次历史结果，不恢复来源资格，也不将旧结论视为当前有效。"
          : evidence.source_status === "candidate"
            ? "此引用当前为候选来源。本页仅用于核对历史原文，当前可用性须重新核验。"
            : document.file_head_version_id !== document.id
              ? "正在查看本次核查保留的原文件版本。文件已有其他版本，新版需要重新核查。"
              : "正在查看本次核查绑定的原件与物理页。引用与结论仍待人工复核。";
      setSource({ document, notice });
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      loading.current = false;
      if (active.current) setBusy(false);
    }
  }
  return (
    <div className="package-review__evidence-link">
      <button
        type="button"
        className="text-button"
        disabled={busy || !available}
        onClick={() => void open()}
      >
        {busy
          ? "正在核对原页身份…"
          : `查看引用原页 · 物理页 ${quote.physical_page}`}
      </button>
      {!available && <small>当前服务尚未提供此引用的原页读取。</small>}
      {error != null && (
        <ErrorNotice error={error} onRetry={() => void open()} />
      )}
      {source && (
        <Evidence
          document={source.document}
          returnFocus={sourceTrigger}
          initialPage={quote.physical_page}
          contextNotice={source.notice}
          onClose={close}
        />
      )}
    </div>
  );
}
