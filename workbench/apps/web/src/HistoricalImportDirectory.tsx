import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { HistoricalImportPage } from "./contracts";
import { ErrorNotice } from "./components";
import {
  historicalSame,
  validateHistoricalDirectory,
} from "./historicalImportProtocol";

export function HistoricalImportDirectory({
  selected,
  onSelect,
}: {
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const [mode, setMode] = useState(""),
    [items, setItems] = useState<HistoricalImportPage["items"]>([]),
    [next, setNext] = useState<number | null>(null);
  const [busy, setBusy] = useState(false),
    [loaded, setLoaded] = useState(false),
    [error, setError] = useState<unknown>(null);
  const active = useRef(false),
    running = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  async function load(offset = 0) {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await api<unknown>(
        `/research/imports?limit=20&offset=${offset}${mode ? `&mode=${mode}` : ""}`,
      );
      const checked = validateHistoricalDirectory(result.data, offset);
      const merged = new Map(
        (offset ? items : []).map((item) => [item.id, item]),
      );
      checked.items.forEach((item) => {
        const old = merged.get(item.id);
        if (old && !historicalSame(old, item))
          throw new Error("目录在读取期间变化，请重新读取第一页后再选择。");
        merged.set(item.id, item);
      });
      if (active.current) {
        setItems([...merged.values()]);
        setNext(checked.next_offset);
        setLoaded(true);
      }
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  return (
    <section
      className="historical-import-directory"
      aria-label="历史导入批次目录"
    >
      <div className="section-heading">
        <h3>已保存的导入批次</h3>
        <button
          type="button"
          className="text-button"
          disabled={busy}
          onClick={() => void load()}
        >
          读取导入批次目录
        </button>
      </div>
      <label>
        批次状态
        <select
          aria-label="批次状态"
          value={mode}
          disabled={busy}
          onChange={(event) => {
            setMode(event.target.value);
            setItems([]);
            setNext(null);
            setLoaded(false);
            setError(null);
          }}
        >
          <option value="">全部</option>
          <option value="dry_run">待确认预检查</option>
          <option value="confirmed_import">已确认导入</option>
        </select>
      </label>
      <p className="small-note">
        目录和详情只读取既有批次，不创建预检查、不重新登记、不发起模型调用。
      </p>
      {busy && <p role="status">正在读取导入目录…</p>}
      {error != null && <ErrorNotice error={error} />}
      {loaded && !items.length && <p>当前筛选下尚无导入批次。</p>}
      <div className="historical-import-directory-list">
        {items.map((item) => (
          <button
            type="button"
            key={item.id}
            aria-pressed={selected === item.id}
            onClick={() => onSelect(item.id)}
          >
            <strong>
              {item.mode === "dry_run" ? "待确认预检查" : "已确认导入"} ·{" "}
              {item.counts.total} 条
            </strong>
            <span>
              {item.created_at
                ? new Date(item.created_at).toLocaleString("zh-CN")
                : "创建时间未记录"}{" "}
              · 修订 {item.revision}
            </span>
            <span>
              可处理 {item.counts.pending} · 已登记 / 复用{" "}
              {item.counts.imported} · 异常 {item.counts.errors}
            </span>
          </button>
        ))}
      </div>
      {next !== null && (
        <button
          type="button"
          className="text-button"
          disabled={busy}
          onClick={() => void load(next)}
        >
          更多导入批次
        </button>
      )}
    </section>
  );
}
