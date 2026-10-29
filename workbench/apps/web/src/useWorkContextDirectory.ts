import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

type Page<T> = {
  items: T[];
  total: number;
  has_more: boolean;
  next_cursor: string | null;
  observation_digest: string;
};
/** A caller remounts this scope on member/project/stage changes. Pages are never mixed across observations. */
export function useWorkContextDirectory<
  T extends { id: string },
  P extends Page<T>,
>(path: string, validate: (value: unknown) => Promise<P>) {
  const [page, setPage] = useState<P | null>(null),
    [items, setItems] = useState<T[]>([]),
    [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false);
  const active = useRef(false),
    pending = useRef(false),
    ticket = useRef(0),
    current = useRef<{ page: P | null; items: T[]; cursors: Set<string> }>({
      page: null,
      items: [],
      cursors: new Set(),
    });
  const load = useCallback(
    async (append = false) => {
      if (!active.current || pending.current) return;
      const before = current.current;
      if (append && (!before.page?.has_more || !before.page.next_cursor))
        return;
      pending.current = true;
      setBusy(true);
      setError(null);
      const request = ++ticket.current,
        cursor = append ? before.page!.next_cursor : null;
      try {
        const { data } = await api<unknown>(
          `${path}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        );
        const next = await validate(data),
          all = append ? [...before.items, ...next.items] : next.items;
        if (
          (append &&
            (before.page?.observation_digest !== next.observation_digest ||
              before.page.total !== next.total)) ||
          new Set(all.map((i) => i.id)).size !== all.length ||
          all.length > next.total ||
          (next.has_more
            ? all.length >= next.total
            : all.length !== next.total) ||
          (next.next_cursor !== null &&
            (next.next_cursor === cursor ||
              (append && before.cursors.has(next.next_cursor))))
        )
          throw new Error(
            "目录分页的观察或顺序已变化，请从首页重新读取；原选择仍保留。",
          );
        if (!active.current || request !== ticket.current) return;
        const cursors = append ? new Set(before.cursors) : new Set<string>();
        if (cursor) cursors.add(cursor);
        current.current = { page: next, items: all, cursors };
        setPage(next);
        setItems(all);
      } catch (failure) {
        if (active.current && request === ticket.current) setError(failure);
      } finally {
        if (active.current && request === ticket.current) {
          pending.current = false;
          setBusy(false);
        }
      }
    },
    [path, validate],
  );
  useEffect(() => {
    active.current = true;
    void load();
    const requests = ticket;
    return () => {
      active.current = false;
      pending.current = false;
      requests.current++;
    };
  }, [load]);
  return { page, items, error, busy, load };
}
