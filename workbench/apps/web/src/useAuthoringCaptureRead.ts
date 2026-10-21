import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

/** A failed refresh retains the selected view, but it cannot authorize a new save. */
export function useAuthoringCaptureRead<T>(
  path: string | null,
  validate: (value: unknown) => Promise<T> | T,
) {
  const [state, setState] = useState<{
    path: string | null;
    value: T | null;
    busy: boolean;
    error: unknown;
    ready: boolean;
  }>({ path, value: null, busy: false, error: null, ready: false });
  const active = useRef({ path, epoch: 0, live: false, running: false });
  const load = useCallback(async () => {
    const s = active.current;
    if (!path || !s.live || s.path !== path || s.running) return;
    s.running = true;
    const epoch = ++s.epoch;
    setState((old) => ({
      path,
      value: old.path === path ? old.value : null,
      busy: true,
      error: null,
      ready: false,
    }));
    try {
      const response = await api<unknown>(path),
        value = await validate(response.data);
      if (s.live && active.current === s && epoch === s.epoch)
        setState({ path, value, busy: false, error: null, ready: true });
    } catch (error) {
      if (s.live && active.current === s && epoch === s.epoch)
        setState((old) => ({ ...old, path, busy: false, error, ready: false }));
    } finally {
      s.running = false;
    }
  }, [path, validate]);
  useEffect(() => {
    const s = { path, epoch: 0, live: true, running: false };
    active.current = s;
    if (path) void load();
    return () => {
      s.live = false;
      ++s.epoch;
    };
  }, [path, load]);
  return {
    ...(state.path === path
      ? state
      : { value: null, busy: !!path, error: null, ready: false }),
    reload: load,
  };
}

export type CaptureDirectoryPage<T> = {
  items: T[];
  next_cursor: string | null;
  has_more: boolean;
  observation_digest?: string;
  total_items?: number;
};
/** Pages must advance without duplicates; observed catalogs are pinned as a whole. */
export function useAuthoringCaptureDirectory<
  P extends CaptureDirectoryPage<{ id: string }>,
>(path: string | null, validate: (value: unknown) => Promise<P> | P) {
  type T = P["items"][number];
  const [state, setState] = useState<{
    path: string | null;
    page: P | null;
    items: T[];
    busy: boolean;
    error: unknown;
    ready: boolean;
  }>({ path, page: null, items: [], busy: false, error: null, ready: false });
  const current = useRef({
    path,
    epoch: 0,
    live: false,
    running: false,
    page: null as P | null,
    items: [] as T[],
    cursors: new Set<string>(),
  });
  const load = useCallback(
    async (append = false) => {
      const s = current.current;
      if (
        !path ||
        !s.live ||
        s.path !== path ||
        s.running ||
        (append && !s.page?.next_cursor)
      )
        return;
      const cursor = append ? s.page!.next_cursor : null,
        before = s.page;
      s.running = true;
      const epoch = ++s.epoch;
      setState((old) => ({
        ...(old.path === path ? old : { path, page: null, items: [] }),
        busy: true,
        error: null,
        ready: false,
      }));
      try {
        const { data } = await api<unknown>(
          path +
            (cursor
              ? `${path.includes("?") ? "&" : "?"}cursor=${encodeURIComponent(cursor)}`
              : ""),
        );
        const page = await validate(data),
          items = append ? [...s.items, ...page.items] : page.items;
        if (
          (append && before?.observation_digest !== page.observation_digest) ||
          (append && before?.total_items !== page.total_items) ||
          new Set(items.map((i) => i.id)).size !== items.length ||
          (page.next_cursor !== null &&
            (page.next_cursor === cursor ||
              (append && s.cursors.has(page.next_cursor)))) ||
          (page.total_items !== undefined &&
            (items.length > page.total_items ||
              (page.has_more
                ? items.length >= page.total_items
                : items.length !== page.total_items)))
        )
          throw new Error(
            "目录分页重复、遗漏或观察发生变化；保留原选择，请从首页重新读取。",
          );
        if (!s.live || current.current !== s || epoch !== s.epoch) return;
        if (!append) s.cursors.clear();
        if (cursor) s.cursors.add(cursor);
        s.page = page;
        s.items = items;
        setState({ path, page, items, busy: false, error: null, ready: true });
      } catch (error) {
        if (s.live && current.current === s && epoch === s.epoch)
          setState((old) => ({
            ...old,
            path,
            busy: false,
            error,
            ready: false,
          }));
      } finally {
        s.running = false;
      }
    },
    [path, validate],
  );
  useEffect(() => {
    const s = {
      path,
      epoch: 0,
      live: true,
      running: false,
      page: null as P | null,
      items: [] as T[],
      cursors: new Set<string>(),
    };
    current.current = s;
    if (path) void load();
    return () => {
      s.live = false;
      ++s.epoch;
    };
  }, [path, load]);
  return {
    ...(state.path === path
      ? state
      : {
          page: null,
          items: [] as T[],
          busy: !!path,
          error: null,
          ready: false,
        }),
    load,
  };
}
