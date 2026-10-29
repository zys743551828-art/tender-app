import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { validateTaskTriggerPage } from "./taskPackageProtocol";
import type { PackageTriggerIntentPage } from "./taskTriggerContracts";
import { useResource } from "./useResource";

/** Validate every page before deriving navigation; a refreshed first page invalidates the previous continuation. */
export function useTaskTriggerPage(bidId: string, enabled: boolean, poll = 0) {
  const path = `/bids/${bidId}/task-package-trigger-intents?limit=20`;
  const resource = useResource<unknown>(
    enabled ? path : null,
    enabled ? poll : 0,
  );
  const head = useMemo(() => {
    try {
      return {
        data: resource.data
          ? validateTaskTriggerPage(resource.data, bidId)
          : undefined,
        error: null,
      };
    } catch (error) {
      return { data: undefined, error };
    }
  }, [resource.data, bidId]);
  const [extra, setExtra] = useState<{
    source: unknown;
    path: string;
    pages: PackageTriggerIntentPage[];
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const active = useRef(true);
  const current = useRef({ path, source: resource.data });
  current.current = { path, source: resource.data };
  const inFlight = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    setError(null);
  }, [path]);
  const pages =
    extra && extra.source === resource.data && extra.path === path
      ? extra.pages
      : [];
  const items = [
    ...(head.data?.items ?? []),
    ...pages.flatMap((page) => page.items),
  ];
  const cursor = (pages.at(-1) ?? head.data)?.next_after ?? null;
  async function more() {
    if (!enabled || !cursor || !head.data || inFlight.current) return;
    const source = resource.data;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const response = await api<unknown>(
        `${path}&after=${encodeURIComponent(cursor)}`,
      );
      const page = validateTaskTriggerPage(response.data, bidId);
      if (
        page.next_after === cursor ||
        page.items.some((item) => items.some((old) => old.id === item.id))
      )
        throw new Error("触发目录分页重复或未前进，原目录保留。");
      if (
        active.current &&
        current.current.source === source &&
        current.current.path === path
      )
        setExtra({ path, source, pages: [...pages, page] });
    } catch (failure) {
      if (
        active.current &&
        current.current.source === source &&
        current.current.path === path
      )
        setError(failure);
    } finally {
      inFlight.current = false;
      if (active.current) setBusy(false);
    }
  }
  return {
    ...resource,
    data: head.data,
    error: head.error ?? resource.error,
    items,
    hasMore: !!cursor,
    more,
    moreBusy: busy,
    moreError: error,
  };
}
