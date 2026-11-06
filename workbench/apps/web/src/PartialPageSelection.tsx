import { useState } from "react";
import { api, commandKey } from "./api";
import type { DocumentEvidenceView, DocumentView } from "./contracts";
import { ErrorNotice } from "./components";
import { PartialPageComparison } from "./PartialPageComparison";

export type Selection = {
  id: string;
  current_material: boolean;
  source_effectivity: "not_verified";
  model_execution_allowed: false;
  formal_qualification: false;
  proof: {
    digest: string;
    manifest: {
      purpose: "technical_reference" | "requirement_reference";
      coverage: "partial";
      source: {
        document_version_id: string;
        parse_run_id: string;
        file_digest: string;
      };
      selection: { first_page: number; last_page: number };
      selected_pages: {
        physical_page: number;
        quality: string;
        gaps: string[];
      }[];
      selected_blocks: { id: string; physical_page: number }[];
      omitted_ranges: { first_page: number; last_page: number }[];
    };
  };
};

export function PartialPageSelection({
  document,
  evidence,
  page,
  pageCount,
  onPage,
}: {
  document: DocumentView;
  evidence: DocumentEvidenceView;
  page: number;
  pageCount: number;
  onPage: (page: number) => void;
}) {
  const [first, setFirst] = useState(page);
  const [last, setLast] = useState(page);
  const [purpose, setPurpose] = useState<
    "technical_reference" | "requirement_reference"
  >("technical_reference");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [scopedEvidence, setScopedEvidence] = useState<
    {
      id: string;
      physical_page: number;
      quote: string;
      source_status: string;
    }[]
  >([]);
  const [history, setHistory] = useState<
    { id: string; confirmed_by: string; created_at: string }[]
  >([]);
  const path = `/bids/${document.bid_id}/partial-page-selections`;
  async function save() {
    if (!evidence.parse_run_id || !confirmed) return;
    const body = {
      document_version_id: document.id,
      parse_run_id: evidence.parse_run_id,
      first_page: first,
      last_page: last,
      purpose,
      confirmed: true,
    };
    setBusy(true);
    setError(null);
    try {
      const created = await api<Selection>(path, {
        method: "POST",
        body,
        key: commandKey(`partial-pages:${document.id}`, body),
      });
      const checked = await api<Selection>(`${path}/${created.data.id}`);
      if (
        checked.data.proof.digest !== created.data.proof.digest ||
        checked.data.id !== created.data.id ||
        checked.data.proof.manifest.source.document_version_id !==
          document.id ||
        checked.data.proof.manifest.source.parse_run_id !==
          evidence.parse_run_id ||
        checked.data.proof.manifest.source.file_digest !== document.sha256
      )
        throw new Error("已保存记录与复核依据不一致，请重新读取。");
      setSelection(checked.data);
      setScopedEvidence([]);
    } catch (value) {
      setError(value);
    } finally {
      setBusy(false);
    }
  }
  async function loadHistory() {
    setBusy(true);
    setError(null);
    try {
      const result = await api<{ items: typeof history; has_more: boolean }>(
        `${path}?document_version_id=${encodeURIComponent(document.id)}`,
      );
      setHistory(result.data.items);
      if (result.data.has_more)
        setError(new Error("仅显示最近 100 条记录，较早记录未列出。"));
    } catch (value) {
      setError(value);
    } finally {
      setBusy(false);
    }
  }
  async function show(id: string) {
    setBusy(true);
    setError(null);
    try {
      const value = (await api<Selection>(`${path}/${id}`)).data;
      if (
        value.proof.manifest.source.document_version_id !== document.id ||
        value.proof.manifest.source.parse_run_id !== evidence.parse_run_id ||
        value.proof.manifest.source.file_digest !== document.sha256
      )
        throw new Error("历史记录对应的原件或解析版本不同，请先打开对应版本。");
      setSelection(value);
      setScopedEvidence([]);
    } catch (value) {
      setError(value);
    } finally {
      setBusy(false);
    }
  }
  async function loadScopedEvidence() {
    if (!selection) return;
    setBusy(true);
    setError(null);
    try {
      const value = (
        await api<{
          selection_id: string;
          proof_digest: string;
          items: typeof scopedEvidence;
          model_execution_allowed: false;
          formal_qualification: false;
        }>(`${path}/${selection.id}/evidence`)
      ).data;
      const expected = new Map(
        selection.proof.manifest.selected_blocks.map((block) => [
          block.id,
          block.physical_page,
        ]),
      );
      if (
        value.selection_id !== selection.id ||
        value.proof_digest !== selection.proof.digest ||
        value.model_execution_allowed !== false ||
        value.formal_qualification !== false ||
        value.items.length !==
          selection.proof.manifest.selected_blocks.length ||
        new Set(value.items.map((item) => item.id)).size !==
          value.items.length ||
        value.items.some((item) => expected.get(item.id) !== item.physical_page)
      )
        throw new Error("选中证据与确认记录不一致，请重新核对。");
      setScopedEvidence(value.items);
    } catch (value) {
      setError(value);
    } finally {
      setBusy(false);
    }
  }
  const valid =
    Number.isSafeInteger(first) &&
    Number.isSafeInteger(last) &&
    first >= 1 &&
    first <= last &&
    last <= pageCount;
  return (
    <details className="notice partial-page-selection">
      <summary>人工确认部分页范围</summary>
      <p>
        先对照原页核对。此记录保留原件、解析、页码和缺口；不改变材料用途、不接入模型，也不授予完整评审资格。
      </p>
      <label>
        起始物理页{" "}
        <input
          type="number"
          min={1}
          max={pageCount || undefined}
          value={first}
          onChange={(event) => {
            setFirst(Number(event.target.value));
            setConfirmed(false);
          }}
        />
      </label>
      <label>
        结束物理页{" "}
        <input
          type="number"
          min={1}
          max={pageCount || undefined}
          value={last}
          onChange={(event) => {
            setLast(Number(event.target.value));
            setConfirmed(false);
          }}
        />
      </label>
      <label>
        用途{" "}
        <select
          value={purpose}
          onChange={(event) => {
            setPurpose(event.target.value as typeof purpose);
            setConfirmed(false);
          }}
        >
          <option value="technical_reference">技术内容参考</option>
          <option value="requirement_reference">招标要求参考</option>
        </select>
      </label>
      <label className="partial-checkbox">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        我已核对所选原页，理解缺失与未选页仍未知。
      </label>
      <button
        type="button"
        disabled={busy || !valid || !confirmed || !evidence.parse_run_id}
        onClick={() => void save()}
      >
        确认并保存页范围
      </button>
      <button type="button" disabled={busy} onClick={() => void loadHistory()}>
        查看历史范围
      </button>
      <ErrorNotice error={error} />
      {history.map((item) => (
        <button type="button" key={item.id} onClick={() => void show(item.id)}>
          {new Date(item.created_at).toLocaleString()} · {item.id.slice(0, 8)}
        </button>
      ))}
      {selection && (
        <div role="status">
          <strong>人工确认记录 · 部分覆盖</strong>
          <p>
            物理页 {selection.proof.manifest.selection.first_page}—
            {selection.proof.manifest.selection.last_page}；
            {selection.proof.manifest.selected_blocks.length} 个已记录证据块。
          </p>
          <p>
            有缺口页：
            {selection.proof.manifest.selected_pages
              .filter((p) => p.quality !== "usable" || p.gaps.length)
              .map((p) => p.physical_page)
              .join("、") || "无已报告缺口"}
            ；未选范围：
            {selection.proof.manifest.omitted_ranges
              .map((r) => `${r.first_page}—${r.last_page}`)
              .join("、") || "无"}
            。
          </p>
          {!selection.current_material && (
            <p>这是历史资料范围，当前材料已变化。</p>
          )}
          <p>
            来源有效性及原件字节未重新验证；不可据此调用模型或认定正式资格。
          </p>
          <PartialPageComparison
            key={selection.id}
            path={path}
            selection={selection}
          />
          <details>
            <summary>查看所选范围的解析依据</summary>
            <p>点击物理页对照原件和解析文本；不把 OCR 摘录当作原文确认。</p>
            <button
              type="button"
              disabled={busy}
              onClick={() => void loadScopedEvidence()}
            >
              读取所选范围证据
            </button>
            {scopedEvidence.map((item) => (
              <div key={item.id}>
                <strong>
                  第 {item.physical_page} 页 · 来源状态 {item.source_status}
                </strong>
                <p>{item.quote}</p>
              </div>
            ))}
            {selection.proof.manifest.selected_pages.map((item) => (
              <button
                type="button"
                key={item.physical_page}
                onClick={() => onPage(item.physical_page)}
              >
                第 {item.physical_page} 物理页
              </button>
            ))}
          </details>
        </div>
      )}
    </details>
  );
}
