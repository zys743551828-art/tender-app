import { useEffect, useState } from "react";
import { api } from "./api";
import type { ReviewPage } from "./contracts";
import { Badge, ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";

export function ReviewHistory({
  bidId,
  selectedId,
  onOpen,
}: {
  bidId: string;
  selectedId: string | null;
  onOpen: (id: string) => void;
}) {
  const resource = useResource<ReviewPage>(`/bids/${bidId}/reviews`);
  const [pages, setPages] = useState<ReviewPage[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    setPages([]);
  }, [resource.data]);
  const last = pages.at(-1) ?? resource.data;
  const items = [
    ...new Map(
      [
        ...(resource.data?.items ?? []),
        ...pages.flatMap((page) => page.items),
      ].map((item) => [item.id, item]),
    ).values(),
  ];
  const foreign = items.some((item) => item.bid_id !== bidId);
  async function loadMore() {
    if (!last?.next_cursor || busy) return;
    setBusy(true);
    setError(null);
    try {
      const { data } = await api<ReviewPage>(
        `/bids/${bidId}/reviews?cursor=${encodeURIComponent(last.next_cursor)}`,
      );
      setPages((old) => [...old, data]);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="review-history">
      <summary>
        查看项目评审历史{items.length > 0 ? ` · 已加载 ${items.length} 轮` : ""}
      </summary>
      <div className="panel">
        <button className="text-button" onClick={() => void resource.reload()}>
          刷新评审历史
        </button>
        <ResourceState
          {...resource}
          hasData={!!resource.data}
          onRetry={() => {
            void resource.reload();
          }}
        />
        <ErrorNotice error={error} onRetry={() => void loadMore()} />
        {foreign ? (
          <div className="notice error" role="alert">
            评审历史项目身份不一致，未展示其他项目轮次。请刷新核对。
          </div>
        ) : (
          <>
            {resource.data && items.length === 0 && (
              <p className="small-empty">
                此项目暂无可读取的评审轮次。准备中的请求单独显示，不算已完成评审。
              </p>
            )}
            {items.map((review) => (
              <article className="history-review-row" key={review.id}>
                <div>
                  <strong>评审轮次 {review.id.slice(0, 8)}</strong>
                  <p className="small-note">
                    {review.current ? "对应当前项目输入" : "历史固定输入"} ·{" "}
                    {review.risk_count === null
                      ? "风险与问题计数尚未完整"
                      : `本轮记录 ${review.risk_count} 项风险与问题`}{" "}
                    ·{" "}
                    {review.core_coverage === "complete"
                      ? "已识别规则核对已完成"
                      : review.core_coverage === "failed"
                        ? "核心核对失败"
                        : review.core_coverage === "pending"
                          ? "核心核对待处理"
                          : "核心覆盖不完整"}
                  </p>
                </div>
                {selectedId === review.id ? (
                  <Badge>正在查看</Badge>
                ) : (
                  <button
                    className="button secondary"
                    onClick={() => onOpen(review.id)}
                  >
                    查看此轮评审
                  </button>
                )}
              </article>
            ))}
            {last?.has_more && (
              <button
                className="button secondary"
                disabled={busy || !last.next_cursor}
                onClick={() => void loadMore()}
              >
                {busy ? "正在读取历史轮次…" : "加载更早的评审轮次"}
              </button>
            )}
          </>
        )}
      </div>
    </details>
  );
}
