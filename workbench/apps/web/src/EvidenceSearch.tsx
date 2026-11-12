import { useId, useMemo, useState } from "react";
import type { EvidenceView } from "./contracts";
import { searchEvidence } from "./evidenceTextSearch";

export function EvidenceSearch({
  items,
  onPage,
}: {
  items: EvidenceView[];
  onPage: (page: number) => void;
}) {
  const [query, setQuery] = useState("");
  const description = useId();
  const result = useMemo(() => searchEvidence(items, query), [items, query]);
  return (
    <section className="notice evidence-gaps" aria-label="查找已加载解析文本">
      <div>
        <label>
          查找本文件解析文本
          <input
            type="search"
            value={query}
            maxLength={200}
            aria-describedby={description}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        {query && (
          <button
            type="button"
            className="text-button"
            onClick={() => setQuery("")}
          >
            清空查找
          </button>
        )}
        <p id={description}>
          仅搜索当前文件已加载的文本，忽略中文之间的空白和英文字母大小写。不会纠正
          OCR
          字形或数字，也不跨文本块匹配；未找到不代表原件没有该内容。已撤回来源不参与查找。命中不代表识别完整或评审通过。
        </p>
        {query.trim() && (
          <>
            <p role="status">
              找到 {result.total} 个文本块
              {result.total > 30 ? "，仅列出前 30 个，请缩小查询范围" : ""}。
            </p>
            <ul>
              {result.items.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => onPage(item.physical_page)}
                  >
                    查看匹配文本 · 第 {item.physical_page} 页
                  </button>
                  <p>
                    {item.quote.length > 300
                      ? `${item.quote.slice(0, 300)}…（仅展示原始文本开头）`
                      : item.quote}
                  </p>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </section>
  );
}
