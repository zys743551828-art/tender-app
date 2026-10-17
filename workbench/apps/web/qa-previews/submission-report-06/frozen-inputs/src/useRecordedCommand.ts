import { useEffect, useRef, useState } from "react";
import { api, ApiError, commandKey, completeCommand, supportsApi } from "./api";
import type { ApiResult } from "./api";

type RequestRecord = {
  path: string;
  body: unknown;
  etag: string;
  key: string;
};

export function clearRecordedCommands(keepMemberId?: string) {
  for (const key of Object.keys(sessionStorage)) {
    const match = key.match(
      /^tender:command(?:-record)?:(?:submission|report|pricing-formula|pricing-simulate|pricing-save):([^:]+):/,
    );
    if (match && (!keepMemberId || match[1] !== keepMemberId))
      sessionStorage.removeItem(key);
  }
}

/** Retain the exact uncertain request across refresh; a new snapshot is never a retry. */
export function useRecordedCommand(scope: string) {
  const storageKey = `tender:command-record:${scope}`;
  const [pending, setPending] = useState<RequestRecord | null>(() => {
    try {
      const value = JSON.parse(sessionStorage.getItem(storageKey) ?? "null");
      return value &&
        typeof value.path === "string" &&
        typeof value.etag === "string" &&
        typeof value.key === "string"
        ? value
        : null;
    } catch {
      return null;
    }
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const active = useRef(true);
  const running = useRef(false);
  const record = useRef(pending);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  function persist(value: RequestRecord | null) {
    try {
      if (value) sessionStorage.setItem(storageKey, JSON.stringify(value));
      else sessionStorage.removeItem(storageKey);
    } catch {
      throw new Error(
        "浏览器暂时无法保存请求恢复记录。输入保留，请释放此站点存储空间后重试；未取得的结果仍可从服务器历史核对。",
      );
    }
    record.current = value;
    if (active.current) setPending(value);
  }
  async function send<T>(request: RequestRecord): Promise<ApiResult<T> | null> {
    if (running.current || !active.current) return null;
    if (!supportsApi("POST", request.path)) {
      setError(
        new ApiError(
          "服务器尚未开放此操作，已保留本次输入。",
          501,
          "NOT_AVAILABLE",
        ),
      );
      return null;
    }
    running.current = true;
    setBusy(true);
    setError(null);
    try {
      persist(request);
      const result = await api<T>(request.path, {
        method: "POST",
        body: request.body,
        etag: request.etag,
        key: request.key,
      });
      // An unmounted caller must be able to recover this same acknowledgement.
      if (!active.current) return null;
      persist(null);
      completeCommand(scope);
      return result;
    } catch (failure) {
      if (active.current) {
        setError(failure);
        if (
          failure instanceof ApiError &&
          ((failure.status >= 400 &&
            failure.status < 500 &&
            ![408, 429].includes(failure.status)) ||
            [
              "REPORT_RENDERER_NOT_CONFIGURED",
              "SUBMISSION_ORIGINAL_UNAVAILABLE",
            ].includes(failure.code))
        ) {
          persist(null);
          completeCommand(scope);
        }
      }
      return null;
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  return {
    pending,
    busy,
    error,
    conflict: error instanceof ApiError && error.status === 412,
    clearError: () => setError(null),
    async run<T>(path: string, body: unknown, etag: string) {
      if (record.current) {
        setError(
          new Error("上次请求的结果尚未取得，请先恢复原请求结果。输入已保留。"),
        );
        return null;
      }
      const key = commandKey(scope, { path, body, etag });
      return send<T>({ path, body, etag, key });
    },
    retry<T>() {
      return record.current ? send<T>(record.current) : Promise.resolve(null);
    },
  };
}
