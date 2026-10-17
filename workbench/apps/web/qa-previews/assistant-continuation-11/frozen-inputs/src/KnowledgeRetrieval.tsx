import { useState } from "react";
import type {
  KnowledgeIndexAccepted,
  KnowledgeIndexPage,
  KnowledgeRetrievalHistory,
  KnowledgeRetrievalHit,
  KnowledgeRetrievalRequest,
  KnowledgeRetrievalResult,
  KnowledgeUnitReference,
  KnowledgeUnitReferenceHistory,
  KnowledgeUnitReferenceRequest,
} from "./contracts";
import { supportsApi } from "./api";
import { Badge, ErrorNotice } from "./components";
import { EvidenceLinks } from "./EvidenceLinks";
import { knowledgePurposes, knowledgeReason } from "./knowledgeNames";
import { knowledgeStorageKey, useKnowledgeInput } from "./knowledgeStorage";
import { ResourceState } from "./ResourceState";
import { useRecordedCommand } from "./useRecordedCommand";
import { useResource } from "./useResource";

function historyLink(bidId: string, traceId: string, citationId?: string) {
  const params = new URLSearchParams({ bid: bidId, trace: traceId });
  if (citationId) params.set("citation", citationId);
  return `/knowledge?${params}`;
}
function references(hit: Pick<KnowledgeRetrievalHit, "provenance">) {
  return hit.provenance.kind === "original_quote"
    ? [hit.provenance.reference]
    : hit.provenance.approved_references;
}
export function KnowledgeRetrieval({
  memberId,
  bidId,
  purpose,
  knowledgeId,
}: {
  memberId: string;
  bidId: string;
  purpose: KnowledgeRetrievalRequest["purpose"];
  knowledgeId?: string | null;
}) {
  const params = new URLSearchParams(window.location.search);
  const [traceId, setTraceId] = useState(params.get("trace") ?? "");
  const [citationId, setCitationId] = useState(params.get("citation") ?? "");
  const [query, setQuery] = useKnowledgeInput(
    knowledgeStorageKey(memberId, bidId) + "rag-query",
    "",
  );
  const [limitKnowledge, setLimitKnowledge] = useState(false);
  const search = useRecordedCommand(`knowledge-search:${memberId}:${bidId}`);
  const trace = useResource<KnowledgeRetrievalHistory>(
    traceId ? `/knowledge-retrievals/${traceId}` : null,
  );
  const available =
    !!bidId && supportsApi("POST", `/bids/${bidId}/knowledge-retrievals`);
  const mismatched = trace.data && trace.data.retrieval.trace_id !== traceId;
  const frozen = trace.data && !mismatched ? trace.data : undefined;
  function accept(value: KnowledgeRetrievalResult) {
    setTraceId(value.trace_id);
    setCitationId("");
    window.history.replaceState({}, "", historyLink(bidId, value.trace_id));
  }
  return (
    <section className="panel knowledge-rag" aria-label="企业知识查证">
      <div className="section-heading">
        <div>
          <h2>按问题查证企业知识</h2>
          <p className="small-note">
            只检索当前项目与用途下可用的知识。摘录仅作参考，不自动创建事实，也不替代全稿评审或评分。
          </p>
        </div>
      </div>
      {!bidId ? (
        <p className="small-empty">
          先选择目标项目，再按具体问题查证。目录关键词查找仍可单独使用。
        </p>
      ) : !available ? (
        <p className="small-empty">此服务版本尚未提供项目知识查证。</p>
      ) : (
        <>
          <form
            className="decision-form"
            onSubmit={(event) => {
              event.preventDefault();
              const request: KnowledgeRetrievalRequest = {
                query: query.trim(),
                purpose,
                limit: 8,
                ...(limitKnowledge && knowledgeId
                  ? { knowledge_ids: [knowledgeId] }
                  : {}),
              };
              void search
                .run<KnowledgeRetrievalResult>(
                  `/bids/${bidId}/knowledge-retrievals`,
                  request,
                  "",
                )
                .then((value) => {
                  if (value) accept(value.data);
                });
            }}
          >
            <label>
              查证问题
              <textarea
                required
                maxLength={10000}
                value={query}
                disabled={search.busy || !!search.pending}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="例如：本项目排水施工可以参考哪些已发布方法？"
              />
            </label>
            <p className="small-note">
              当前用途：{knowledgePurposes[purpose]}
              。不会在输入或刷新时自动检索。
            </p>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={limitKnowledge}
                disabled={!knowledgeId || search.busy || !!search.pending}
                onChange={(event) => setLimitKnowledge(event.target.checked)}
              />
              仅查证当前打开的知识条目（先从目录选择）
            </label>
            <ErrorNotice error={search.error} />
            <button
              className="button primary"
              disabled={search.busy || !!search.pending || !query.trim()}
            >
              {search.busy ? "正在查证…" : "查证企业知识"}
            </button>
          </form>
          {search.pending && !search.busy && (
            <div className="notice warning">
              <p>
                上次查证结果尚未取得，先恢复原请求，避免把另一问题当作重试。
              </p>
              <button
                className="button secondary"
                onClick={() =>
                  void search
                    .retry<KnowledgeRetrievalResult>()
                    .then((value) => {
                      if (value) accept(value.data);
                    })
                }
              >
                恢复原查证结果
              </button>
            </div>
          )}
        </>
      )}
      {traceId && (
        <>
          <div className="section-title">
            <h3>当次实际提供的参考</h3>
            <button className="text-button" onClick={() => void trace.reload()}>
              重新核对当前资格
            </button>
          </div>
          <ResourceState
            {...trace}
            hasData={!!frozen}
            onRetry={() => void trace.reload()}
          />
          {mismatched && (
            <p className="notice error">查证记录身份不一致，未展示其他记录。</p>
          )}
          {frozen && (
            <>
              <p className="small-note">
                查证于 {new Date(frozen.evaluated_at).toLocaleString("zh-CN")} ·{" "}
                <a href={historyLink(bidId, traceId)}>打开此查证的固定链接</a>
                。保留当时内容，当前资格另列。
              </p>
              {supportsApi("GET", "/assistant/sources") && (
                <p>
                  <a
                    href={`/assistant?${new URLSearchParams({ bid: bidId, trace: traceId })}`}
                  >
                    带此查证进入项目助手
                  </a>
                </p>
              )}
              <CurrentReasons reasons={frozen.current_reasons} />
              {frozen.retrieval.gaps.map((gap, i) => (
                <p className="notice warning" key={i}>
                  {gap}
                </p>
              ))}
              {frozen.retrieval.coverage === "unavailable" && (
                <p className="notice warning">
                  本次查证不可用，未提供可用参考。
                </p>
              )}
              {!frozen.retrieval.hits.length && (
                <p className="small-empty">
                  本次没有返回有资格的参考。可调整问题，或在知识条目中核对发布范围与查证索引；不会用失效知识补足结果。
                </p>
              )}
              {frozen.retrieval.hits.map((hit) => (
                <KnowledgeHit
                  key={`${traceId}:${hit.unit_id}`}
                  hit={hit}
                  traceId={traceId}
                  bidId={bidId}
                  memberId={memberId}
                  blocked={
                    !!frozen.current_reasons.length ||
                    trace.loading ||
                    !!trace.error
                  }
                  onReferenced={(value) => {
                    setCitationId(value.citation_id);
                    window.history.replaceState(
                      {},
                      "",
                      historyLink(bidId, traceId, value.citation_id),
                    );
                  }}
                />
              ))}
              <details className="identity-details">
                <summary>查证范围与方法详情</summary>
                <p>此路径仅为参考；覆盖：{frozen.retrieval.coverage}。</p>
                <p>实际检索路径：{frozen.retrieval.route.join("、")}</p>
                <p>
                  记录：{traceId} · 策略：{frozen.retrieval.policy_digest}
                </p>
              </details>
            </>
          )}
        </>
      )}
      {citationId && (
        <KnowledgeCitation
          key={citationId}
          citationId={citationId}
          bidId={bidId}
        />
      )}
    </section>
  );
}

function CurrentReasons({ reasons }: { reasons: string[] }) {
  return reasons.length ? (
    <div className="notice warning">
      <div>
        <strong>当前不能据此新增选用；当时内容仍保留</strong>
        {reasons.map((reason, i) => (
          <p key={i}>{knowledgeReason(reason)}</p>
        ))}
        <p>请使用当前项目与来源重新查证，不直接重用旧结果。</p>
      </div>
    </div>
  ) : (
    <p className="small-note">
      当前读取未报告失效原因；新增引用时服务器仍会重新核对完整范围。
    </p>
  );
}
function KnowledgeHit({
  hit,
  traceId,
  bidId,
  memberId,
  blocked,
  onReferenced,
}: {
  hit: KnowledgeRetrievalHit;
  traceId: string;
  bidId: string;
  memberId: string;
  blocked: boolean;
  onReferenced: (value: KnowledgeUnitReference) => void;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useKnowledgeInput(
    knowledgeStorageKey(memberId, traceId) + hit.unit_id,
    "",
  );
  const command = useRecordedCommand(
    `knowledge-unit:${memberId}:${traceId}:${hit.unit_id}`,
  );
  const refs = references(hit);
  const receive = (value: KnowledgeUnitReference) => {
    if (
      value.trace_id !== traceId ||
      value.unit_id !== hit.unit_id ||
      value.bid_id !== bidId
    )
      throw new Error("引用身份不一致，请从服务器记录重新核对。");
    setOpen(false);
    onReferenced(value);
  };
  const [validationError, setValidationError] = useState<unknown>(null);
  function finish(value: KnowledgeUnitReference | undefined) {
    if (value) {
      try {
        receive(value);
      } catch (error) {
        setValidationError(error);
      }
    }
  }
  return (
    <article className="knowledge-hit">
      <div className="section-title">
        <h3>参考 {hit.rank}</h3>
        <Badge>
          {hit.unit_kind === "knowledge_text"
            ? "知识整理内容 · 派生参考"
            : "获准引用的原文摘录"}
        </Badge>
      </div>
      <blockquote>{hit.text}</blockquote>
      <p className="small-note">
        {hit.unit_kind === "knowledge_text"
          ? "以下是此知识整理内容的批准来源，不表示整段文字逐字出自任一原页。"
          : "摘录来自获准原文；完整范围请打开原页核对。"}
      </p>
      {refs.map((ref) => (
        <p className="small-note" key={ref.evidence_id}>
          批准摘录 · 物理页{ref.physical_page}：{ref.excerpt}
        </p>
      ))}
      <EvidenceLinks
        ids={refs.map((ref) => ref.evidence_id)}
        label="查看批准来源原页"
      />
      <a href={`/knowledge?item=${encodeURIComponent(hit.knowledge_id)}`}>
        查看知识条目与版本
      </a>
      <button
        type="button"
        className="text-button"
        disabled={blocked || !bidId}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        登记为本项目参考
      </button>
      {open && (
        <form
          className="decision-form"
          onSubmit={(event) => {
            event.preventDefault();
            const body: KnowledgeUnitReferenceRequest = {
              unit_id: hit.unit_id,
              quote: hit.text,
              target_kind: "project",
              target_object_id: bidId,
              applicability_reason: reason.trim(),
            };
            void command
              .run<KnowledgeUnitReference>(
                `/knowledge-retrievals/${traceId}/references`,
                body,
                "",
              )
              .then((value) => finish(value?.data));
          }}
        >
          <p>仅登记到当前项目参考，不创建工程事实、不确认规则、不执行评分。</p>
          <label>
            本次用途与适用理由
            <textarea
              required
              maxLength={4000}
              value={reason}
              disabled={command.busy || !!command.pending}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
          <button
            className="button secondary"
            disabled={
              blocked || command.busy || !!command.pending || !reason.trim()
            }
          >
            保存项目参考
          </button>
        </form>
      )}
      <ErrorNotice error={command.error ?? validationError} />
      {command.pending && !command.busy && (
        <button
          className="button secondary"
          onClick={() =>
            void command
              .retry<KnowledgeUnitReference>()
              .then((value) => finish(value?.data))
          }
        >
          恢复原引用登记结果
        </button>
      )}
    </article>
  );
}

export function KnowledgeCitation({
  citationId,
  bidId,
}: {
  citationId: string;
  bidId: string;
}) {
  const history = useResource<KnowledgeUnitReferenceHistory>(
    `/knowledge-unit-references/${citationId}`,
  );
  const item = history.data?.reference;
  const valid = item?.citation_id === citationId && item.bid_id === bidId;
  return (
    <section className="knowledge-citation">
      <h3>已登记参考的历史与当前资格</h3>
      <ResourceState
        {...history}
        hasData={!!item}
        onRetry={() => void history.reload()}
      />
      {item && !valid && (
        <p className="notice error">
          参考与所选项目身份不一致，未将其当作本项目引用。
        </p>
      )}
      {valid && (
        <>
          <Badge>项目参考 · 不创建事实</Badge>
          <blockquote>{item.quote}</blockquote>
          <p>{item.applicability_reason}</p>
          <p className="small-note">
            登记时主体：{item.project_context.identity.bidder_name} · 工程：
            {item.project_context.identity.engineering_title}
            。固定内容不会被当前版本覆盖。
          </p>
          <CurrentReasons reasons={history.data!.current_reasons} />
          <EvidenceLinks
            ids={references(item).map((ref) => ref.evidence_id)}
            label="追溯当时批准来源原页"
          />
          <a href={historyLink(bidId, item.trace_id, item.citation_id)}>
            打开此引用的固定链接
          </a>
        </>
      )}
    </section>
  );
}

export function KnowledgeIndex({
  id,
  versionId,
  memberId,
  published,
}: {
  id: string;
  versionId: string;
  memberId: string;
  published: boolean;
}) {
  const [open, setOpen] = useState(false);
  const indexes = useResource<KnowledgeIndexPage>(
    open ? `/knowledge/${id}/indexes` : null,
    open ? 5000 : 0,
  );
  const command = useRecordedCommand(`knowledge-index:${memberId}:${id}`);
  return (
    <div className="knowledge-index">
      <button
        className="text-button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        查看知识查证索引
      </button>
      {open && (
        <>
          <ResourceState
            {...indexes}
            hasData={!!indexes.data}
            onRetry={() => void indexes.reload()}
          />
          {indexes.data?.items.map((item) => (
            <p key={item.index_id}>
              <Badge>
                {
                  {
                    queued: "等待建立",
                    ready: "已建立",
                    failed: "建立失败",
                    superseded: "已由新索引替代",
                  }[item.state]
                }
              </Badge>{" "}
              {item.knowledge_version_id === versionId
                ? "此知识版本"
                : "其他历史版本"}{" "}
              · {item.published_unit_count}/{item.expected_unit_count ?? "未知"}
              个单元{item.current_ready ? " · 当前可供查证" : ""}
              {item.error_code ? ` · ${item.error_code}` : ""}
            </p>
          ))}
          {indexes.data?.items.length === 0 && (
            <p>尚无查证索引。发布与适用范围仍需单独核对。</p>
          )}
          <ErrorNotice error={command.error} />
          <button
            className="button secondary"
            disabled={
              !published ||
              command.busy ||
              !!command.pending ||
              indexes.data?.items.some(
                (item) =>
                  item.knowledge_version_id === versionId &&
                  item.state === "queued",
              )
            }
            onClick={() =>
              void command
                .run<KnowledgeIndexAccepted>(
                  `/knowledge/${id}/indexes`,
                  { knowledge_version_id: versionId },
                  "",
                )
                .then((value) => {
                  if (value) void indexes.reload();
                })
            }
          >
            为此知识版本建立查证索引
          </button>
          {command.pending && !command.busy && (
            <button
              className="text-button"
              onClick={() =>
                void command.retry<KnowledgeIndexAccepted>().then((value) => {
                  if (value) void indexes.reload();
                })
              }
            >
              恢复原索引受理结果
            </button>
          )}
          <p className="small-note">
            {!published && "此版本尚非当前发布版本，不能为其新增索引。"}
            本地建立索引不代表发布、项目适用或正式评分资格。
          </p>
        </>
      )}
    </div>
  );
}
