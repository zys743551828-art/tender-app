import { useState } from "react";
import { api, ApiError } from "./api";
import type {
  Bid,
  BiddingCompanyPage,
  KnowledgeCandidate,
  KnowledgeImpact,
  KnowledgePage,
  KnowledgeReference,
  KnowledgeReferenceHistory,
  KnowledgeReferenceRequest,
  KnowledgeVersionPage,
  KnowledgeView,
  MaterialView,
} from "./contracts";
import { Badge, ErrorNotice } from "./components";
import { EvidenceLinks } from "./EvidenceLinks";
import {
  knowledgeCategories,
  knowledgePurposes,
  knowledgeStates,
  knowledgeReason,
} from "./knowledgeNames";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import { useCommand } from "./useCommand";
import { KnowledgeRetrieval, KnowledgeIndex } from "./KnowledgeRetrieval";
import { supportsApi } from "./api";
import { KnowledgeVersionEditor } from "./KnowledgeVersionEditor";
import { useBidChoices } from "./useBidChoices";
import {
  useKnowledgeInput,
  knowledgeStorageKey,
  discardKnowledgeForm,
} from "./knowledgeStorage";

export function Knowledge({
  memberId,
  selectedId,
  onSelect,
}: {
  memberId: string;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [bidId, setBidId] = useState(
    () => new URLSearchParams(window.location.search).get("bid") ?? "",
  );
  const [purpose, setPurpose] =
    useState<KnowledgeReferenceRequest["purpose"]>("assist");
  const [state, setState] = useState<"all" | "published">("published");
  const selected = selectedId;
  const [create, setCreate] = useState(false);
  const bids = useBidChoices();
  const bidResource = useResource<Bid>(bidId ? `/bids/${bidId}` : null);
  const currentBid =
    bidResource.data?.id === bidId ? bidResource.data : undefined;
  const params = new URLSearchParams({ state, purpose });
  if (query) params.set("q", query);
  if (bidId) params.set("bid_id", bidId);
  const path = `/knowledge?${params}`;
  const entries = useResource<KnowledgePage>(path);
  const [more, setMore] = useState<{ path: string; page: KnowledgePage }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const pages = more
    .filter((page) => page.path === path)
    .map((page) => page.page);
  const last = pages.at(-1) ?? entries.data;
  const items = [
    ...new Map(
      [
        ...(entries.data?.items ?? []),
        ...pages.flatMap((page) => page.items),
      ].map((item) => [item.id, item]),
    ).values(),
  ];
  async function next() {
    if (!last?.next_cursor || busy) return;
    setBusy(true);
    setError(null);
    try {
      const { data } = await api<KnowledgePage>(
        `${path}&after=${encodeURIComponent(last.next_cursor)}`,
      );
      setMore((old) => [...old, { path, page: data }]);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page-content knowledge-page">
      <header className="page-heading">
        <div>
          <span className="eyebrow">有来源、有范围的可靠复用</span>
          <h1>企业知识</h1>
          <p className="muted">
            维护可核查知识，选用时重新核对项目适用性。知识参考不会自动变成工程事实。
          </p>
        </div>
        <button
          className="button secondary"
          onClick={() => setCreate((old) => !old)}
        >
          {create ? "收起候选表单" : "建立知识候选"}
        </button>
      </header>
      <section className="panel knowledge-search">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setQuery(input.trim());
            setMore([]);
          }}
        >
          <label>
            关键词
            <input
              value={input}
              maxLength={200}
              onChange={(event) => setInput(event.target.value)}
              placeholder="在知识原文中查找"
            />
          </label>
          <label>
            查阅范围
            <select
              aria-label="知识查阅范围"
              value={state}
              onChange={(event) =>
                setState(event.target.value as "all" | "published")
              }
            >
              <option value="published">当前发布目录</option>
              <option value="all">全部维护记录</option>
            </select>
          </label>
          <label>
            目标项目
            <select
              aria-label="知识目标项目"
              value={bidId}
              onChange={(event) => {
                const params = new URLSearchParams(window.location.search);
                params.delete("trace");
                params.delete("citation");
                if (event.target.value) params.set("bid", event.target.value);
                else params.delete("bid");
                window.history.replaceState({}, "", `/knowledge?${params}`);
                setBidId(event.target.value);
              }}
            >
              <option value="">仅查阅目录</option>
              {bids.items.map((bid) => (
                <option key={bid.id} value={bid.id}>
                  {bid.title}
                </option>
              ))}
            </select>
          </label>
          <label>
            用途
            <select
              aria-label="知识用途"
              value={purpose}
              onChange={(event) =>
                setPurpose(
                  event.target.value as KnowledgeReferenceRequest["purpose"],
                )
              }
            >
              {Object.entries(knowledgePurposes).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <button className="button secondary">查找知识</button>
        </form>
        <p className="small-note">
          当前按原文关键词查找。未选项目只是目录查阅，不表示适用于任意工程；选项目后由服务器核对主体、地区、工程类型、事实前提、时间和来源。
        </p>
        <ResourceState
          {...bids}
          hasData={!!bids.data}
          onRetry={() => void bids.reload()}
        />
        {bids.hasMore && (
          <button
            className="text-button"
            disabled={bids.moreBusy}
            onClick={() => void bids.loadMore()}
          >
            {bids.moreBusy ? "正在读取项目…" : "加载更多项目供选择"}
          </button>
        )}
        <ErrorNotice
          error={bids.moreError}
          onRetry={() => void bids.loadMore()}
        />
        {bidId && (
          <ResourceState
            {...bidResource}
            hasData={!!currentBid}
            onRetry={() => void bidResource.reload()}
          />
        )}
        {currentBid && currentBid.identity?.binding_status !== "confirmed" && (
          <div className="notice warning">
            该项目主体与工程身份尚未确认，不能把已有编号视为适用性批准。可以查阅目录，新增选用仍须服务端核对。
            <a href={`/bids/${currentBid.id}/settings`}>确认本项目投标主体</a>
          </div>
        )}
      </section>
      {supportsApi(
        "POST",
        `/bids/${bidId || "project"}/knowledge-retrievals`,
      ) && (
        <KnowledgeRetrieval
          key={`${memberId}:${bidId}`}
          memberId={memberId}
          bidId={bidId}
          knowledgeId={selected}
          purpose={purpose}
        />
      )}
      {create && (
        <CandidateForm
          memberId={memberId}
          bids={bids.items ?? []}
          onCreated={(id) => {
            setCreate(false);
            onSelect(id);
            void entries.reload();
          }}
        />
      )}
      <div className="knowledge-columns">
        <section className="panel knowledge-results">
          <h2>知识目录</h2>
          <ResourceState
            {...entries}
            hasData={!!entries.data}
            onRetry={() => void entries.reload()}
          />
          <ErrorNotice error={error} />
          {entries.data && !items.length && (
            <p className="small-empty">
              {bidId
                ? "当前项目与用途下没有可用的匹配知识；不会用失效内容补足结果。"
                : "当前查找条件下没有可读知识。可以调整关键词或建立有来源的候选。"}
            </p>
          )}
          {items.map((item) => (
            <button
              key={item.id}
              className={`knowledge-link${selected === item.id ? " selected" : ""}`}
              onClick={() => onSelect(item.id)}
            >
              <strong>{item.title}</strong>
              <span>
                <Badge
                  tone={item.workflow === "published" ? "success" : "warning"}
                >
                  {knowledgeStates[item.workflow]}
                </Badge>{" "}
                版本 {item.version_no}
              </span>
              <small>{item.scope}</small>
            </button>
          ))}
          {last?.has_more && last.next_cursor && (
            <button
              className="text-button"
              disabled={busy}
              onClick={() => void next()}
            >
              {busy ? "正在读取更多知识…" : "加载更多知识"}
            </button>
          )}
        </section>
        {selected && (
          <KnowledgeDetails
            key={selected}
            id={selected}
            memberId={memberId}
            bid={currentBid}
            purpose={purpose}
            onChanged={() => void entries.reload()}
          />
        )}
      </div>
    </div>
  );
}

function CandidateForm({
  memberId,
  bids,
  onCreated,
}: {
  memberId: string;
  bids: Bid[];
  onCreated: (id: string) => void;
}) {
  const formKey = knowledgeStorageKey(memberId, "candidate");
  const [title, setTitle] = useKnowledgeInput(formKey + "title", "");
  const [content, setContent] = useKnowledgeInput(formKey + "content", "");
  const [scope, setScope] = useKnowledgeInput(formKey + "scope", "");
  const [bidId, setBidId] = useKnowledgeInput(formKey + "bidId", "");
  const [sources, setSources] = useKnowledgeInput<string[]>(
    formKey + "sources",
    [],
  );
  const materials = useResource<MaterialView>(
    bidId ? `/bids/${bidId}/materials` : null,
  );
  const command = useCommand(`knowledge-candidate:${memberId}`);
  async function save() {
    const body: KnowledgeCandidate = {
      title: title.trim(),
      content: content.trim(),
      scope: scope.trim(),
      source_version_ids: sources,
    };
    const result = await command.run<KnowledgeView>("/knowledge", body, null);
    if (result) {
      discardKnowledgeForm(formKey);
      onCreated(result.data.id);
    }
  }
  return (
    <section className="panel knowledge-candidate">
      <h2>建立待完善候选</h2>
      <p className="small-note">
        候选不等于已发布。主体、地区、类型、期限和用途需在独立版本中明确；发布也不会创建项目事实或训练资格。本页输入在此浏览器会话内按登录成员保留，收起后可继续编辑。
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <fieldset disabled={command.busy}>
          <legend>候选内容与原件</legend>
          <label>
            候选标题
            <input
              required
              maxLength={200}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
          <label>
            知识正文
            <textarea
              required
              rows={6}
              maxLength={100000}
              value={content}
              onChange={(event) => setContent(event.target.value)}
            />
          </label>
          <label>
            拟适用范围说明
            <textarea
              required
              maxLength={2000}
              value={scope}
              onChange={(event) => setScope(event.target.value)}
            />
          </label>
          <label>
            选择来源项目
            <select
              aria-label="候选来源项目"
              value={bidId}
              onChange={(event) => setBidId(event.target.value)}
            >
              <option value="">选择真实项目</option>
              {bids.map((bid) => (
                <option key={bid.id} value={bid.id}>
                  {bid.title}
                </option>
              ))}
            </select>
          </label>
          <ResourceState
            {...materials}
            hasData={!!materials.data}
            onRetry={() => void materials.reload()}
          />
          <fieldset>
            <legend>选择已入库原件的当前版本</legend>
            {materials.data?.documents.map((document) => (
              <label className="checkbox-label" key={document.id}>
                <input
                  type="checkbox"
                  checked={sources.includes(document.id)}
                  onChange={(event) =>
                    setSources((old) =>
                      event.target.checked
                        ? [...new Set([...old, document.id])]
                        : old.filter((id) => id !== document.id),
                    )
                  }
                />
                {document.filename} · 版本 {document.file_revision}
              </label>
            ))}
            <p className="small-note">
              已选 {sources.length}{" "}
              份。原件选择不等于逐字出处核验，也不等于已确认公司事实。
            </p>
          </fieldset>
        </fieldset>
        <ErrorNotice error={command.error} />
        <button
          className="button primary"
          disabled={
            command.busy ||
            !title.trim() ||
            !content.trim() ||
            !scope.trim() ||
            !sources.length
          }
        >
          {command.busy ? "正在保留候选及来源…" : "保存待完善候选"}
        </button>
      </form>
    </section>
  );
}

function KnowledgeDetails({
  id,
  memberId,
  bid,
  purpose,
  onChanged,
}: {
  id: string;
  memberId: string;
  bid: Bid | undefined;
  purpose: KnowledgeReferenceRequest["purpose"];
  onChanged: () => void;
}) {
  const current = useResource<KnowledgeView>(`/knowledge/${id}`);
  const companies = useResource<BiddingCompanyPage>(
    "/identity/bidders?limit=100",
  );
  const publishedId = current.data?.published_version_id;
  const published = useResource<KnowledgeView>(
    publishedId && publishedId !== current.data?.version_id
      ? `/knowledge/${id}/versions/${publishedId}`
      : null,
  );
  const publishedView =
    publishedId === current.data?.version_id
      ? current.data
      : published.data &&
          published.data.version_id === publishedId &&
          published.data.id === id
        ? published.data
        : undefined;
  const [versionId, setVersionId] = useState<string | null>(null);
  const version = useResource<KnowledgeView>(
    versionId ? `/knowledge/${id}/versions/${versionId}` : null,
  );
  const view = versionId ? version.data : current.data;
  const [historyOpen, setHistoryOpen] = useState(false);
  const [citationId, setCitationId] = useState<string | null>(null);
  const [impactOpen, setImpactOpen] = useState(false);
  const history = useResource<KnowledgeVersionPage>(
    historyOpen ? `/knowledge/${id}/versions` : null,
  );
  const [more, setMore] = useState<KnowledgeVersionPage[]>([]);
  const [moreBusy, setMoreBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const impact = useResource<KnowledgeImpact>(
    impactOpen
      ? `/knowledge/${id}/impacts${view ? `?version_id=${view.version_id}` : ""}`
      : null,
  );
  const [reason, setReason] = useState("");
  const transition = useCommand(`knowledge-transition:${memberId}:${id}`);
  const [savedAction, setSavedAction] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const last = more.at(-1) ?? history.data;
  const versions = [
    ...new Map(
      [
        ...(history.data?.items ?? []),
        ...more.flatMap((page) => page.items),
      ].map((item) => [item.version_id, item]),
    ).values(),
  ];
  async function next() {
    if (!last?.has_more || last.next_cursor == null || moreBusy) return;
    setMoreBusy(true);
    setError(null);
    try {
      const { data } = await api<KnowledgeVersionPage>(
        `/knowledge/${id}/versions?before=${last.next_cursor}`,
      );
      setMore((old) => [...old, data]);
    } catch (failure) {
      setError(failure);
    } finally {
      setMoreBusy(false);
    }
  }
  async function act(action: "submit" | "publish" | "withdraw") {
    const result = await transition.run<KnowledgeView>(
      `/knowledge/${id}/${action}`,
      { decision: action, reason: reason.trim(), evidence_ids: [] },
      current.etag,
    );
    if (result) {
      setSavedAction(
        action === "withdraw"
          ? "停用已记录，旧报告与原件继续留存。"
          : action === "publish"
            ? "发布已记录，实际新用资格仍按当前范围与来源核验。"
            : "已送明确发布，尚未发布。",
      );
      setReason("");
      setVersionId(null);
      window.dispatchEvent(new Event("server-snapshot-change"));
      void current.reload();
      void history.reload();
      void impact.reload();
      onChanged();
    }
  }
  if (
    (current.data && current.data.id !== id) ||
    (view && (view.id !== id || (versionId && view.version_id !== versionId)))
  )
    return (
      <div className="notice error" role="alert">
        知识版本身份不一致，未用当前正文替代历史。
      </div>
    );
  return (
    <section className="panel knowledge-detail">
      <ResourceState
        {...current}
        hasData={!!current.data}
        onRetry={() => void current.reload()}
      />
      {versionId && (
        <ResourceState
          {...version}
          hasData={!!version.data}
          onRetry={() => void version.reload()}
        />
      )}
      <ErrorNotice error={error} />
      {view && (
        <>
          {!versionId && current.etag && (
            <button
              className="button secondary"
              onClick={() => setEditing((old) => !old)}
            >
              {editing ? "收起候选版本编辑" : "完善并追加候选版本"}
            </button>
          )}
          {editing && !versionId && current.etag && (
            <KnowledgeVersionEditor
              key={id}
              item={current.data!}
              etag={current.etag}
              memberId={memberId}
              onSaved={() => {
                setEditing(false);
                setVersionId(null);
                void current.reload();
                void history.reload();
                onChanged();
              }}
              onCancel={() => setEditing(false)}
            />
          )}
          <div className="section-heading">
            <div>
              <h2>{view.title}</h2>
              <p className="small-note">
                版本 {view.version_no} ·{" "}
                {versionId ? "按明确版本查阅" : "最新维护版本"}
              </p>
            </div>
            <Badge tone={view.workflow === "published" ? "success" : "warning"}>
              {knowledgeStates[view.workflow]}
            </Badge>
          </div>
          <p className="notice neutral">{view.reference_notice}</p>
          {supportsApi("GET", `/knowledge/${id}/indexes`) && (
            <KnowledgeIndex
              key={view.version_id}
              id={id}
              versionId={view.version_id}
              published={
                view.workflow === "published" &&
                view.published_version_id === view.version_id
              }
              memberId={memberId}
            />
          )}
          {view.published_version_id &&
            view.published_version_id !== view.version_id && (
              <div className="notice warning">
                <div>
                  <p>维护中的新候选不会自动替换旧发布版。</p>
                  <button
                    className="text-button"
                    onClick={() => setVersionId(view.published_version_id)}
                  >
                    查看当前发布版本
                  </button>
                </div>
              </div>
            )}
          {versionId && (
            <button className="text-button" onClick={() => setVersionId(null)}>
              返回最新维护版本
            </button>
          )}
          <div className="knowledge-tags">
            {view.categories.map((category) => (
              <Badge key={category}>
                {knowledgeCategories[
                  category as keyof typeof knowledgeCategories
                ] ?? category}
              </Badge>
            ))}
          </div>
          <pre className="knowledge-content">{view.content}</pre>
          <h3>适用范围</h3>
          <p>{view.scope}</p>
          {view.applicability ? (
            <>
              <p className="small-note">
                适用主体：
                {view.applicability.bidder_ids
                  .map(
                    (bidderId) =>
                      companies.data?.items.find(
                        (company) => company.id === bidderId,
                      )?.name ??
                      view.provenance.find(
                        (source) => source.bidder_id === bidderId,
                      )?.original_bidder ??
                      "主体名称未读取（仍按已选身份核对）",
                  )
                  .join("、")}
              </p>
              <p className="small-note">
                地区：{view.applicability.regions.join("、")}；工程类型：
                {view.applicability.engineering_types.join("、")}
              </p>
              <p className="small-note">
                用途：
                {view.applicability.purposes
                  .map((item) => knowledgePurposes[item])
                  .join("、")}
              </p>
              <p className="small-note">
                有效期：
                {new Date(view.applicability.valid_from).toLocaleString(
                  "zh-CN",
                )}{" "}
                起，
                {view.applicability.validity_kind === "bounded"
                  ? `至 ${view.applicability.valid_until ? new Date(view.applicability.valid_until).toLocaleString("zh-CN") : "期限缺失"}`
                  : view.applicability.validity_kind === "no_expiry_confirmed"
                    ? "已据核实依据明确无到期限制"
                    : "截止状态未知，不能发布或新用"}
              </p>
              <p className="small-note">{view.applicability.validity_basis}</p>
              <p className="small-note">
                {view.applicability.specificity_note}
              </p>
              <p className="small-note">
                另有 {view.applicability.conditions.length}{" "}
                项精确事实前提，选用时须与当前已确认事实及来源重新一致。
              </p>
            </>
          ) : (
            <div className="notice warning">
              适用主体、地区、工程类型、期限和用途尚未完善。当前只能保留候选，不能发布或据此选用。
            </div>
          )}
          <h3>原件与逐字出处</h3>
          {view.provenance.map((source, index) => (
            <article
              className="knowledge-source"
              key={`${source.source_ref.evidence_id}:${index}`}
            >
              <strong>
                {source.original_name} · 物理页{" "}
                {source.source_ref.physical_page}
              </strong>
              <p className="small-note">
                {source.original_project_title} · {source.original_bidder}
              </p>
              <blockquote>{source.source_ref.excerpt}</blockquote>
              <EvidenceLinks
                ids={[source.source_ref.evidence_id]}
                label="核对知识来源原页"
              />
            </article>
          ))}
          {!view.source_refs.length && (
            <p className="small-note">
              当前只保留了候选原件身份，尚未选定可核验的逐字出处。
            </p>
          )}
          <div className="review-shortcuts">
            <button
              className="text-button"
              onClick={() => setHistoryOpen((old) => !old)}
            >
              {historyOpen ? "收起知识版本" : "查看知识版本历史"}
            </button>
            <button
              className="text-button"
              onClick={() => setImpactOpen((old) => !old)}
            >
              {impactOpen ? "收起停用影响" : "查看当前版本影响"}
            </button>
          </div>
          {historyOpen && (
            <>
              <ResourceState
                {...history}
                hasData={!!history.data}
                onRetry={() => void history.reload()}
              />
              <div className="revision-choices">
                {versions.map((item) => (
                  <button
                    className="button secondary"
                    key={item.version_id}
                    onClick={() => setVersionId(item.version_id)}
                  >
                    版本 {item.version_no} · {knowledgeStates[item.workflow]}
                  </button>
                ))}
              </div>
              {last?.has_more && last.next_cursor != null && (
                <button
                  className="text-button"
                  disabled={moreBusy}
                  onClick={() => void next()}
                >
                  加载更早知识版本
                </button>
              )}
            </>
          )}
          {impactOpen && (
            <>
              <ResourceState
                {...impact}
                hasData={!!impact.data}
                onRetry={() => void impact.reload()}
              />
              {impact.data?.knowledge_id === id && (
                <div className="knowledge-impact">
                  <h3>登记引用的影响范围</h3>
                  {(
                    ["working", "submitted", "archived", "closed"] as const
                  ).map((group) => (
                    <section key={group}>
                      <strong>
                        {
                          {
                            working: "在办项目",
                            submitted: "已提交项目",
                            archived: "归档项目",
                            closed: "已结束或终止项目",
                          }[group]
                        }{" "}
                        ·{" "}
                        {
                          new Set(
                            impact.data!.groups[group].map(
                              (item) => item.bid_id,
                            ),
                          ).size
                        }
                        个项目 · {impact.data!.groups[group].length}处引用
                      </strong>
                      {impact.data!.groups[group].map((item) => (
                        <p key={item.citation_id}>
                          {item.title} ·{" "}
                          {knowledgePurposes[
                            item.purpose as keyof typeof knowledgePurposes
                          ] ?? item.purpose}{" "}
                          · {new Date(item.created_at).toLocaleString("zh-CN")}{" "}
                          · 引用 {item.citation_id.slice(0, 8)}
                          <button
                            className="text-button"
                            onClick={() => setCitationId(item.citation_id)}
                          >
                            追溯此项目当时引用
                          </button>
                        </p>
                      ))}
                    </section>
                  ))}
                  {impact.data.unknown_ranges.map((gap, index) => (
                    <p className="notice warning" key={index}>
                      {knowledgeReason(gap)}
                    </p>
                  ))}
                  <p className="small-note">
                    这里只显示已登记谱系。打开影响清单不表示已经复核，历史报告不会被重写。
                  </p>
                </div>
              )}
            </>
          )}
          {citationId && (
            <KnowledgeCitation citationId={citationId} knowledgeId={id} />
          )}
          {current.data?.version_id === view.version_id && (
            <form
              className="knowledge-transitions"
              onSubmit={(event) => event.preventDefault()}
            >
              <label>
                维护依据与原因
                <textarea
                  value={reason}
                  required
                  maxLength={2000}
                  onChange={(event) => setReason(event.target.value)}
                />
              </label>
              <ErrorNotice error={transition.error} />
              {transition.conflict && (
                <div className="notice warning">
                  知识状态或来源已变化，输入保留。请刷新并核对当前维护版本后再明确操作。
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => void current.reload()}
                  >
                    读取当前维护版本
                  </button>
                </div>
              )}
              <div className="review-shortcuts">
                {view.workflow === "candidate" && (
                  <button
                    className="button secondary"
                    disabled={
                      transition.busy ||
                      !current.etag ||
                      !view.applicability ||
                      view.applicability.validity_kind === "unknown" ||
                      !reason.trim()
                    }
                    onClick={() => void act("submit")}
                  >
                    完善后送明确发布
                  </button>
                )}
                {view.workflow === "pending_confirmation" && (
                  <button
                    className="button primary"
                    disabled={
                      transition.busy || !current.etag || !reason.trim()
                    }
                    onClick={() => void act("publish")}
                  >
                    明确发布此版本
                  </button>
                )}
                {view.published_version_id && !publishedView && (
                  <ResourceState
                    {...published}
                    hasData={false}
                    onRetry={() => void published.reload()}
                  />
                )}
                {publishedView && (
                  <p className="small-note">
                    停用对象：当前发布版本 {publishedView.version_no} ·{" "}
                    {publishedView.title}。维护中的其他候选不视为此发布对象。
                  </p>
                )}
                {view.published_version_id && (
                  <button
                    className="button secondary"
                    disabled={
                      transition.busy ||
                      !current.etag ||
                      !reason.trim() ||
                      !publishedView
                    }
                    onClick={() => void act("withdraw")}
                  >
                    停用当前发布版本
                  </button>
                )}
              </div>
              {savedAction && (
                <p role="status" className="inline-success">
                  {savedAction}
                </p>
              )}
            </form>
          )}
          {bid && (
            <KnowledgeReferenceForm
              key={`${view.version_id}:${bid.id}:${purpose}`}
              item={view}
              bid={bid}
              purpose={purpose}
            />
          )}
        </>
      )}
    </section>
  );
}

function KnowledgeReferenceForm({
  item,
  bid,
  purpose,
}: {
  item: KnowledgeView;
  bid: Bid;
  purpose: KnowledgeReferenceRequest["purpose"];
}) {
  const [excerpt, setExcerpt] = useState("");
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<KnowledgeReference | null>(null);
  const [citation, setCitation] = useState<string | null>(null);
  const history = useResource<KnowledgeReferenceHistory>(
    citation ? `/knowledge-references/${citation}` : null,
  );
  const [validation, setValidation] = useState("initial");
  const [rechecking, setRechecking] = useState(false);
  const [recheckError, setRecheckError] = useState<unknown>(null);
  const [checked, setChecked] = useState<{
    bid: Bid;
    item: KnowledgeView;
  } | null>(null);
  const command = useCommand(
    `knowledge-reference:${item.id}:${bid.id}:${purpose}:${validation}`,
  );
  const context = checked?.bid ?? bid;
  const currentItem = checked?.item ?? item;
  const eligible =
    currentItem.workflow === "published" &&
    currentItem.published_version_id === item.version_id &&
    context.identity?.binding_status === "confirmed" &&
    !!context.identity.region &&
    !!context.identity.engineering_type &&
    !context.archived_at &&
    ["preparation", "working"].includes(context.phase);
  const requiresRecheck =
    command.error instanceof ApiError &&
    command.error.status === 409 &&
    [
      "KNOWLEDGE_PROJECT_CONTEXT_CHANGED",
      "KNOWLEDGE_PROJECT_CONTEXT_MISSING",
      "KNOWLEDGE_NOT_APPLICABLE",
    ].includes(command.error.code);
  async function recheck() {
    if (rechecking || command.busy) return;
    setRechecking(true);
    setRecheckError(null);
    try {
      const [project, version] = await Promise.all([
        api<Bid>(`/bids/${bid.id}`),
        api<KnowledgeView>(`/knowledge/${item.id}/versions/${item.version_id}`),
      ]);
      if (
        project.data.id !== bid.id ||
        version.data.id !== item.id ||
        version.data.version_id !== item.version_id
      )
        throw new Error(
          "重新读取的身份不一致，保留原摘录与请求，不使用其他项目或版本。",
        );
      setChecked({ bid: project.data, item: version.data });
      setValidation(crypto.randomUUID());
      command.clearError();
      setResult(null);
    } catch (failure) {
      setRecheckError(failure);
    } finally {
      setRechecking(false);
    }
  }
  async function save() {
    const body: KnowledgeReferenceRequest = {
      bid_id: bid.id,
      version_id: item.version_id,
      purpose,
      target_kind: "project",
      target_object_id: bid.id,
      excerpt: excerpt.trim(),
      applicability_reason: reason.trim(),
    };
    const response = await command.run<KnowledgeReference>(
      `/knowledge/${item.id}/references`,
      body,
      null,
    );
    if (
      response &&
      response.data.bid_id === bid.id &&
      response.data.version_id === item.version_id
    )
      setResult(response.data);
  }
  return (
    <section className="knowledge-reference-form">
      <h3>明确选作项目参考</h3>
      <p className="small-note">
        {bid.title} · {knowledgePurposes[purpose]}
        。服务器会在此刻重新核验全部资格；选用不确认项目事实，也不表示正式评分通过。
      </p>
      {!eligible && (
        <div className="notice warning">
          当前版本、项目身份、地区、工程类型或项目阶段不满足新增选用条件。旧知识与旧引用仍可追溯。
        </div>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <label>
          本次使用的实际摘录
          <textarea
            value={excerpt}
            maxLength={20000}
            required
            disabled={command.busy}
            onChange={(event) => setExcerpt(event.target.value)}
            placeholder="填写此版本正文中的逐字摘录"
          />
        </label>
        <label>
          为何适用于此项目与用途
          <textarea
            value={reason}
            maxLength={4000}
            required
            disabled={command.busy}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
        <ErrorNotice error={command.error} />
        <ErrorNotice error={recheckError} onRetry={() => void recheck()} />
        {requiresRecheck && (
          <button
            type="button"
            className="text-button"
            disabled={rechecking}
            onClick={() => void recheck()}
          >
            {rechecking
              ? "正在重读项目与原知识版本…"
              : "重新核对项目与知识版本，保留本次摘录"}
          </button>
        )}
        {checked && (
          <p className="notice neutral">
            已重读当前主体：{checked.bid.identity.bidder_name}；原知识版本
            {checked.item.version_no}，状态
            {knowledgeStates[checked.item.workflow]}
            。请核对原摘录与用途后再明确选用；当前资格仍由服务器再次核验。
          </p>
        )}
        <button
          className="button secondary"
          disabled={
            !eligible ||
            command.busy ||
            rechecking ||
            requiresRecheck ||
            !excerpt.trim() ||
            !reason.trim()
          }
        >
          {command.busy ? "正在重新核对资格并登记参考…" : "登记本次项目参考"}
        </button>
      </form>
      {result && (
        <div className="notice neutral">
          <div>
            <strong>参考已登记，未创建项目事实</strong>
            <p>{result.excerpt}</p>
            {result.citation_ids.map((id) => (
              <button
                className="text-button"
                key={id}
                onClick={() => setCitation(id)}
              >
                追溯当时引用及当前资格
              </button>
            ))}
          </div>
        </div>
      )}
      {citation && (
        <>
          <ResourceState
            {...history}
            hasData={!!history.data}
            onRetry={() => void history.reload()}
          />
          {history.data?.reference.version_id === item.version_id &&
            history.data.reference.bid_id === bid.id && (
              <div className="knowledge-reference-history">
                <h4>当时固定的摘录</h4>
                <blockquote>{history.data.reference.excerpt}</blockquote>
                <p>{history.data.reference.applicability_reason}</p>
                {history.data.current_applicability_reasons.map(
                  (gap, index) => (
                    <p className="notice warning" key={index}>
                      {knowledgeReason(gap)}
                    </p>
                  ),
                )}
                <details>
                  <summary>查看当时知识版本正文</summary>
                  <pre className="knowledge-content">
                    {history.data.version_content}
                  </pre>
                </details>
                <EvidenceLinks
                  ids={history.data.reference.source_refs.map(
                    (source) => source.evidence_id,
                  )}
                  label="追溯当时原件依据"
                />
              </div>
            )}
        </>
      )}
    </section>
  );
}

function KnowledgeCitation({
  citationId,
  knowledgeId,
}: {
  citationId: string;
  knowledgeId: string;
}) {
  const history = useResource<KnowledgeReferenceHistory>(
    `/knowledge-references/${citationId}`,
  );
  const value = history.data;
  const valid =
    !!value &&
    value.reference.knowledge_id === knowledgeId &&
    value.reference.citation_ids.includes(citationId);
  return (
    <section className="knowledge-reference-history">
      <h3>当时引用与当前资格</h3>
      <ResourceState
        {...history}
        hasData={!!value}
        onRetry={() => void history.reload()}
      />
      {value && !valid && (
        <p className="notice error">
          引用身份不一致，未用其他项目或版本的记录替代。
        </p>
      )}
      {valid && (
        <>
          <blockquote>{value.reference.excerpt}</blockquote>
          <p>{value.reference.applicability_reason}</p>
          <p className="small-note">
            {knowledgePurposes[value.reference.purpose]} ·
            当时版本摘录留存，不自动产生工程事实或当前合格结论。
          </p>
          {value.current_applicability_reasons.map((reason, index) => (
            <p className="notice warning" key={index}>
              {knowledgeReason(reason)}
            </p>
          ))}
          <details>
            <summary>查看当时固定知识正文</summary>
            <pre className="knowledge-content">{value.version_content}</pre>
          </details>
          <EvidenceLinks
            ids={value.reference.source_refs.map((ref) => ref.evidence_id)}
            label="核对当时引用原页"
          />
        </>
      )}
    </section>
  );
}
