import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { useResource } from "./useResource";

/** Cursor-only collections use their actual server shape and explicit item identity. */
export function useCursorList<
  T extends { items: unknown[]; next_cursor: string | null },
>(path: string | null, identity: (item: T["items"][number]) => string) {
  const first = useResource<T>(path);
  const [pages, setPages] = useState<
    { path: string; root: T | undefined; page: T }[]
  >([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const active = useRef(true);
  const inFlight = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const matching = pages
    .filter((page) => page.path === path && page.root === first.data)
    .map((page) => page.page);
  const last = matching.at(-1) ?? first.data;
  const items = [
    ...new Map(
      [
        ...(first.data?.items ?? []),
        ...matching.flatMap((page) => page.items),
      ].map((item) => [identity(item), item]),
    ).values(),
  ] as T["items"];
  async function more() {
    if (!path || inFlight.current || !last?.next_cursor) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const { data } = await api<T>(
        `${path}${path.includes("?") ? "&" : "?"}cursor=${encodeURIComponent(last.next_cursor)}`,
      );
      if (data.next_cursor === last.next_cursor)
        throw new Error("分页游标没有推进，请重读当前记录。");
      if (active.current)
        setPages((old) => [...old, { path, root: first.data, page: data }]);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      inFlight.current = false;
      if (active.current) setBusy(false);
    }
  }
  return {
    ...first,
    items,
    hasMore: !!last?.next_cursor,
    more,
    moreBusy: busy,
    moreError: error,
  };
}
