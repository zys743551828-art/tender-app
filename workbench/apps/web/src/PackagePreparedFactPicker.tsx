import { useEffect, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import { ErrorNotice } from "./components";
import type {
  PackageExecutionInputView,
  PackagePreparedFactPage,
  PackagePreparedFactSummary,
} from "./contracts";
import type { FreezeScope } from "./packageFrozenInput";
import { executionPath } from "./executionInputRecovery";
import { matchesPreparedFacts } from "./preparedFactDirectory";
type Props = {
  scope: FreezeScope;
  frozenId: string;
  prepared: PackageExecutionInputView;
  disabled: boolean;
  onSelect: (item: PackagePreparedFactSummary) => void;
  description?: string;
};
export default function PackagePreparedFactPicker(props: Props) {
  return (
    <Picker
      key={JSON.stringify([
        props.scope,
        props.frozenId,
        props.prepared.manifest.id,
        props.prepared.digest,
      ])}
      {...props}
    />
  );
}
function Picker({
  scope,
  frozenId,
  prepared,
  disabled,
  onSelect,
  description = "读取此准备输入保存时的事实摘要，按名称选择后核对范围；事实更新不会替换这里的旧记录。",
}: Props) {
  const [items, setItems] = useState<PackagePreparedFactSummary[]>([]),
    [cursor, setCursor] = useState<string | null>(null),
    [loaded, setLoaded] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  const active = useRef(false),
    running = useRef(false),
    seen = useRef(new Set<string>());
  const path = `${executionPath(scope, frozenId)}/${prepared.manifest.id}/facts`,
    available = supportsApi("GET", path);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  async function read(more = false) {
    if (running.current || disabled || !available || (more && !cursor)) return;
    const after = more ? cursor : null;
    running.current = true;
    setBusy(true);
    setError(null);
    if (!more) {
      setItems([]);
      setCursor(null);
      setLoaded(false);
      seen.current.clear();
    }
    try {
      const { data } = await api<PackagePreparedFactPage>(
        `${path}?limit=20${after ? `&cursor=${encodeURIComponent(after)}` : ""}`,
      );
      if (!matchesPreparedFacts(data, scope, frozenId, prepared, after))
        throw new Error("原事实目录身份、摘要或分页状态不符，未采纳。");
      if (
        (more &&
          (data.items.some(
            (x) =>
              items.some((old) => old.fact_id === x.fact_id) ||
              (items.length > 0 &&
                x.fact_id <= items[items.length - 1].fact_id),
          ) ||
            items.length + data.items.length > data.fact_count)) ||
        (data.next_cursor !== null && seen.current.has(data.next_cursor))
      )
        throw new Error("原事实目录出现重复记录或游标，已停止追加。");
      if (active.current) {
        if (data.next_cursor) seen.current.add(data.next_cursor);
        setItems(more ? [...items, ...data.items] : data.items);
        setCursor(data.next_cursor);
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
      className="package-frozen-input__fact-picker"
      aria-label="按名称选择原事实"
    >
      <p>{description}</p>
      <button
        type="button"
        className="button secondary"
        disabled={busy || disabled || !available}
        onClick={() => void read()}
      >
        {busy ? "正在读取原事实…" : "读取原事实列表"}
      </button>
      {!available && <p>当前服务尚未提供原事实摘要目录。</p>}
      {loaded && !items.length && <p>此准备输入没有保存事实。</p>}
      {items.length > 0 && (
        <ul>
          {items.map((item) => (
            <li key={item.fact_id}>
              <button
                type="button"
                className="button secondary"
                disabled={busy || disabled}
                onClick={() => onSelect(item)}
              >
                <span>
                  {item.name} · {item.value_preview}
                  {item.unit ? ` ${item.unit}` : ""}
                  <small>
                    原主体：{item.subject}；原范围：{item.scope}
                  </small>
                  {item.preview_truncated && (
                    <small>摘要有截断，请结合完整原资料核对。</small>
                  )}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {cursor && (
        <button
          type="button"
          className="button secondary"
          disabled={busy || disabled}
          onClick={() => void read(true)}
        >
          加载更多原事实
        </button>
      )}
      {error != null && <ErrorNotice error={error} />}
    </section>
  );
}
