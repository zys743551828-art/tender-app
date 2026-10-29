import { useEffect, useRef, useState } from "react";
import { api, ApiError, commandKey, completeCommand, supportsApi } from "./api";

export function useCommand(scope: string) {
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
  const pending = useRef<{
    signature: string;
    scope: string;
    key: string;
    etag: string | null;
  } | null>(null);
  async function run<T>(
    path: string,
    body: unknown,
    etag: string | null,
    method = "POST",
  ) {
    if (inFlight.current || !active.current) return null;
    if (!supportsApi(method, path)) {
      setError(
        new ApiError("此操作尚未开放，输入已保留。", 501, "NOT_AVAILABLE"),
      );
      return null;
    }
    const signature = JSON.stringify({ path, method, body });
    if (
      pending.current?.signature !== signature ||
      pending.current.scope !== scope
    )
      pending.current = {
        signature,
        scope,
        etag,
        key: commandKey(scope, { signature, etag }),
      };
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await api<T>(path, {
        method,
        body,
        etag: pending.current.etag,
        key: pending.current.key,
      });
      pending.current = null;
      // If the caller has left, retain the key so restored input can recover this ACK.
      if (active.current) completeCommand(scope);
      return active.current ? result : null;
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 412)
        pending.current = null;
      if (active.current) setError(failure);
      return null;
    } finally {
      inFlight.current = false;
      if (active.current) setBusy(false);
    }
  }
  return {
    busy,
    error,
    run,
    clearError: () => setError(null),
    conflict: error instanceof ApiError && error.status === 412,
  };
}
