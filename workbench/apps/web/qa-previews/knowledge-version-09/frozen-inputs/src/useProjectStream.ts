import { useEffect, useState } from "react";
import { supportsApi } from "./api";
import { changeSequence, eventDecoder } from "./eventStream";

export function useProjectStream(streamId: string | undefined, bidId: string) {
  const [session, setSession] = useState(0);
  useEffect(() => {
    const restore = () => setSession((value) => value + 1);
    window.addEventListener("auth-restored", restore);
    return () => window.removeEventListener("auth-restored", restore);
  }, []);
  useEffect(() => {
    if (!streamId || !supportsApi("GET", `/streams/${streamId}/events`)) return;
    const controller = new AbortController();
    let reconnect: ReturnType<typeof setTimeout> | undefined;
    let refreshTimer: ReturnType<typeof setTimeout> | undefined;
    const key = `tender:stream:${streamId}`;
    let seq = Number(sessionStorage.getItem(key) ?? 0);
    if (!Number.isSafeInteger(seq) || seq < 0) seq = 0;
    let stopped = false;
    function refresh() {
      if (refreshTimer || stopped) return;
      refreshTimer = setTimeout(() => {
        refreshTimer = undefined;
        window.dispatchEvent(
          new CustomEvent("server-snapshot-change", { detail: { bidId } }),
        );
      }, 300);
    }
    function expire() {
      stopped = true;
      window.dispatchEvent(new Event("session-expired"));
    }
    function reset() {
      seq = 0;
      sessionStorage.removeItem(key);
      refresh();
    }
    async function connect() {
      let delay = 1000;
      let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
      try {
        const headers = new Headers({ Accept: "text/event-stream" });
        if (seq) headers.set("Last-Event-ID", `${streamId}:${seq}`);
        const response = await fetch(`/api/v1/streams/${streamId}/events`, {
          headers,
          credentials: "same-origin",
          signal: controller.signal,
        });
        if (response.status === 401) {
          expire();
          return;
        }
        if (response.status === 410) {
          reset();
          return;
        }
        if (
          !response.ok ||
          !response.headers
            .get("Content-Type")
            ?.startsWith("text/event-stream") ||
          !response.body
        ) {
          delay = 5000;
          return;
        }
        refresh();
        let reconnectNow = false;
        const decode = eventDecoder((frame) => {
          if (frame.event === "control") {
            try {
              const control = JSON.parse(frame.data) as { code?: unknown };
              if (
                control.code === "SESSION_EXPIRED" ||
                control.code === "UNAUTHENTICATED"
              )
                expire();
              else if (control.code === "RESET_REQUIRED") {
                reset();
                reconnectNow = true;
              } else {
                delay = 5000;
                reconnectNow = true;
              }
            } catch {
              delay = 5000;
              reconnectNow = true;
            }
            return;
          }
          const next = changeSequence(frame, streamId!, bidId, seq);
          if (next !== null && !stopped && !reconnectNow) {
            seq = next;
            sessionStorage.setItem(key, String(seq));
            refresh();
          }
        });
        reader = response.body.getReader();
        const utf8 = new TextDecoder();
        while (!stopped && !controller.signal.aborted && !reconnectNow) {
          const { value, done } = await reader.read();
          if (done) break;
          decode(utf8.decode(value, { stream: true }));
        }
      } catch {
        delay = 5000;
      } finally {
        await reader?.cancel().catch(() => {});
        if (!stopped && !controller.signal.aborted)
          reconnect = setTimeout(() => void connect(), delay);
      }
    }
    void connect();
    return () => {
      stopped = true;
      controller.abort();
      clearTimeout(reconnect);
      clearTimeout(refreshTimer);
    };
  }, [streamId, bidId, session]);
}
