import { useCallback, useEffect, useRef, useState } from "react";

type Entry<T> = { version: number; value: T };
/** Only a completed server ACK can drain this queue. Lost responses replay first. */
export function useSaveQueue<T>(
  save: (value: T) => Promise<void>,
  delay = 800,
  replayFailure: (error: unknown) => boolean = () => true,
) {
  const replayRef = useRef(replayFailure);
  replayRef.current = replayFailure;
  const saveRef = useRef(save);
  saveRef.current = save;
  const pending = useRef<Entry<T> | null>(null);
  const failed = useRef<Entry<T> | null>(null);
  const inFlight = useRef<Promise<boolean> | null>(null);
  const counter = useRef(0);
  const errorRef = useRef<unknown>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mounted = useRef(true);
  const [phase, setPhase] = useState<"saved" | "pending" | "saving" | "failed">(
    "saved",
  );
  const [error, setError] = useState<unknown>(null);
  const flush = useCallback((): Promise<boolean> => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    if (inFlight.current) return inFlight.current;
    if (!pending.current && !failed.current) return Promise.resolve(true);
    const work = (async () => {
      if (mounted.current) {
        setPhase("saving");
        setError(null);
      }
      errorRef.current = null;
      while (failed.current || pending.current) {
        const entry = failed.current ?? pending.current!;
        try {
          await saveRef.current(entry.value);
          failed.current = null;
          if (pending.current?.version === entry.version)
            pending.current = null;
        } catch (failure) {
          failed.current = replayRef.current(failure) ? entry : null;
          errorRef.current = failure;
          if (mounted.current) {
            setError(failure);
            setPhase("failed");
          }
          return false;
        }
      }
      if (mounted.current) setPhase("saved");
      return true;
    })();
    inFlight.current = work;
    void work.finally(() => {
      if (inFlight.current === work) inFlight.current = null;
    });
    return work;
  }, []);
  const change = useCallback(
    (value: T) => {
      if (!mounted.current) return;
      pending.current = { version: ++counter.current, value };
      if (!inFlight.current && !errorRef.current) setPhase("pending");
      if (timer.current) clearTimeout(timer.current);
      // Failure requires an explicit retry; new typing cannot silently replay a command.
      if (!errorRef.current)
        timer.current = setTimeout(() => {
          void flush();
        }, delay);
    },
    [delay, flush],
  );
  const discard = useCallback(() => {
    if (inFlight.current) return false;
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    pending.current = null;
    failed.current = null;
    errorRef.current = null;
    setError(null);
    setPhase("saved");
    return true;
  }, []);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);
  return {
    phase,
    error,
    change,
    flush,
    discard,
    isDirty: () => !!pending.current || !!failed.current || !!inFlight.current,
  };
}
