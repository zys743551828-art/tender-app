import { useEffect, useMemo, useState } from "react";
import { api, ApiError, commandKey, completeCommand, supportsApi } from "./api";
import type { ApiResult } from "./api";
export { clearRecordedCommands } from "./recordedCommandStorage";

type RequestRecord = {
  path: string;
  body: unknown;
  etag: string;
  key: string;
  method?: "POST" | "PUT" | "PATCH";
};

type CommandSession = {
  scope: string;
  storageKey: string;
  record: RequestRecord | null;
  active: boolean;
  running: boolean;
};

type CommandState = {
  session: CommandSession;
  pending: RequestRecord | null;
  busy: boolean;
  error: unknown;
};

function readRecord(storageKey: string): RequestRecord | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(storageKey) ?? "null");
    return value &&
      typeof value.path === "string" &&
      typeof value.etag === "string" &&
      typeof value.key === "string" &&
      [undefined, "POST", "PUT", "PATCH"].includes(value.method)
      ? value
      : null;
  } catch {
    return null;
  }
}

function initialState(session: CommandSession): CommandState {
  return { session, pending: session.record, busy: false, error: null };
}

/** Retain the exact uncertain request across refresh; a new snapshot is never a retry. */
export function useRecordedCommand(
  scope: string,
  validateResponse?: (result: ApiResult<unknown>) => void | Promise<void>,
) {
  const session = useMemo<CommandSession>(() => {
    const storageKey = `tender:command-record:${scope}`;
    return {
      scope,
      storageKey,
      record: readRecord(storageKey),
      active: false,
      running: false,
    };
  }, [scope]);
  const [state, setState] = useState(() => initialState(session));
  const { pending, busy, error } =
    state.session === session ? state : initialState(session);
  useEffect(() => {
    session.active = true;
    return () => {
      session.active = false;
    };
  }, [session]);
  function updateState(patch: Partial<Omit<CommandState, "session">>) {
    if (session.active)
      setState((previous) => ({
        ...(previous.session === session ? previous : initialState(session)),
        ...patch,
      }));
  }
  function persist(value: RequestRecord | null) {
    try {
      if (value)
        sessionStorage.setItem(session.storageKey, JSON.stringify(value));
      else sessionStorage.removeItem(session.storageKey);
    } catch {
      throw new Error(
        "浏览器暂时无法保存请求恢复记录。输入保留，请释放此站点存储空间后重试；未取得的结果仍可从服务器历史核对。",
      );
    }
    session.record = value;
    updateState({ pending: value });
  }
  async function send<T>(request: RequestRecord): Promise<ApiResult<T> | null> {
    if (session.running || !session.active) return null;
    if (!supportsApi(request.method ?? "POST", request.path)) {
      updateState({
        error: new ApiError(
          "服务器尚未开放此操作，已保留本次输入。",
          501,
          "NOT_AVAILABLE",
        ),
      });
      return null;
    }
    session.running = true;
    updateState({ busy: true, error: null });
    let acknowledged = false;
    try {
      persist(request);
      const result = await api<T>(request.path, {
        method: request.method ?? "POST",
        body: request.body,
        etag: request.etag,
        key: request.key,
      });
      acknowledged = true;
      // A caller that left this scope must recover the same acknowledgement.
      if (!session.active) return null;
      await validateResponse?.(result);
      if (!session.active) return null;
      persist(null);
      completeCommand(session.scope);
      return result;
    } catch (failure) {
      if (session.active) {
        updateState({ error: failure });
        if (
          !acknowledged &&
          failure instanceof ApiError &&
          ((failure.status >= 400 &&
            failure.status < 500 &&
            ![408, 429].includes(failure.status)) ||
            [
              "MODEL_NOT_CONFIGURED",
              "REPORT_RENDERER_NOT_CONFIGURED",
              "SUBMISSION_ORIGINAL_UNAVAILABLE",
            ].includes(failure.code))
        ) {
          persist(null);
          completeCommand(session.scope);
        }
      }
      return null;
    } finally {
      session.running = false;
      updateState({ busy: false });
    }
  }
  return {
    pending,
    busy,
    error,
    conflict: error instanceof ApiError && error.status === 412,
    clearError: () => updateState({ error: null }),
    async run<T>(
      path: string,
      body: unknown,
      etag: string,
      method: "POST" | "PUT" | "PATCH" = "POST",
    ) {
      if (!session.active) return null;
      if (session.record) {
        updateState({
          error: new Error(
            "上次请求的结果尚未取得，请先恢复原请求结果。输入已保留。",
          ),
        });
        return null;
      }
      const request = {
        path,
        body,
        etag,
        ...(method === "POST" ? {} : { method }),
      };
      const key = commandKey(session.scope, request);
      return send<T>({ ...request, key });
    },
    retry<T>() {
      return session.record ? send<T>(session.record) : Promise.resolve(null);
    },
  };
}
