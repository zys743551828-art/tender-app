import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import { ErrorNotice } from "./components";
import { freezePath } from "./packageFrozenInput";
import type { FreezeScope } from "./packageFrozenInput";
import type { PackageReviewFrozenInputPage } from "./contracts";
import { validateFrozenInputPage } from "./frozenInputDirectory";
import type { FrozenInputSummary } from "./frozenInputDirectory";

type Props = {
  scope: FreezeScope;
  enabled: boolean;
  refreshId?: string;
  onSelect: (item: FrozenInputSummary) => void;
};
type Snapshot = {
  items: FrozenInputSummary[];
  cursor: string | null;
  cursors: string[];
  busy: boolean;
  loaded: boolean;
  error: unknown;
};
const empty = (): Snapshot => ({
  items: [],
  cursor: null,
  cursors: [],
  busy: false,
  loaded: false,
  error: null,
});

/** Caller keys the frozen workspace by exact scope; request generations also guard close/reopen. */
export default function PackageFrozenInputDirectory({
  scope,
  enabled,
  refreshId,
  onSelect,
}: Props) {
  const { memberId, bidId, packageId, revisionId, inventoryId } = scope;
  const bound = useMemo(
    () => ({ memberId, bidId, packageId, revisionId, inventoryId }),
    [memberId, bidId, packageId, revisionId, inventoryId],
  );
  const path = `${freezePath(bound)}?limit=20`;
  const available = supportsApi("GET", path);
  const [snapshot, setSnapshot] = useState<Snapshot>(empty);
  const current = useRef(snapshot);
  const generation = useRef(0);
  const running = useRef(false);
  const invalidate = useCallback(() => {
    generation.current++;
    running.current = false;
  }, []);
  const read = useCallback(
    async (more = false) => {
      if (
        !enabled ||
        !available ||
        running.current ||
        (more && !current.current.cursor)
      )
        return;
      const root = more ? current.current : empty();
      const cursor = more ? root.cursor : null;
      const ticket = ++generation.current;
      running.current = true;
      setSnapshot({ ...root, busy: true, error: null });
      try {
        const { data } = await api<PackageReviewFrozenInputPage>(
          `${path}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        );
        validateFrozenInputPage(
          data,
          bound,
          root.items,
          cursor ? [...root.cursors, cursor] : [],
        );
        if (ticket !== generation.current) return;
        const next = {
          items: [...root.items, ...data.items],
          cursor: data.next_cursor,
          cursors: cursor ? [...root.cursors, cursor] : [],
          busy: false,
          loaded: true,
          error: null,
        };
        current.current = next;
        setSnapshot(next);
      } catch (error) {
        if (ticket === generation.current) {
          const next = { ...root, busy: false, error };
          current.current = next;
          setSnapshot(next);
        }
      } finally {
        if (ticket === generation.current) running.current = false;
      }
    },
    [enabled, available, path, bound],
  );
  useEffect(() => {
    current.current = empty();
    setSnapshot(empty());
    void read();
    return invalidate;
  }, [read, refreshId, invalidate]);
  if (!available)
    return <p>当前服务尚未提供冻结输入历史目录，仍可按编号读取。</p>;
  return (
    <div className="package-frozen-input__directory">
      <p>
        按冻结时间从新到旧列出此清单下的记录。选择后读取完整记录，不替换当前候选或未决请求。
      </p>
      <button
        className="button secondary"
        type="button"
        disabled={!enabled || snapshot.busy}
        onClick={() => void read()}
      >
        刷新历史目录
      </button>
      {snapshot.busy && <p role="status">正在读取历史目录…</p>}
      {snapshot.error != null && <ErrorNotice error={snapshot.error} />}
      {snapshot.loaded && !snapshot.items.length && (
        <p>此清单尚无冻结输入记录。</p>
      )}
      {!!snapshot.items.length && (
        <>
          <p>已读取 {snapshot.items.length} 条记录。</p>
          <ul>
            {snapshot.items.map((item) => (
              <li key={item.id}>
                <button
                  className="button secondary"
                  type="button"
                  onClick={() => onSelect(item)}
                >
                  <span>
                    查看 {new Date(item.frozen_at).toLocaleString()} 的冻结记录
                    <br />
                    <code>{item.id}</code>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
      {snapshot.cursor && (
        <button
          className="button secondary"
          type="button"
          disabled={snapshot.busy}
          onClick={() => void read(true)}
        >
          加载更多冻结记录
        </button>
      )}
    </div>
  );
}
