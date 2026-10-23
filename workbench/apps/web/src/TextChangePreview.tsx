import { useMemo, useState } from "react";
import { textDifference } from "./textDifference";
import "./TextChangePreview.css";

export function TextChangePreview({
  before,
  after,
  beforeLabel = "修改前",
  afterLabel = "拟修改后 · 尚未应用",
}: {
  before: string;
  after: string;
  beforeLabel?: string;
  afterLabel?: string;
}) {
  const difference = useMemo(
    () => textDifference(before, after),
    [before, after],
  );
  const [mobileSide, setMobileSide] = useState<"before" | "after">("after");
  return (
    <div className="text-change-preview" data-side={mobileSide}>
      <p className="text-change-preview__legend">
        <span>
          <span className="text-change-preview__removed">删除或替换</span>{" "}
          标示原文变化，
        </span>
        <span>
          <span className="text-change-preview__added">新增</span>{" "}
          标示拟稿变化。
        </span>
        {before === after && <span>两侧文字一致。</span>}
      </p>
      {difference.blockComparison && (
        <p>变化较多，已按区块标示；两侧保留全文。</p>
      )}
      <div
        className="text-change-preview__mobile-switch"
        role="group"
        aria-label="选择对照稿件"
      >
        <button
          type="button"
          className="button secondary"
          aria-pressed={mobileSide === "before"}
          onClick={() => setMobileSide("before")}
        >
          修改前
        </button>
        <button
          type="button"
          className="button secondary"
          aria-pressed={mobileSide === "after"}
          onClick={() => setMobileSide("after")}
        >
          拟修改后
        </button>
      </div>
      <div className="text-change-preview__panes">
        {(["before", "after"] as const).map((side) => (
          <section
            key={side}
            className={`text-change-preview__${side}`}
            aria-label={side === "before" ? beforeLabel : afterLabel}
          >
            <h4>{side === "before" ? beforeLabel : afterLabel}</h4>
            <pre
              tabIndex={0}
              aria-label={`${side === "before" ? "修改前" : "拟修改后"}全文`}
            >
              {difference.changes
                .filter(
                  (change) =>
                    change.kind !== (side === "before" ? "added" : "removed"),
                )
                .map((change, index) =>
                  change.kind === "equal" ? (
                    change.text
                  ) : (
                    <mark
                      key={index}
                      className={`text-change-preview__${change.kind}`}
                    >
                      {change.text}
                    </mark>
                  ),
                )}
            </pre>
          </section>
        ))}
      </div>
    </div>
  );
}
