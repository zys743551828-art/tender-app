import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "./api";
import { ErrorNotice } from "./components";
import type {
  PackageReviewComparisonPage,
  PackageReviewComparisonRow,
  PackageReviewRunView,
} from "./contracts";
import {
  packageReviewComparisonHeader,
  packageReviewComparisonPath,
  packageReviewComparisonTotal,
  validateCompletePackageReviewComparison,
  validatePackageReviewComparisonPage,
} from "./packageReviewComparisonProtocol";
import type { PackageReviewComparisonSelection } from "./packageReviewComparisonSelection";
import {
  loadPackageReviewComparisonSelection,
  storePackageReviewComparisonSelection,
  validPackageReviewComparisonSelection,
} from "./packageReviewComparisonSelection";
import PackageReviewComparisonView from "./PackageReviewComparisonView";
import "./packageReviewComparison.css";

type Props = {
  memberId: string;
  bidId: string;
  currentRun: PackageReviewRunView;
};
export default function PackageReviewComparisonWorkspace(p: Props) {
  return <ComparisonWorkspace key={`${p.memberId}:${p.bidId}`} {...p} />;
}
function ComparisonWorkspace({ memberId, bidId, currentRun }: Props) {
  const [loaded] = useState(() => {
    try {
      return {
        selection: loadPackageReviewComparisonSelection(
          memberId,
          bidId,
          currentRun.id,
        ),
        error: null,
      };
    } catch (error) {
      return {
        selection: {
          version: 1 as const,
          memberId,
          bidId,
          leftId: "",
          rightId: currentRun.id,
        },
        error,
      };
    }
  });
  const [selection, setSelection] = useState(loaded.selection),
    [storageError, setStorageError] = useState<unknown>(loaded.error),
    [pages, setPages] = useState<PackageReviewComparisonPage[]>([]),
    [pageIndex, setPageIndex] = useState(0),
    [reading, setReading] = useState(false),
    [error, setError] = useState<unknown>(null),
    [stale, setStale] = useState(false),
    [complete, setComplete] = useState(false);
  const active = useRef(false),
    busy = useRef(false),
    ticket = useRef(0),
    pagesRef = useRef(pages),
    seenRows = useRef(new Map<string, PackageReviewComparisonRow>()),
    seenCursors = useRef(new Set<string>());
  useEffect(() => {
    active.current = true;
    const requests = ticket;
    return () => {
      active.current = false;
      requests.current++;
    };
  }, []);
  function reset() {
    ticket.current++;
    busy.current = false;
    setReading(false);
    setError(null);
    setStale(false);
    setComplete(false);
    pagesRef.current = [];
    setPages([]);
    setPageIndex(0);
    seenRows.current.clear();
    seenCursors.current.clear();
  }
  function change(next: PackageReviewComparisonSelection) {
    reset();
    setSelection(next);
    try {
      storePackageReviewComparisonSelection(next);
      setStorageError(null);
    } catch {
      setStorageError(
        new Error(
          "对比选择未保存到浏览器，刷新后请重新选择；仍可读取当前选定的两轮对比。",
        ),
      );
    }
  }
  async function read(first = true, all = false) {
    if (
      !active.current ||
      busy.current ||
      !validPackageReviewComparisonSelection(selection)
    )
      return;
    const baseline = first ? undefined : pagesRef.current[0],
      initialCursor = first ? null : pagesRef.current.at(-1)?.next_cursor;
    if (!first && (!initialCursor || stale)) return;
    if (first) reset();
    const request = ++ticket.current,
      query = { bidId, leftId: selection.leftId, rightId: selection.rightId };
    busy.current = true;
    setReading(true);
    setError(null);
    try {
      let more = false;
      do {
        const last = pagesRef.current.at(-1);
        const cursor = first ? null : last?.next_cursor;
        const { data } = await api<unknown>(
          packageReviewComparisonPath(query, cursor),
        );
        const received = await validatePackageReviewComparisonPage(
          data,
          query,
          20,
          baseline,
        );
        if (!active.current || request !== ticket.current) return;
        const collected = new Map(first ? [] : seenRows.current);
        if (
          !first &&
          (received.items.some((row) => collected.has(row.requirement_id)) ||
            (last &&
              received.items[0].requirement_id <=
                last.items[last.items.length - 1].requirement_id) ||
            (received.next_cursor !== null &&
              (received.next_cursor === cursor ||
                seenCursors.current.has(received.next_cursor))))
        )
          throw new Error("对比页发生重复或顺序变化，请重新读取这两轮对比。");
        received.items.forEach((row) => collected.set(row.requirement_id, row));
        const total = packageReviewComparisonTotal(received);
        if (
          collected.size > total ||
          (received.has_more && collected.size >= total)
        )
          throw new Error("对比条数或续页标记不一致，请重新读取。");
        if (!received.has_more)
          await validateCompletePackageReviewComparison(received, [
            ...collected.values(),
          ]);
        if (!active.current || request !== ticket.current) return;
        seenRows.current = collected;
        if (received.next_cursor) seenCursors.current.add(received.next_cursor);
        const updated = first ? [received] : [...pagesRef.current, received];
        pagesRef.current = updated;
        setPages(updated);
        setPageIndex(updated.length - 1);
        setComplete(!received.has_more);
        setStale(false);
        more = received.has_more;
        first = false;
      } while (all && more);
    } catch (failure) {
      if (active.current && request === ticket.current) {
        setError(failure);
        if (
          !first ||
          (failure instanceof ApiError && failure.code === "INVALID_CURSOR")
        )
          setStale(true);
      }
    } finally {
      if (active.current && request === ticket.current) {
        busy.current = false;
        setReading(false);
      }
    }
  }
  function download() {
    const baseline = pagesRef.current[0];
    if (!active.current || busy.current || !complete || stale || !baseline)
      return;
    try {
      const snapshot = {
        export_version: "package-review-comparison-export/1",
        notice:
          "范围核查对比快照；不判定风险已经解决，不构成正式评分或提交许可。",
        comparison: {
          ...packageReviewComparisonHeader(baseline),
          comparison_digest: baseline.comparison_digest,
          items: [...seenRows.current.values()],
        },
      };
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(snapshot, null, 2)], {
          type: "application/json",
        }),
      );
      try {
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = `package-review-comparison-${selection.leftId}-${selection.rightId}.json`;
        anchor.click();
      } finally {
        window.setTimeout(() => URL.revokeObjectURL(url), 0);
      }
    } catch (failure) {
      setError(failure);
    }
  }
  const page = pages[pageIndex],
    available =
      currentRun.operation.state === "succeeded" && !!currentRun.result;
  return (
    <section
      className="package-review-comparison"
      aria-label="两轮范围核查对比"
    >
      <div className="package-review__heading">
        <div>
          <h4>两轮范围核查对比</h4>
          <p>
            选择同一标段中的两条已完成核查，分别比较输入、要求定义、机器判断与人工意见。
          </p>
        </div>
      </div>
      <div className="package-review-comparison__selectors">
        {(["left", "right"] as const).map((side) => {
          const key = side === "left" ? "leftId" : "rightId";
          return (
            <div key={side}>
              <label>
                {side === "left"
                  ? "左侧核查编号（比较基准）"
                  : "右侧核查编号（待比较轮次）"}
                <input
                  value={selection[key]}
                  maxLength={36}
                  spellCheck={false}
                  onChange={(event) =>
                    change({
                      ...selection,
                      [key]: event.target.value.trim().toLowerCase(),
                    })
                  }
                  placeholder="从该轮历史记录复制核查编号"
                />
              </label>
              <button
                type="button"
                className="button secondary"
                disabled={!available}
                onClick={() => change({ ...selection, [key]: currentRun.id })}
              >
                {side === "left" ? "将当前核查设为左侧" : "将当前核查设为右侧"}
              </button>
            </div>
          );
        })}
      </div>
      <p className="muted">
        选择会随当前浏览器会话保留，可先打开一轮历史放入左侧，再打开另一轮放入右侧。读取对比不会启动新的核查。
      </p>
      <div className="package-review__actions">
        <button
          type="button"
          className="button secondary"
          onClick={() =>
            change({
              ...selection,
              leftId: selection.rightId,
              rightId: selection.leftId,
            })
          }
        >
          交换左右两侧
        </button>
        <button
          type="button"
          className="button primary"
          disabled={
            reading || !validPackageReviewComparisonSelection(selection)
          }
          onClick={() => void read()}
        >
          {reading ? "正在读取对比…" : "读取两轮对比"}
        </button>
      </div>
      {pages.length > 0 && (
        <div className="package-review__actions">
          <button
            type="button"
            className="button secondary"
            disabled={reading || stale || complete}
            onClick={() => void read(false, true)}
          >
            读取全部剩余对比
          </button>
          <button
            type="button"
            className="button secondary"
            disabled={reading || stale || !complete}
            onClick={download}
          >
            导出完整对比 JSON
          </button>
          <p className="muted" role="status">
            已读取 {pages.reduce((count, item) => count + item.items.length, 0)}{" "}
            / {packageReviewComparisonTotal(pages[0])} 条。
            导出包含所有对比行与冻结身份；须完整读取并核对摘要，不只导出当前页。
          </p>
        </div>
      )}
      {selection.leftId && selection.leftId === selection.rightId && (
        <p className="package-review__notice">请明确选择两条不同的核查运行。</p>
      )}
      {storageError != null && (
        <p className="muted" role="status">
          {storageError instanceof Error
            ? storageError.message
            : String(storageError)}
        </p>
      )}
      {error != null && (
        <ErrorNotice error={error} onRetry={() => void read()} />
      )}
      {stale && (
        <p className="package-review__notice">
          此次对比不能继续翻页，请重新读取两轮对比。已显示页面属于之前读取的快照。
        </p>
      )}
      {page && (
        <PackageReviewComparisonView
          key={page.comparison_digest}
          memberId={memberId}
          page={page}
          pageIndex={pageIndex}
          complete={complete}
          previousDisabled={pageIndex === 0 || reading}
          nextDisabled={
            reading ||
            stale ||
            (pageIndex === pages.length - 1 && !page.has_more)
          }
          onPrevious={() => setPageIndex(pageIndex - 1)}
          onNext={() =>
            pageIndex + 1 < pages.length
              ? setPageIndex(pageIndex + 1)
              : void read(false)
          }
        />
      )}
    </section>
  );
}
