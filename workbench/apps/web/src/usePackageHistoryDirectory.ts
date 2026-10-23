import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import {
  historyBase,
  validateHistoryDirectory,
  type HistoryDirectoryByKind,
  type HistoryDirectoryFilters,
  type HistoryDirectoryKind,
} from "./packageHistoricalResearchProtocol";

export function usePackageHistoryDirectory<K extends HistoryDirectoryKind>(
  kind: K,
  filters: HistoryDirectoryFilters,
) {
  type Page = HistoryDirectoryByKind[K];
  type Item = Page["items"][number];
  const filterKey = JSON.stringify(filters);
  const [page, setPage] = useState<Page | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const active = useRef(false),
    ticket = useRef(0),
    running = useRef(false);
  const state = useRef<{ page: Page | null; items: Item[]; cursors: string[] }>(
    { page: null, items: [], cursors: [] },
  );
  useEffect(() => {
    active.current = true;
    ticket.current += 1;
    running.current = false;
    state.current = { page: null, items: [], cursors: [] };
    setPage(null);
    setItems([]);
    setError(null);
    setBusy(false);
    return () => {
      active.current = false;
      ticket.current += 1;
    };
  }, [kind, filterKey]);
  const load = useCallback(
    async (more = false) => {
      if (!active.current || running.current) return;
      const previous = state.current;
      const cursor =
        more && previous.page?.status === "observed"
          ? previous.page.next_cursor
          : null;
      if (more && !cursor) return;
      const expected = JSON.parse(filterKey) as HistoryDirectoryFilters;
      const path =
        kind === "jobs"
          ? `${historyBase}/cohorts/${expected.cohort_id}/jobs`
          : `${historyBase}/${kind}`;
      const query = new URLSearchParams({ limit: "20" });
      if (kind === "admissions" && expected.bid_id)
        query.set("bid_id", expected.bid_id);
      if (kind === "admissions" && expected.scope_id)
        query.set("scope_id", expected.scope_id);
      if (kind === "cohorts" && expected.protocol_id)
        query.set("protocol_id", expected.protocol_id);
      if (cursor) query.set("cursor", cursor);
      const own = ++ticket.current;
      running.current = true;
      setBusy(true);
      setError(null);
      try {
        const response = await api<unknown>(`${path}?${query}`);
        const next = await validateHistoryDirectory(
          kind,
          response.data,
          expected,
        );
        if (
          more &&
          (next.status !== "observed" ||
            previous.page?.status !== "observed" ||
            next.observation_digest !== previous.page.observation_digest ||
            next.total !== previous.page.total)
        )
          throw new Error(
            "目录观察已变化，已保留上次记录；请重新读取第一页，不拼接不同观察。",
          );
        const combined = more
          ? [...previous.items, ...next.items]
          : [...next.items];
        if (new Set(combined.map((item) => item.id)).size !== combined.length)
          throw new Error("目录出现重复记录，请重新读取第一页后再选择。");
        if (
          next.status === "observed" &&
          (combined.length > next.total ||
            (!next.has_more && combined.length !== next.total) ||
            (next.has_more &&
              (combined.length >= next.total ||
                !next.next_cursor ||
                next.next_cursor === cursor ||
                previous.cursors.includes(next.next_cursor))))
        )
          throw new Error("目录分页数量或游标不一致，请重新读取第一页。");
        if (!active.current || own !== ticket.current) return;
        state.current = {
          page: next,
          items: combined as Item[],
          cursors: more && cursor ? [...previous.cursors, cursor] : [],
        };
        setPage(next);
        setItems(combined as Item[]);
      } catch (failure) {
        if (active.current && own === ticket.current) setError(failure);
      } finally {
        if (active.current && own === ticket.current) {
          running.current = false;
          setBusy(false);
        }
      }
    },
    [kind, filterKey],
  );
  return { page, items, busy, error, load };
}
