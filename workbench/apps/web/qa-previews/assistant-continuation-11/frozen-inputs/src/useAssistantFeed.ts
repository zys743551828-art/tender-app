import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type {
  AssistantGlobalEventPage,
  AssistantGlobalMessagePage,
  WorkMessagePage,
} from "./contracts";
import type { AssistantMessage } from "./assistantState";
import { knowledgeStorageKey } from "./knowledgeStorage";
import { useResource } from "./useResource";

export function useAssistantPolling(milliseconds = 4000) {
  const [active, setActive] = useState(true);
  useEffect(() => {
    const stop = () => setActive(false);
    const resume = () => setActive(true);
    window.addEventListener("session-expired", stop);
    window.addEventListener("auth-restored", resume);
    return () => {
      window.removeEventListener("session-expired", stop);
      window.removeEventListener("auth-restored", resume);
    };
  }, []);
  return active ? milliseconds : 0;
}

/** Pages remain linked to the newest page's actual cursor, even when new messages arrive. */
export function useAssistantMessages(
  path: string | null,
  conversationId: string | undefined,
  bidId: string | null,
) {
  type Page = WorkMessagePage | AssistantGlobalMessagePage;
  const poll = useAssistantPolling();
  const first = useResource<Page>(path, poll);
  const [pages, setPages] = useState<
    { path: string; cursor: string; page: Page }[]
  >([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const pending = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const readable = (page: Page) =>
    page.items.every(
      (message) =>
        message.conversation_id === conversationId && message.bid_id === bidId,
    );
  const rootValid = !first.data || readable(first.data);
  const chain: Page[] = [];
  let cursor = rootValid && first.data?.has_more ? first.data.before : null;
  const visited = new Set<string>();
  while (cursor && !visited.has(cursor)) {
    visited.add(cursor);
    const found = [...pages]
      .reverse()
      .find((page) => page.path === path && page.cursor === cursor);
    if (!found || !readable(found.page)) break;
    chain.push(found.page);
    cursor = found.page.has_more ? found.page.before : null;
  }
  const items: AssistantMessage[] = [
    ...new Map(
      [
        ...chain.flatMap<AssistantMessage>((page) => page.items),
        ...(rootValid ? (first.data?.items ?? []) : []),
      ].map((item) => [item.id, item]),
    ).values(),
  ].sort(
    (a, b) =>
      Date.parse(a.created_at) - Date.parse(b.created_at) ||
      a.id.localeCompare(b.id),
  );
  async function more() {
    if (!path || !cursor || pending.current) return;
    pending.current = true;
    setBusy(true);
    setError(null);
    try {
      const value = await api<Page>(
        `${path}&before=${encodeURIComponent(cursor)}`,
      );
      if (
        !readable(value.data) ||
        (value.data.has_more && value.data.before === cursor)
      )
        throw new Error("消息历史身份或分页位置不一致，未拼入其他记录。");
      if (mounted.current)
        setPages((old) => [
          ...old,
          { path, cursor: cursor!, page: value.data },
        ]);
    } catch (failure) {
      if (mounted.current) setError(failure);
    } finally {
      pending.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return {
    ...first,
    items,
    hasMore: !!cursor,
    more,
    moreBusy: busy,
    moreError: error,
    identityError: rootValid
      ? null
      : new Error("会话消息范围不一致，未显示其他会话内容。"),
  };
}

/** Global events carry private persistent facts. They only invalidate read models, never execute tools. */
export function useAssistantGlobalEvents(
  conversationId: string | undefined,
  memberId: string,
  enabled: boolean,
) {
  const interval = useAssistantPolling(2500);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    if (!enabled || !conversationId || !interval) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const storageKey =
      knowledgeStorageKey(memberId, conversationId) + "assistant-event-cursor";
    let seq = 0;
    try {
      seq = Number(sessionStorage.getItem(storageKey) ?? 0);
      if (!Number.isSafeInteger(seq) || seq < 0) seq = 0;
    } catch {
      /* Cursor persistence is optional for read recovery. */
    }
    async function poll() {
      let delay = interval;
      try {
        const { data } = await api<AssistantGlobalEventPage>(
          `/assistant/global-conversations/${conversationId}/events?after=${seq}&limit=100`,
        );
        if (stopped) return;
        if (
          data.stream_id !== conversationId ||
          !Number.isSafeInteger(data.next_cursor) ||
          data.next_cursor < seq ||
          data.items.some(
            (item, index) =>
              item.seq <= (index ? data.items[index - 1].seq : seq),
          )
        )
          throw new Error("助手处理记录的位置无法核对，请重新读取主会话。");
        setError(null);
        if (data.next_cursor > seq) {
          seq = data.next_cursor;
          try {
            sessionStorage.setItem(storageKey, String(seq));
          } catch {
            /* Re-read from zero is safe. */
          }
          window.dispatchEvent(new Event("server-snapshot-change"));
        }
        if (seq < data.head_cursor) delay = 100;
      } catch (failure) {
        if (!stopped) setError(failure);
        if (stopped || (failure instanceof ApiError && failure.status === 401))
          return;
        if (failure instanceof ApiError && failure.status === 410) {
          seq = 0;
          try {
            sessionStorage.removeItem(storageKey);
          } catch {
            /* The next read starts from zero. */
          }
          window.dispatchEvent(new Event("server-snapshot-change"));
        }
      }
      if (!stopped) timer = setTimeout(() => void poll(), delay);
    }
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [conversationId, memberId, enabled, interval]);
  return error;
}
