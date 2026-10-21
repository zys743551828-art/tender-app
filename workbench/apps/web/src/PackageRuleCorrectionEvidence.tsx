import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { api, supportsApi } from "./api";
import type {
  DocumentView,
  PackageRuleCorrectionEvidenceDetail,
  PackageRuleCorrectionPreviewView,
  RuleEvidenceQuote,
} from "./contracts";
import { ErrorNotice } from "./components";
import {
  correctionProtocolFailure,
  sameCorrectionValue,
  validateCorrectionEvidenceDetail,
  validateCorrectionEvidencePage,
  type CorrectionEvidenceEntry,
} from "./packageRuleCorrectionProtocol";
import {
  correctionEvidencePath,
  correctionText,
  type CorrectionBase,
  type CorrectionScope,
} from "./packageRuleCorrectionRecovery";

const Evidence = lazy(async () => ({
  default: (await import("./Evidence")).Evidence,
}));
export type CorrectionQuoteChoice = {
  detail: PackageRuleCorrectionEvidenceDetail;
  quote: string;
};
type FrozenQuote =
  PackageRuleCorrectionPreviewView["manifest"]["changes"][number]["quotes"][number];

function SourcePage({
  scope,
  detail,
  quote,
}: {
  scope: CorrectionScope;
  detail: PackageRuleCorrectionEvidenceDetail;
  quote?: string;
}) {
  const active = useRef(false),
    running = useRef(false);
  const [document, setDocument] = useState<DocumentView | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const close = useCallback(() => setDocument(null), []);
  const item = detail.evidence;
  async function open() {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    try {
      const { data } = await api<DocumentView>(
        `/documents/${item.document_version_id}`,
      );
      if (
        data.id !== item.document_version_id ||
        data.bid_id !== scope.bidId ||
        data.sha256 !== item.file_digest ||
        (quote && !item.text_content.includes(quote))
      )
        correctionProtocolFailure();
      if (active.current) setDocument(data);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  return (
    <div>
      <button
        type="button"
        className="text-button"
        disabled={
          busy || !supportsApi("GET", `/documents/${item.document_version_id}`)
        }
        onClick={() => void open()}
      >
        {busy ? "正在核对文件身份…" : `查看原件 · 物理页 ${item.physical_page}`}
      </button>
      {error != null && <ErrorNotice error={error} />}
      {document && (
        <Suspense fallback={<p role="status">正在打开冻结原件…</p>}>
          <Evidence
            document={document}
            initialPage={item.physical_page}
            contextNotice="正在核对该清单绑定的确切原件与物理页。人工修订保留原抽取范围和解析缺口，不代表整包完整。"
            onClose={close}
          />
        </Suspense>
      )}
    </div>
  );
}

export function PackageRuleCorrectionSource({
  scope,
  base,
  quote,
}: {
  scope: CorrectionScope;
  base: CorrectionBase;
  quote: FrozenQuote | RuleEvidenceQuote;
}) {
  const [detail, setDetail] =
    useState<PackageRuleCorrectionEvidenceDetail | null>(null);
  const [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false);
  const active = useRef(false),
    running = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  async function read() {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    try {
      const { data } = await api<PackageRuleCorrectionEvidenceDetail>(
        `${correctionEvidencePath(scope, base.inventoryId)}/${quote.evidence_id}`,
      );
      const item = data?.evidence;
      if (!item) correctionProtocolFailure();
      await validateCorrectionEvidenceDetail(data, scope, base, {
        ...item,
        excerpt: "",
      });
      if (
        item.evidence_id !== quote.evidence_id ||
        !item.text_content.includes(quote.quote) ||
        ("member_id" in quote &&
          (item.member_id !== quote.member_id ||
            item.document_version_id !== quote.document_version_id ||
            item.parse_run_id !== quote.parse_run_id ||
            item.physical_page !== quote.physical_page ||
            item.evidence_digest !== quote.evidence_digest ||
            !sameCorrectionValue(item.part_ids, quote.part_ids)))
      )
        correctionProtocolFailure();
      if (active.current) setDetail(data);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  return (
    <div className="rule-correction-source">
      {"member_id" in quote ? (
        <p className="small-note">
          成员 {quote.member_id} · 物理页 {quote.physical_page}
        </p>
      ) : (
        detail && (
          <p className="small-note">
            成员 {detail.evidence.member_id} · 物理页{" "}
            {detail.evidence.physical_page}
          </p>
        )
      )}
      <blockquote>{quote.quote}</blockquote>
      {detail ? (
        <SourcePage scope={scope} detail={detail} quote={quote.quote} />
      ) : (
        <button
          type="button"
          className="text-button"
          disabled={busy}
          onClick={() => void read()}
        >
          {busy ? "正在核对冻结证据…" : "核对引用与原页"}
        </button>
      )}
      {error != null && <ErrorNotice error={error} />}
    </div>
  );
}

function QuoteEditor({
  scope,
  detail,
  disabled,
  selected,
  onSelect,
}: {
  scope: CorrectionScope;
  detail: PackageRuleCorrectionEvidenceDetail;
  disabled: boolean;
  selected: CorrectionQuoteChoice[];
  onSelect: (value: CorrectionQuoteChoice) => void;
}) {
  const source = detail.evidence;
  const [quote, setQuote] = useState("");
  const valid =
    correctionText(quote, 8000) && source.text_content.includes(quote);
  const duplicate = selected.some(
    (item) =>
      item.detail.evidence.evidence_id === source.evidence_id &&
      item.quote === quote,
  );
  return (
    <section
      className="rule-correction-quote-editor"
      aria-label="冻结原页引用编辑"
    >
      <h6>
        成员 {source.member_id} · 物理页 {source.physical_page} ·{" "}
        {source.kind === "table"
          ? "表格文字"
          : source.kind === "visual_observation"
            ? "视觉观察"
            : "原页文字"}
      </h6>
      <p className="small-note">
        引用必须逐字来自下面的完整证据；条件、例外和分值也需包含在引用中。
      </p>
      <pre className="rule-correction-original">
        {source.text_content || "该证据没有可引用文字。"}
      </pre>
      <SourcePage scope={scope} detail={detail} />
      <label>
        逐字引用
        <textarea
          rows={4}
          maxLength={8000}
          value={quote}
          disabled={disabled}
          onChange={(event) => setQuote(event.target.value)}
        />
      </label>
      {quote && !valid && (
        <p role="alert">
          引用与这段冻结原文不完全一致，请保留原字、标点和换行。
        </p>
      )}
      {duplicate && <p role="status">此段逐字引用已加入当前条款。</p>}
      <div className="rule-correction-toolbar">
        <button
          type="button"
          className="text-button"
          disabled={
            disabled ||
            !source.text_content.trim() ||
            Array.from(source.text_content).length > 8000
          }
          onClick={() => setQuote(source.text_content)}
        >
          填入这段完整原文
        </button>
        <button
          type="button"
          disabled={disabled || !valid || duplicate || selected.length >= 50}
          onClick={() => {
            onSelect({ detail, quote });
            setQuote("");
          }}
        >
          采用这段逐字引用
        </button>
      </div>
    </section>
  );
}

export function PackageRuleCorrectionEvidence({
  scope,
  base,
  disabled,
  selected,
  onSelect,
}: {
  scope: CorrectionScope;
  base: CorrectionBase;
  disabled: boolean;
  selected: CorrectionQuoteChoice[];
  onSelect: (value: CorrectionQuoteChoice) => void;
}) {
  const path = correctionEvidencePath(scope, base.inventoryId);
  const [opened, setOpened] = useState(false);
  const [items, setItems] = useState<CorrectionEvidenceEntry[]>([]),
    [next, setNext] = useState<string | null>(null);
  const [detail, setDetail] =
    useState<PackageRuleCorrectionEvidenceDetail | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null),
    [loaded, setLoaded] = useState(false);
  const active = useRef(false),
    generation = useRef(0),
    running = useRef(false);
  const invalidate = useCallback(() => {
    generation.current++;
  }, []);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      invalidate();
    };
  }, [invalidate]);
  async function load(cursor: string | null = null) {
    if (running.current || disabled) return;
    running.current = true;
    const token = ++generation.current;
    setOpened(true);
    setBusy(true);
    setError(null);
    try {
      const { data } = await api<unknown>(
        `${path}?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
      );
      const page = validateCorrectionEvidencePage(data, scope, base);
      if (cursor && page.has_more && page.next_cursor === cursor)
        throw new Error("原页目录游标没有推进，请重读目录。");
      if (!active.current || token !== generation.current) return;
      const merged = new Map(
        (cursor ? items : []).map((item) => [item.evidence_id, item]),
      );
      for (const item of page.items) {
        const previous = merged.get(item.evidence_id);
        if (previous && !sameCorrectionValue(previous, item))
          correctionProtocolFailure();
        merged.set(item.evidence_id, item);
      }
      setItems([...merged.values()]);
      setNext(page.has_more ? page.next_cursor : null);
      setLoaded(true);
    } catch (failure) {
      if (active.current && token === generation.current) setError(failure);
    } finally {
      running.current = false;
      if (active.current && token === generation.current) setBusy(false);
    }
  }
  async function choose(entry: CorrectionEvidenceEntry) {
    if (running.current || disabled) return;
    running.current = true;
    const token = ++generation.current;
    setBusy(true);
    setError(null);
    setDetail(null);
    try {
      const { data } = await api<unknown>(`${path}/${entry.evidence_id}`);
      const exact = await validateCorrectionEvidenceDetail(
        data,
        scope,
        base,
        entry,
      );
      if (active.current && token === generation.current) setDetail(exact);
    } catch (failure) {
      if (active.current && token === generation.current) setError(failure);
    } finally {
      running.current = false;
      if (active.current && token === generation.current) setBusy(false);
    }
  }
  return (
    <div className="rule-correction-evidence">
      <button
        type="button"
        className="secondary"
        disabled={disabled || busy || !supportsApi("GET", path)}
        aria-expanded={opened}
        onClick={() => {
          if (opened) setOpened(false);
          else if (loaded) setOpened(true);
          else void load();
        }}
      >
        选择冻结原页依据
      </button>
      {opened && (
        <div className="rule-correction-directory">
          <p>来源固定为当前清单的招标／补遗版本，不切换到最新解析。</p>
          {busy && <p role="status">正在读取确切原页证据…</p>}
          {error != null && (
            <ErrorNotice error={error} onRetry={() => void load()} />
          )}
          <div className="rule-correction-evidence-list">
            {items.map((item, index) => (
              <button
                type="button"
                key={item.evidence_id}
                disabled={disabled || busy}
                aria-pressed={detail?.evidence.evidence_id === item.evidence_id}
                onClick={() => void choose(item)}
              >
                <strong>
                  依据 {index + 1} · {item.member_id} · 物理页{" "}
                  {item.physical_page}
                </strong>
                <span>{item.excerpt || "目录没有摘要，请读取完整证据。"}</span>
              </button>
            ))}
          </div>
          {loaded && !busy && !items.length && (
            <p>该清单的冻结原页目录暂无可用文字依据，不能改取其他解析。</p>
          )}
          {next && (
            <button
              type="button"
              disabled={disabled || busy}
              onClick={() => void load(next)}
            >
              更多冻结原页
            </button>
          )}
          {detail && (
            <QuoteEditor
              key={`${base.inventoryDigest}:${detail.evidence.evidence_id}`}
              scope={scope}
              detail={detail}
              disabled={disabled || busy}
              selected={selected}
              onSelect={onSelect}
            />
          )}
        </div>
      )}
    </div>
  );
}
