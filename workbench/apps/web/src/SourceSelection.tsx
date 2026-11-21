import { useState } from "react";
import type {
  DocumentEvidenceView,
  EvidenceView,
  MaterialView,
} from "./contracts";
import { Badge } from "./components";
import { normalizeEvidenceQuery } from "./evidenceTextSearch";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";

export function SourceSelection({
  bidId,
  selected,
  onChange,
}: {
  bidId: string;
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  const materials = useResource<MaterialView>(`/bids/${bidId}/materials`);
  const [documentId, setDocumentId] = useState("");
  const evidence = useResource<DocumentEvidenceView>(
    documentId ? `/documents/${documentId}/evidence` : null,
  );
  return (
    <div className="source-selection">
      <ResourceState
        {...materials}
        hasData={!!materials.data}
        onRetry={() => void materials.reload()}
      />
      <label>
        选择来源文件
        <select
          value={documentId}
          onChange={(event) => setDocumentId(event.target.value)}
        >
          <option value="">选择已入库资料</option>
          {materials.data?.documents
            .filter(
              (document) =>
                document.role !== "official_result" && document.role !== "body",
            )
            .map((document) => (
              <option value={document.id} key={document.id}>
                {document.filename} · 版本 {document.file_revision}
              </option>
            ))}
        </select>
      </label>
      <p className="small-note">
        仅选择能证明该项工程事实的来源。已选 {selected.length}{" "}
        处依据，最终效力与适用性由服务端核验。
      </p>
      {documentId && (
        <>
          <ResourceState
            {...evidence}
            hasData={!!evidence.data}
            onRetry={() => void evidence.reload()}
          />
          {evidence.data?.gaps.map((gap, index) => (
            <p className="small-note" key={index}>
              {gap}
            </p>
          ))}
          {evidence.data && (
            <QuotePicker
              key={documentId}
              items={evidence.data.items}
              selected={selected}
              onChange={onChange}
            />
          )}
        </>
      )}
    </div>
  );
}

function QuotePicker({
  items,
  selected,
  onChange,
}: {
  items: EvidenceView[];
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  const [page, setPage] = useState("");
  const [quote, setQuote] = useState("");
  const needle = normalizeEvidenceQuery(quote);
  const pageNumber = page.trim();
  const visible = items.filter(
    (item) =>
      (!pageNumber ||
        (/^\d+$/.test(pageNumber) &&
          item.physical_page === Number(pageNumber))) &&
      (!needle || normalizeEvidenceQuery(item.quote).includes(needle)),
  );
  if (!items.length)
    return <p className="small-note">当前文件暂无原页摘录。</p>;
  return (
    <>
      <div
        className="field-pair"
        onKeyDown={(event) => {
          // Searching a quote must not implicitly submit the surrounding fact form.
          if (event.key === "Enter" && !event.nativeEvent.isComposing)
            event.preventDefault();
        }}
      >
        <label>
          按物理页筛选
          <input
            inputMode="numeric"
            value={page}
            placeholder="全部物理页"
            onChange={(event) => setPage(event.target.value)}
          />
        </label>
        <label>
          按摘录原文筛选
          <input
            type="search"
            value={quote}
            onChange={(event) => setQuote(event.target.value)}
          />
        </label>
      </div>
      <p className="small-note" role="status">
        {visible.length
          ? `显示 ${visible.length} / ${items.length} 处原页摘录。`
          : `本文件的 ${items.length} 处原页摘录中没有匹配项。`}
      </p>
      {(page || quote) && (
        <button
          type="button"
          className="text-button"
          onClick={() => {
            setPage("");
            setQuote("");
          }}
        >
          清除摘录筛选
        </button>
      )}
      {!!visible.length && (
        <div className="source-quote-picker">
          {visible.map((item) => (
            <label key={item.id} className="evidence-select-item">
              <input
                type="checkbox"
                checked={selected.includes(item.id)}
                disabled={
                  item.source_status === "withdrawn" ||
                  (!selected.includes(item.id) && selected.length >= 100)
                }
                onChange={(event) =>
                  onChange(
                    event.target.checked
                      ? [...selected, item.id]
                      : selected.filter((id) => id !== item.id),
                  )
                }
              />
              <span>
                <Badge>物理页 {item.physical_page}</Badge>
                <span className="source-quote-text">{item.quote}</span>
              </span>
            </label>
          ))}
        </div>
      )}
    </>
  );
}
