import type {
  HistoryPending,
  HistoryReceipt,
} from "./packageHistoricalResearchProtocol";
import { ErrorNotice } from "./components";

export type HistoryCommands = {
  blocked: boolean;
  busy: boolean;
  send: (pending: HistoryPending) => Promise<HistoryReceipt | null>;
};

export function HistoryDirectoryStatus({
  noun,
  page,
  count,
  busy,
  error,
  onLoad,
  onMore,
}: {
  noun: string;
  page: null | {
    status: "observed" | "unavailable";
    total: number | null;
    has_more: boolean | null;
  };
  count: number;
  busy: boolean;
  error: unknown;
  onLoad: () => void;
  onMore: () => void;
}) {
  return (
    <>
      <div className="package-history-toolbar">
        <button
          type="button"
          className="button secondary"
          disabled={busy}
          onClick={onLoad}
        >
          {busy ? `正在读取${noun}…` : `读取${noun}目录`}
        </button>
        {page?.status === "observed" && (
          <span className="small-note">
            已读取 {count} / {page.total} 条
          </span>
        )}
        {page?.has_more && (
          <button
            type="button"
            className="text-button"
            disabled={busy}
            onClick={onMore}
          >
            加载更多{noun}
          </button>
        )}
      </div>
      <ErrorNotice error={error} />
      {error != null && page && (
        <p className="small-note">
          下面保留上次读取的目录；请重新读取第一页后继续选择。
        </p>
      )}
      {page?.status === "unavailable" && (
        <p className="notice neutral">
          {noun}
          目录尚未配置，记录数量未知。服务可用后再读取；这不表示历史记录不存在。
        </p>
      )}
      {page?.status === "observed" && page.total === 0 && (
        <p className="small-empty">本次已观察到的{noun}目录为空。</p>
      )}
      {page?.status === "observed" && count > 0 && (
        <p className="small-note">
          目录只提供既有记录；当前来源和执行资格尚未重新核对，打开详情后再作决定。
        </p>
      )}
    </>
  );
}
