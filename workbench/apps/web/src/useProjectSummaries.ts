import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { ProjectWorkSummary, ProjectWorkSummaryBatch } from "./contracts";
import { checkedProjectSummaries } from "./projectSummaries";

type Snapshot = {
  key: string;
  loading: boolean;
  items: Map<string, ProjectWorkSummary>;
  error?: unknown;
};

export function useProjectSummaries(ids: readonly string[]) {
  const key = ids.join(",");
  const [snapshot, setSnapshot] = useState<Snapshot>();
  const generation = useRef(0);
  const invalidate = useCallback(() => {
    generation.current++;
  }, []);
  const reload = useCallback(async () => {
    const current = ++generation.current;
    const selected = key ? key.split(",") : [];
    setSnapshot({ key, loading: selected.length > 0, items: new Map() });
    if (!selected.length) return;
    try {
      const batches = [];
      for (let index = 0; index < selected.length; index += 20)
        batches.push(selected.slice(index, index + 20));
      const pages: ProjectWorkSummaryBatch[] = [];
      for (let index = 0; index < batches.length; index += 2) {
        if (generation.current !== current) return;
        pages.push(
          ...(await Promise.all(
            batches.slice(index, index + 2).map(async (batch) => {
              const query = new URLSearchParams(
                batch.map((id) => ["bid_id", id]),
              );
              const response = await api<unknown>(
                `/project-work-summaries?${query}`,
              );
              return checkedProjectSummaries(response.data, batch);
            }),
          )),
        );
      }
      if (generation.current === current)
        setSnapshot({
          key,
          loading: false,
          items: new Map(
            pages.flatMap((page) =>
              page.items.map((item) => [item.bid_id, item] as const),
            ),
          ),
        });
    } catch (error) {
      if (generation.current === current)
        setSnapshot({ key, loading: false, items: new Map(), error });
    }
  }, [key]);
  useEffect(() => {
    void reload();
    const changed = () => void reload();
    window.addEventListener("server-snapshot-change", changed);
    return () => {
      invalidate();
      window.removeEventListener("server-snapshot-change", changed);
    };
  }, [reload, invalidate]);
  const current = snapshot?.key === key ? snapshot : undefined;
  return {
    items: current?.items ?? new Map<string, ProjectWorkSummary>(),
    loading: key.length > 0 && (!current || current.loading),
    error: current?.error,
    reload,
  };
}
