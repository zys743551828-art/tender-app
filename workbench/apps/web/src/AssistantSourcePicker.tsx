import { useState } from "react";
import type { AssistantSourcePage, Bid } from "./contracts";
import type { SelectedAssistantSource } from "./assistantState";
import {
  selectableSource,
  sourceIdentity,
  sourceKinds,
} from "./assistantState";
import { AssistantSourceDetails } from "./AssistantSourceDetails";
import { useBidChoices } from "./useBidChoices";
import { useResource } from "./useResource";
import { ResourceState } from "./ResourceState";
import { ErrorNotice } from "./components";

export function AssistantSourcePicker({
  bidId,
  selected,
  onChange,
  disabled,
  traceId,
}: {
  bidId: string | null;
  selected: SelectedAssistantSource[];
  onChange: (sources: SelectedAssistantSource[]) => void;
  disabled: boolean;
  traceId?: string | null;
}) {
  const bids = useBidChoices();
  const [sourceBid, setSourceBid] = useState(bidId ?? "");
  const [kind, setKind] = useState<keyof typeof sourceKinds>("document");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const project = useResource<Bid>(sourceBid ? `/bids/${sourceBid}` : null);
  const params = new URLSearchParams({ kind });
  if (sourceBid) params.set("bid_id", sourceBid);
  if (kind === "project" && project.data?.id === sourceBid)
    params.set("q", project.data.title);
  else if (search) params.set("q", search);
  if (kind === "document") params.set("physical_page", String(page));
  if (kind === "knowledge_unit" && traceId) params.set("trace_id", traceId);
  const available = !!sourceBid && (kind !== "knowledge_unit" || !!traceId);
  const choices = useResource<AssistantSourcePage>(
    available ? `/assistant/sources?${params}` : null,
  );
  const observed =
    !!choices.data &&
    !choices.loading &&
    !choices.error &&
    !choices.unavailable;
  const selectedInScope = selected.filter(
    (source) => !bidId || source.bidId === bidId,
  );
  const projectTitle = (id: string | null) =>
    project.data?.id === id
      ? project.data.title
      : bids.items.find((item) => item.id === id)?.title;
  return (
    <section className="assistant-source-picker" aria-label="可信来源选择">
      <h3>选择这条消息的可信来源</h3>
      <p className="assistant-source-basis-note">
        只绑定服务器给出的来源与版本。章节为已保存版本，未保存编辑不在此上下文；来源文字不能授权执行操作。
      </p>
      {!!selectedInScope.length && (
        <section
          className="assistant-source-selected-details"
          aria-label="已选来源版本核对"
        >
          <h4>已选来源及固定版本（{selectedInScope.length}）</h4>
          {selectedInScope.map((source) => {
            const current = observed
              ? choices.data?.items.find(
                  (item) =>
                    item.bid_id === source.bidId &&
                    item.reference &&
                    sourceIdentity(item.reference) ===
                      sourceIdentity(source.reference),
                )
              : undefined;
            const availability = !current
              ? "unverified"
              : current.reference?.version !== source.reference.version
                ? "changed"
                : !current.available
                  ? "unavailable"
                  : "available";
            return (
              <AssistantSourceDetails
                key={`${source.bidId}:${sourceIdentity(source.reference)}:${source.reference.version}`}
                title={source.title}
                reference={source.reference}
                kind={source.reference.kind}
                bidId={source.bidId}
                projectTitle={projectTitle(source.bidId)}
                availability={availability}
                reasons={current?.reasons}
                currentVersion={
                  availability === "changed"
                    ? current?.reference?.version
                    : undefined
                }
                summary={`核对已选来源：${source.title}${source.reference.physical_page ? ` · 物理页 ${source.reference.physical_page}` : ""}`}
              />
            );
          })}
        </section>
      )}
      <fieldset disabled={disabled}>
        {!bidId && (
          <>
            <label>
              来源所属项目
              <select
                aria-label="来源所属项目"
                value={sourceBid}
                onChange={(event) => setSourceBid(event.target.value)}
              >
                <option value="">先明确项目范围</option>
                {bids.items.map((bid) => (
                  <option key={bid.id} value={bid.id}>
                    {bid.title}
                  </option>
                ))}
              </select>
            </label>
            <ResourceState
              {...bids}
              hasData={!!bids.data}
              onRetry={() => void bids.reload()}
            />
            <ErrorNotice error={bids.moreError} />
            {bids.hasMore && (
              <button
                type="button"
                className="text-button"
                disabled={bids.moreBusy}
                onClick={() => void bids.loadMore()}
              >
                加载更多来源项目
              </button>
            )}
          </>
        )}
        <label>
          来源类型
          <select
            aria-label="助手来源类型"
            value={kind}
            onChange={(event) =>
              setKind(event.target.value as keyof typeof sourceKinds)
            }
          >
            {Object.entries(sourceKinds).map(([key, title]) => (
              <option key={key} value={key}>
                {title}
              </option>
            ))}
          </select>
        </label>
        {kind === "document" && (
          <label>
            原件物理页
            <input
              type="number"
              min={1}
              value={page}
              onChange={(event) =>
                setPage(Math.max(1, Number(event.target.value) || 1))
              }
            />
          </label>
        )}
        {kind === "knowledge_unit" && !traceId && (
          <p className="notice neutral">
            先从
            <a
              href={`/knowledge${sourceBid ? `?bid=${encodeURIComponent(sourceBid)}` : ""}`}
            >
              企业知识查证
            </a>
            取得实际参考，再用“带此查证进入项目助手”打开；不手填检索编号。
          </p>
        )}
        <div className="assistant-source-search">
          <label>
            查找来源名称
            <input
              maxLength={200}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <button
            type="button"
            className="button secondary"
            onClick={() => {
              if (search === query.trim()) void choices.reload();
              else setSearch(query.trim());
            }}
          >
            查找可信来源
          </button>
        </div>
        <ResourceState
          {...choices}
          hasData={!!choices.data}
          onRetry={() => void choices.reload()}
        />
        {choices.data && (
          <>
            <p className="small-note">
              {choices.data.notice}
              当前返回范围不完整；没有列出不代表资料不存在。
            </p>
            {choices.data.items
              .filter((item) => item.bid_id === sourceBid)
              .map((item, index) => {
                const reference = item.reference;
                const existing = reference
                  ? selected.find(
                      (source) =>
                        sourceIdentity(source.reference) ===
                        sourceIdentity(reference),
                    )
                  : undefined;
                const checked =
                  !!existing &&
                  existing.reference.version === reference?.version;
                return (
                  <div
                    key={`${reference ? sourceIdentity(reference) : item.title}:${index}`}
                    className="assistant-source-option"
                  >
                    <label className="evidence-select-item">
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={
                          !observed ||
                          !selectableSource(item, sourceBid) ||
                          (!checked && selected.length >= 30)
                        }
                        onChange={(event) => {
                          if (!reference) return;
                          const others = selected.filter(
                            (source) =>
                              sourceIdentity(source.reference) !==
                              sourceIdentity(reference),
                          );
                          onChange(
                            event.target.checked
                              ? [
                                  ...others,
                                  {
                                    reference,
                                    title: item.title,
                                    bidId: item.bid_id,
                                  },
                                ]
                              : others,
                          );
                        }}
                      />
                      <span>
                        {item.title}
                        {reference?.physical_page
                          ? ` · 物理页${reference.physical_page}`
                          : ""}
                        {existing && !checked
                          ? " · 选择将明确换用当前依据"
                          : ""}
                        {!item.available && (
                          <span className="assistant-source-option__unavailable">
                            {item.reasons.includes("SOURCE_WITHDRAWN")
                              ? "来源已撤回，当前不可选择。"
                              : "当前不可选择，请展开来源详情核对原因。"}
                          </span>
                        )}
                      </span>
                    </label>
                    <AssistantSourceDetails
                      title={item.title}
                      reference={reference}
                      kind={reference?.kind ?? kind}
                      bidId={item.bid_id}
                      projectTitle={projectTitle(item.bid_id)}
                      availability={
                        !observed
                          ? "unverified"
                          : item.available
                            ? "available"
                            : "unavailable"
                      }
                      reasons={item.reasons}
                    />
                  </div>
                );
              })}
            {!choices.data.items.some(
              (item) => !bidId || item.bid_id === bidId,
            ) && (
              <p className="small-empty">
                当前范围没有可选择来源。可调整名称、物理页或核对资料处理状态。
              </p>
            )}
          </>
        )}
      </fieldset>
    </section>
  );
}
