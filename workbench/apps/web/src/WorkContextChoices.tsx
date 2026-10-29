import { useCallback } from "react";
import type { WorkContextChoicePage } from "./contracts";
import { Badge, ErrorNotice, LoadingSkeleton } from "./components";
import { contextOperationNames } from "./workContextAuthoringProtocol";
import {
  contextChoiceTarget,
  validateWorkContextChoices,
} from "./workContextDirectoryProtocol";
import type {
  WorkContextKind,
  WorkContextTarget,
} from "./workContextNavigation";
import { useWorkContextDirectory } from "./useWorkContextDirectory";

const statusNames = {
  ...contextOperationNames,
  saved: "已保存",
  standard: "标准登记",
  offline_fact: "线下事实补录",
};
export function WorkContextChoices(p: {
  bidId: string;
  kind: WorkContextKind;
  selected: WorkContextTarget | null;
  onSelect: (target: WorkContextTarget) => void;
}) {
  const validate = useCallback(
    (v: unknown) => validateWorkContextChoices(v, p.bidId, p.kind),
    [p.bidId, p.kind],
  );
  const { page, items, error, busy, load } = useWorkContextDirectory<
    WorkContextChoicePage["items"][number],
    WorkContextChoicePage
  >(`/bids/${p.bidId}/work-contexts/choices?kind=${p.kind}&limit=20`, validate);
  return (
    <section className="panel work-context-choices" aria-label="阶段记录目录">
      <div className="section-heading">
        <div>
          <h2>选择一条历史记录</h2>
          <p className="muted">
            按记录时间列出。选择后核对完整身份，再读取该条记录的正文或结果。
          </p>
        </div>
        <button
          type="button"
          className="button secondary"
          disabled={busy}
          onClick={() => void load()}
        >
          重读目录
        </button>
      </div>
      {busy && !page && (
        <LoadingSkeleton text="正在读取完整阶段目录…" rows={3} />
      )}
      {error != null && (
        <ErrorNotice error={error} onRetry={() => void load()} />
      )}
      {error != null && page && (
        <p className="notice warning">
          目录未能更新，下面保留上次读取的记录；再次选择仍会核对固定身份。
        </p>
      )}
      {page && (
        <p className="small-note">
          已列出 {items.length} / {page.total}{" "}
          条。记录存在不表示当前可用于生成、核查或提交。
        </p>
      )}
      {page && !items.length && (
        <p className="notice neutral">
          此阶段尚无已保存记录。可先在章节编制、整包核查或实交工作面完成对应操作，再回到这里明确选择。
        </p>
      )}
      <ul className="work-context-choice-list">
        {items.map((item) => {
          const chosen =
            p.selected?.id === item.id &&
            p.selected.selectionDigest === item.selection_digest;
          return (
            <li
              key={`${item.id}:${item.selection_digest}`}
              data-selected={chosen}
            >
              <div>
                <strong>{item.label}</strong>
                <time dateTime={item.created_at}>
                  {new Date(item.created_at).toLocaleString("zh-CN", {
                    timeZone: "Asia/Shanghai",
                    hour12: false,
                  })}
                  （北京时间）
                </time>
                <Badge tone="neutral">{statusNames[item.status]}</Badge>
              </div>
              <button
                type="button"
                className={chosen ? "button secondary" : "button"}
                aria-pressed={chosen}
                onClick={() => p.onSelect(contextChoiceTarget(item))}
              >
                {chosen ? "已选此记录" : "选择此记录"}
              </button>
              <details>
                <summary>记录固定身份</summary>
                <p className="digest">{item.id}</p>
                <p className="digest">{item.selection_digest}</p>
              </details>
            </li>
          );
        })}
      </ul>
      {page?.has_more && (
        <button
          type="button"
          className="button secondary"
          disabled={busy}
          onClick={() => void load(true)}
        >
          {busy ? "正在读取…" : "显示更多记录"}
        </button>
      )}
    </section>
  );
}
