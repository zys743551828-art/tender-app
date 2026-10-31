import { useCallback, useEffect, useRef, useState } from "react";
import { api, supportsApi } from "./api";

type Snapshot<T> = {
  path: string;
  data?: T;
  etag: string | null;
  loading: boolean;
  error?: unknown;
};

export function useResource<T>(path: string | null, pollMs = 0) {
  const [snapshot, setSnapshot] = useState<Snapshot<T> | null>(null);
  const generation = useRef(0);
  const inFlight = useRef<{
    path: string;
    generation: number;
    completion: Promise<void>;
  } | null>(null);
  const invalidate = useCallback(() => {
    generation.current++;
    inFlight.current = null;
  }, []);
  const supported = path !== null && supportsApi("GET", path);
  const reload = useCallback(async () => {
    if (!path || !supported) return;
    if (
      inFlight.current?.path === path &&
      inFlight.current.generation === generation.current
    )
      // A caller awaiting reload must also await an already active read.
      return inFlight.current.completion;
    const current = ++generation.current;
    let complete!: () => void;
    const completion = new Promise<void>((resolve) => {
      complete = resolve;
    });
    inFlight.current = { path, generation: current, completion };
    setSnapshot((old) => ({
      path,
      data: old?.path === path ? old.data : undefined,
      etag: old?.path === path ? old.etag : null,
      error: old?.path === path ? old.error : undefined,
      loading: true,
    }));
    try {
      const result = await api<T>(path);
      if (generation.current === current)
        setSnapshot({
          path,
          data: result.data,
          etag: result.etag,
          loading: false,
        });
    } catch (error) {
      if (generation.current === current)
        setSnapshot((old) => ({
          path,
          data: old?.path === path ? old.data : undefined,
          etag: old?.path === path ? old.etag : null,
          loading: false,
          error,
        }));
    } finally {
      if (inFlight.current?.generation === current) inFlight.current = null;
      complete();
    }
    return completion;
  }, [path, supported]);
  useEffect(() => {
    void reload();
    const changed = () => void reload();
    window.addEventListener("server-snapshot-change", changed);
    const timer = pollMs
      ? window.setInterval(() => void reload(), pollMs)
      : null;
    return () => {
      window.removeEventListener("server-snapshot-change", changed);
      invalidate();
      if (timer) window.clearInterval(timer);
    };
  }, [reload, pollMs, invalidate]);
  const current = snapshot?.path === path ? snapshot : null;
  return {
    data: current?.data,
    etag: current?.etag ?? null,
    loading: supported && (!current || current.loading),
    error: current?.error,
    unavailable: path !== null && !supported,
    reload,
  };
}
