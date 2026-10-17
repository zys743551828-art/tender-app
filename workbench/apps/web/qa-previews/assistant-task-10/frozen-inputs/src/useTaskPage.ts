import { useRef, useState, useEffect } from "react";
import { api } from "./api";
import { useResource } from "./useResource";
/** All pages use the actual server cursor. New first pages invalidate the retained cursor chain. */
export function useTaskPage<T extends { items: { id: string }[] }>(
  path: string,
  poll = 0,
  cursorFor: (page: T) => string | null,
  param = "cursor",
) {
  const resource = useResource<T>(path, poll);
  const [pages, setPages] = useState<
    { path: string; cursor: string; page: T }[]
  >([]);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const chain: T[] = [];
  let cursor = resource.data ? cursorFor(resource.data) : null;
  const seen = new Set<string>();
  while (cursor && !seen.has(cursor)) {
    seen.add(cursor);
    const page = [...pages]
      .reverse()
      .find((item) => item.path === path && item.cursor === cursor);
    if (!page) break;
    chain.push(page.page);
    cursor = cursorFor(page.page);
  }
  const items = [
    ...new Map(
      [
        ...(resource.data?.items ?? []),
        ...chain.flatMap((page) => page.items),
      ].map((item) => [item.id, item]),
    ).values(),
  ] as T["items"];
  async function more() {
    if (!cursor || pending.current) return;
    pending.current = true;
    setBusy(true);
    setError(null);
    try {
      const value = await api<T>(
        `${path}${path.includes("?") ? "&" : "?"}${param}=${encodeURIComponent(cursor)}`,
      );
      if (cursorFor(value.data) === cursor)
        throw new Error("服务器分页位置未前进，已有记录保留。");
      if (mounted.current)
        setPages((old) => [
          ...old,
          { path, cursor: cursor!, page: value.data },
        ]);
    } catch (error) {
      if (mounted.current) setError(error);
    } finally {
      pending.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return {
    ...resource,
    items,
    hasMore: !!cursor,
    more,
    moreBusy: busy,
    moreError: error,
  };
}
