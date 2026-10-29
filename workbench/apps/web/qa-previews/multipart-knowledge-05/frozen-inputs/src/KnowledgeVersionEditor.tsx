import { useEffect, useState } from "react";
import { api } from "./api";
import type {
  BiddingCompanyPage,
  DocumentView,
  FactSetView,
  KnowledgeSourcePosition,
  KnowledgeSourcePositions,
  KnowledgeVersionRequest,
  KnowledgeView,
} from "./contracts";
import { Badge, ErrorNotice } from "./components";
import { EvidenceLinks } from "./EvidenceLinks";
import { knowledgeCategories, knowledgePurposes } from "./knowledgeNames";
import { ResourceState } from "./ResourceState";
import { useCommand } from "./useCommand";
import { useResource } from "./useResource";
import { useDirectory } from "./useDirectory";
import { useBidChoices } from "./useBidChoices";
import {
  useKnowledgeInput,
  knowledgeStorageKey,
  discardKnowledgeForm,
} from "./knowledgeStorage";

function inputDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "";
  const pad = (number: number) => String(number).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
const tokens = (value: string) => [
  ...new Set(
    value
      .split(/[,，、\n]/)
      .map((item) => item.trim())
      .filter(Boolean),
  ),
];

export function KnowledgeVersionEditor({
  item,
  etag,
  memberId,
  onSaved,
  onCancel,
}: {
  item: KnowledgeView;
  etag: string;
  memberId: string;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const formKey = knowledgeStorageKey(memberId, item.id);
  const [title, setTitle] = useKnowledgeInput(formKey + "title", item.title);
  const [content, setContent] = useKnowledgeInput(
    formKey + "content",
    item.content,
  );
  const [scope, setScope] = useKnowledgeInput(formKey + "scope", item.scope);
  const [categories, setCategories] = useKnowledgeInput<
    KnowledgeVersionRequest["categories"]
  >(
    formKey + "categories",
    item.categories.filter(
      (category) => category in knowledgeCategories,
    ) as KnowledgeVersionRequest["categories"],
  );
  const original = item.applicability;
  const [bidders, setBidders] = useKnowledgeInput(
    formKey + "bidders",
    original?.bidder_ids ?? [],
  );
  const [bidIds, setBidIds] = useKnowledgeInput(
    formKey + "bidIds",
    original?.bid_ids ?? [],
  );
  const [limited, setLimited] = useKnowledgeInput(
    formKey + "limited",
    !!original?.bid_ids.length,
  );
  const [regions, setRegions] = useKnowledgeInput(
    formKey + "regions",
    original?.regions.join("、") ?? "",
  );
  const [types, setTypes] = useKnowledgeInput(
    formKey + "types",
    original?.engineering_types.join("、") ?? "",
  );
  const [purposes, setPurposes] = useKnowledgeInput(
    formKey + "purposes",
    original?.purposes ?? [],
  );
  const [validity, setValidity] = useKnowledgeInput(
    formKey + "validity",
    original?.validity_kind ?? "unknown",
  );
  const [from, setFrom] = useKnowledgeInput(
    formKey + "from",
    inputDate(original?.valid_from ?? new Date().toISOString()),
  );
  const [until, setUntil] = useKnowledgeInput(
    formKey + "until",
    original?.valid_until ? inputDate(original.valid_until) : "",
  );
  const [basis, setBasis] = useKnowledgeInput(
    formKey + "basis",
    original?.validity_basis ?? "",
  );
  const [note, setNote] = useKnowledgeInput(
    formKey + "note",
    original?.specificity_note ?? "",
  );
  const [conditions, setConditions] = useKnowledgeInput(
    formKey + "conditions",
    original?.conditions ?? [],
  );
  const [noConditions, setNoConditions] = useKnowledgeInput(
    formKey + "noConditions",
    original ? original.conditions.length === 0 : false,
  );
  const [factBid, setFactBid] = useKnowledgeInput(formKey + "factBid", "");
  const [refs, setRefs] = useKnowledgeInput<KnowledgeSourcePosition[]>(
    formKey + "refs",
    item.source_refs,
  );
  const [baseEtag, setBaseEtag] = useKnowledgeInput(formKey + "baseEtag", etag);
  const [remote, setRemote] = useState<{
    value: KnowledgeView;
    etag: string;
  } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [companyQuery, setCompanyQuery] = useState("");
  const companies = useDirectory<BiddingCompanyPage>(
    `/identity/bidders?query=${encodeURIComponent(companyQuery)}&limit=100`,
  );
  const projects = useBidChoices();
  const facts = useResource<FactSetView>(
    factBid ? `/bids/${factBid}/facts` : null,
  );
  const command = useCommand(`knowledge-version:${memberId}:${item.id}`);
  const companyFact = categories.includes("company_fact");
  const ready =
    title.trim() &&
    content.trim() &&
    scope.trim() &&
    categories.length &&
    bidders.length &&
    (!companyFact || bidders.length === 1) &&
    tokens(regions).length &&
    tokens(types).length &&
    purposes.length &&
    from &&
    basis.trim() &&
    note.trim() &&
    refs.length &&
    (!limited || bidIds.length) &&
    (noConditions || conditions.length) &&
    (validity !== "bounded" || until);
  async function save() {
    setError(null);
    try {
      const body: KnowledgeVersionRequest = {
        title: title.trim(),
        content: content.trim(),
        scope: scope.trim(),
        categories,
        source_refs: refs,
        applicability: {
          bidder_ids: bidders,
          bid_ids: limited ? bidIds : [],
          regions: tokens(regions),
          engineering_types: tokens(types),
          purposes,
          conditions: noConditions ? [] : conditions,
          validity_kind: validity,
          valid_from: new Date(from).toISOString(),
          valid_until:
            validity === "bounded" && until
              ? new Date(until).toISOString()
              : null,
          validity_basis: basis.trim(),
          specificity_note: note.trim(),
        },
      };
      const result = await command.run<KnowledgeView>(
        `/knowledge/${item.id}/versions`,
        body,
        baseEtag,
      );
      if (result && result.data.id === item.id) {
        discardKnowledgeForm(formKey);
        onSaved();
      }
    } catch (failure) {
      setError(failure);
    }
  }
  async function compare() {
    setError(null);
    try {
      const result = await api<KnowledgeView>(`/knowledge/${item.id}`);
      if (!result.etag || result.data.id !== item.id)
        throw new Error("最新知识身份或条件令牌无法核对，当前输入保留。");
      setRemote({ value: result.data, etag: result.etag });
    } catch (failure) {
      setError(failure);
    }
  }
  return (
    <form
      className="knowledge-version-editor"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <h3>完善并追加知识候选版本</h3>
      <p className="small-note">
        保存只追加候选，旧发布版继续保留。字段不完整、期限未知或来源失效都不能借候选保存绕过发布与适用性检查。收起或离开时本地输入保留；再次打开后仍须按原条件令牌核对保存。
      </p>
      {projects.hasMore && (
        <button
          type="button"
          className="text-button"
          disabled={projects.moreBusy}
          onClick={() => void projects.loadMore()}
        >
          加载更多项目供选择
        </button>
      )}
      <ErrorNotice
        error={projects.moreError}
        onRetry={() => void projects.loadMore()}
      />
      <fieldset disabled={command.busy}>
        <legend>知识内容与分类</legend>
        <label>
          版本标题
          <input
            required
            maxLength={200}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        <label>
          版本正文
          <textarea
            required
            rows={7}
            maxLength={100000}
            value={content}
            onChange={(event) => setContent(event.target.value)}
          />
        </label>
        <label>
          明确的适用范围
          <textarea
            required
            maxLength={2000}
            value={scope}
            onChange={(event) => setScope(event.target.value)}
          />
        </label>
        <div className="checkbox-options">
          {Object.entries(knowledgeCategories).map(([key, label]) => (
            <label className="checkbox-label" key={key}>
              <input
                type="checkbox"
                checked={categories.includes(
                  key as KnowledgeVersionRequest["categories"][number],
                )}
                onChange={(event) =>
                  setCategories((old) =>
                    event.target.checked
                      ? [
                          ...old,
                          key as KnowledgeVersionRequest["categories"][number],
                        ]
                      : old.filter((item) => item !== key),
                  )
                }
              />
              {label}
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset disabled={command.busy}>
        <legend>适用主体、工程与地区</legend>
        <label>
          查找已明确登记的主体
          <input
            value={companyQuery}
            maxLength={200}
            onChange={(event) => setCompanyQuery(event.target.value)}
          />
        </label>
        <ResourceState
          {...companies}
          hasData={!!companies.data}
          onRetry={() => void companies.reload()}
        />
        {companies.items.map((company) => (
          <label key={company.id} className="checkbox-label">
            <input
              type="checkbox"
              checked={bidders.includes(company.id)}
              onChange={(event) =>
                setBidders((old) =>
                  event.target.checked
                    ? [...new Set([...old, company.id])]
                    : old.filter((id) => id !== company.id),
                )
              }
            />
            {company.name}
          </label>
        ))}
        {companies.hasMore && (
          <p className="small-note">
            主体结果较多，请缩小名称范围查找；名称相近不会自动合并。
          </p>
        )}
        {companies.hasMore && (
          <button
            type="button"
            className="text-button"
            disabled={companies.moreBusy}
            onClick={() => void companies.loadMore()}
          >
            加载更多适用主体
          </button>
        )}
        <ErrorNotice
          error={companies.moreError}
          onRetry={() => void companies.loadMore()}
        />
        {companyFact && bidders.length !== 1 && (
          <p className="notice warning">
            本公司可用事实必须明确单一主体，且全部来源属于该主体。原件选择不会自动取得事实资格。
          </p>
        )}
        <label>
          明确地区范围
          <input
            value={regions}
            required
            onChange={(event) => setRegions(event.target.value)}
            placeholder="多个地区用顿号分隔，不能留空表示全部"
          />
        </label>
        <label>
          明确工程类型
          <input
            value={types}
            required
            onChange={(event) => setTypes(event.target.value)}
            placeholder="多个类型用顿号分隔"
          />
        </label>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={limited}
            onChange={(event) => setLimited(event.target.checked)}
          />
          进一步限定到明确项目
        </label>
        {limited ? (
          <>
            <ResourceState
              {...projects}
              hasData={!!projects.data}
              onRetry={() => void projects.reload()}
            />
            {projects.items.map((bid) => (
              <label className="checkbox-label" key={bid.id}>
                <input
                  type="checkbox"
                  checked={bidIds.includes(bid.id)}
                  onChange={(event) =>
                    setBidIds((old) =>
                      event.target.checked
                        ? [...new Set([...old, bid.id])]
                        : old.filter((id) => id !== bid.id),
                    )
                  }
                />
                {bid.title}
              </label>
            ))}
          </>
        ) : (
          <p className="small-note">
            在上述已明确主体、地区与工程类型内，不再限定具体项目；这不等于任意主体或任意工程可用。
          </p>
        )}
        <div className="checkbox-options">
          {Object.entries(knowledgePurposes).map(([key, label]) => (
            <label className="checkbox-label" key={key}>
              <input
                type="checkbox"
                checked={purposes.includes(key as (typeof purposes)[number])}
                onChange={(event) =>
                  setPurposes((old) =>
                    event.target.checked
                      ? [...old, key as (typeof purposes)[number]]
                      : old.filter((value) => value !== key),
                  )
                }
              />
              {label}
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset disabled={command.busy}>
        <legend>期限与核实依据</legend>
        <label>
          有效性方式
          <select
            aria-label="知识有效性方式"
            value={validity}
            onChange={(event) =>
              setValidity(event.target.value as typeof validity)
            }
          >
            <option value="unknown">期限尚未知，仅保留候选</option>
            <option value="bounded">有明确截止期限</option>
            <option value="no_expiry_confirmed">
              据核实依据明确无到期限制
            </option>
          </select>
        </label>
        <label>
          生效起始（本地时间）
          <input
            type="datetime-local"
            required
            value={from}
            onChange={(event) => setFrom(event.target.value)}
          />
        </label>
        {validity === "bounded" && (
          <label>
            截止时间（本地时间）
            <input
              type="datetime-local"
              required
              value={until}
              onChange={(event) => setUntil(event.target.value)}
            />
          </label>
        )}
        <label>
          期限核实依据
          <textarea
            required
            value={basis}
            maxLength={4000}
            onChange={(event) => setBasis(event.target.value)}
          />
        </label>
        <label>
          特殊条件与范围说明
          <textarea
            required
            value={note}
            maxLength={4000}
            onChange={(event) => setNote(event.target.value)}
          />
        </label>
      </fieldset>
      <fieldset disabled={command.busy}>
        <legend>项目事实前提</legend>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={noConditions}
            onChange={(event) => setNoConditions(event.target.checked)}
          />
          明确不设额外事实前提
        </label>
        {!noConditions && (
          <>
            <label>
              从真实项目读取已确认事实
              <select
                aria-label="条件事实来源项目"
                value={factBid}
                onChange={(event) => setFactBid(event.target.value)}
              >
                <option value="">选择项目</option>
                {projects.items.map((bid) => (
                  <option key={bid.id} value={bid.id}>
                    {bid.title}
                  </option>
                ))}
              </select>
            </label>
            <ResourceState
              {...facts}
              hasData={!!facts.data}
              onRetry={() => void facts.reload()}
            />
            {facts.data?.facts
              .filter(
                (fact) =>
                  fact.confirmation === "confirmed" &&
                  fact.source_validity === "effective" &&
                  fact.value !== null,
              )
              .map((fact) => {
                const condition = {
                  subject: fact.subject,
                  scope: fact.scope,
                  name: fact.name,
                  value: fact.value!,
                  unit: fact.unit,
                };
                const signature = JSON.stringify(condition);
                return (
                  <label className="checkbox-label" key={fact.id}>
                    <input
                      type="checkbox"
                      checked={conditions.some(
                        (item) => JSON.stringify(item) === signature,
                      )}
                      onChange={(event) =>
                        setConditions((old) =>
                          event.target.checked
                            ? [
                                ...old.filter(
                                  (item) => JSON.stringify(item) !== signature,
                                ),
                                condition,
                              ]
                            : old.filter(
                                (item) => JSON.stringify(item) !== signature,
                              ),
                        )
                      }
                    />
                    {fact.subject} · {fact.name}：{String(fact.value)}
                    {fact.unit ?? ""} · {fact.scope}
                  </label>
                );
              })}
          </>
        )}
        <p className="small-note">
          已选 {noConditions ? 0 : conditions.length}{" "}
          项。值与类型、单位、范围、当前人工确认和完整来源祖先必须同时一致；知识发布和选用不会自动确认事实。
        </p>
      </fieldset>
      <KnowledgeSourcePicker
        item={item}
        selected={refs}
        disabled={command.busy}
        onChange={setRefs}
      />
      <ErrorNotice error={error ?? command.error} />
      {command.conflict && (
        <div className="notice warning">
          <div>
            <p>
              当前版本或来源状态已有变化，所有输入保留。先读取最新版本比较，再明确按新基准追加候选。
            </p>
            <button
              type="button"
              className="text-button"
              onClick={() => void compare()}
            >
              读取最新知识并比较
            </button>
          </div>
        </div>
      )}
      {remote && (
        <div className="notice warning">
          <div>
            <strong>
              当前服务器版本 {remote.value.version_no}：{remote.value.title}
            </strong>
            <pre className="knowledge-content">{remote.value.content}</pre>
            <button
              type="button"
              className="button secondary"
              onClick={() => {
                setBaseEtag(remote.etag);
                setRemote(null);
                command.clearError();
              }}
            >
              保留本地内容，按当前版本继续追加
            </button>
          </div>
        </div>
      )}
      <div className="review-shortcuts">
        <button className="button primary" disabled={command.busy || !ready}>
          {command.busy ? "正在核验来源并追加候选…" : "保存候选新版本"}
        </button>
        <button
          className="text-button"
          type="button"
          disabled={command.busy}
          onClick={() => {
            discardKnowledgeForm(formKey);
            onCancel();
          }}
        >
          放弃本地编辑并返回
        </button>
      </div>
    </form>
  );
}

function KnowledgeSourcePicker({
  item,
  selected,
  disabled,
  onChange,
}: {
  item: KnowledgeView;
  selected: KnowledgeSourcePosition[];
  disabled: boolean;
  onChange: (value: KnowledgeSourcePosition[]) => void;
}) {
  const [documents, setDocuments] = useState<DocumentView[]>([]);
  const [metadataAttempt, setMetadataAttempt] = useState(0);
  const [metadataError, setMetadataError] = useState<unknown>(null);
  const [documentId, setDocumentId] = useState(
    item.declared_source_version_ids[0] ?? "",
  );
  const [page, setPage] = useState(1);
  const [parseId, setParseId] = useState<string | null>(null);
  const [more, setMore] = useState<
    { path: string; value: KnowledgeSourcePositions }[]
  >([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const idsKey = item.declared_source_version_ids.join(",");
  useEffect(() => {
    let active = true;
    setDocuments([]);
    setMetadataError(null);
    void Promise.allSettled(
      idsKey
        .split(",")
        .filter(Boolean)
        .map(async (id) => {
          const { data } = await api<DocumentView>(`/documents/${id}`);
          if (data.id !== id) throw new Error("原件身份不一致");
          return data;
        }),
    ).then((results) => {
      if (!active) return;
      setDocuments(
        results.flatMap((result) =>
          result.status === "fulfilled" ? [result.value] : [],
        ),
      );
      if (results.some((result) => result.status === "rejected"))
        setMetadataError(
          new Error("部分候选原件元数据尚不能读取，未把缺失来源视为已核验。"),
        );
    });
    return () => {
      active = false;
    };
  }, [idsKey, metadataAttempt]);
  const params = new URLSearchParams({
    document_version_id: documentId,
    physical_page: String(page),
    limit: "50",
  });
  if (parseId) params.set("parse_id", parseId);
  const path = documentId
    ? `/knowledge/${item.id}/source-positions?${params}`
    : null;
  const positions = useResource<KnowledgeSourcePositions>(path);
  useEffect(() => {
    if (!parseId && positions.data?.parse_id)
      setParseId(positions.data.parse_id);
  }, [parseId, positions.data]);
  const pages = more
    .filter((entry) => entry.path === path)
    .map((entry) => entry.value);
  const last = pages.at(-1) ?? positions.data;
  const items = [
    ...new Map(
      [
        ...(positions.data?.items ?? []),
        ...pages.flatMap((value) => value.items),
      ].map((value) => [value.reference.evidence_id, value]),
    ).values(),
  ];
  async function next() {
    if (
      !path ||
      !last?.has_more ||
      last.next_ordinal == null ||
      !last.parse_id ||
      loadingMore
    )
      return;
    setLoadingMore(true);
    setError(null);
    try {
      const { data } = await api<KnowledgeSourcePositions>(
        `${path}&after_ordinal=${last.next_ordinal}`,
      );
      if (data.parse_id !== last.parse_id || data.physical_page !== page)
        throw new Error("分页来源与当前解析身份不一致，未合并其他解析内容。");
      setMore((old) => [...old, { path, value: data }]);
    } catch (failure) {
      setError(failure);
    } finally {
      setLoadingMore(false);
    }
  }
  return (
    <fieldset className="knowledge-source-picker" disabled={disabled}>
      <legend>选择真实原页与逐字摘录</legend>
      <label>
        候选原件
        <select
          aria-label="知识候选原件"
          value={documentId}
          onChange={(event) => {
            setDocumentId(event.target.value);
            setPage(1);
            setParseId(null);
            setMore([]);
          }}
        >
          <option value="">选择原件</option>
          {documents.map((document) => (
            <option key={document.id} value={document.id}>
              {document.filename} · 版本 {document.file_revision}
            </option>
          ))}
        </select>
      </label>
      <label>
        物理页
        <select
          aria-label="知识来源物理页"
          value={page}
          onChange={(event) => {
            setPage(Number(event.target.value));
            setParseId(null);
            setMore([]);
          }}
        >
          {Array.from(
            { length: Math.max(1, positions.data?.page_count ?? 1) },
            (_, index) => (
              <option key={index + 1} value={index + 1}>
                {index + 1}
              </option>
            ),
          )}
        </select>
      </label>
      <ResourceState
        {...positions}
        hasData={!!positions.data}
        onRetry={() => void positions.reload()}
      />
      <ErrorNotice
        error={metadataError}
        onRetry={() => setMetadataAttempt((old) => old + 1)}
      />
      <ErrorNotice error={error} onRetry={() => void next()} />
      {positions.data?.readiness === "not_ready" && (
        <p className="notice warning">
          本页解析尚未提供可读出处，不能伪造来源或把整份原件当作此页证据。
          <button
            type="button"
            className="text-button"
            disabled={positions.loading}
            onClick={() => void positions.reload()}
          >
            重新读取本页出处
          </button>
        </p>
      )}
      {items.map((source) => {
        const ref = source.reference;
        const checked = selected.some(
          (value) =>
            value.evidence_id === ref.evidence_id &&
            value.source_id === ref.source_id,
        );
        const valid =
          ref.document_version_id === documentId &&
          ref.physical_page === page &&
          ref.parse_id === positions.data?.parse_id;
        return (
          <article className="knowledge-source-choice" key={ref.evidence_id}>
            <Badge>物理页 {ref.physical_page}</Badge>
            <blockquote>{ref.excerpt}</blockquote>
            {source.excerpt_truncated && (
              <p className="small-note">
                服务器提供的候选摘录已截短，不能称为完整解析。可在已选摘录中明确调整较短范围，并核对原页。
              </p>
            )}
            <EvidenceLinks ids={[ref.evidence_id]} label="查看此出处原页" />
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={checked}
                disabled={disabled || !valid}
                onChange={(event) =>
                  onChange(
                    event.target.checked
                      ? [
                          ...selected.filter(
                            (value) => value.evidence_id !== ref.evidence_id,
                          ),
                          ref,
                        ]
                      : selected.filter(
                          (value) => value.evidence_id !== ref.evidence_id,
                        ),
                  )
                }
              />
              使用此真实出处
            </label>
          </article>
        );
      })}
      {last?.has_more && last.next_ordinal != null && (
        <button
          type="button"
          className="text-button"
          disabled={disabled || loadingMore}
          onClick={() => void next()}
        >
          {loadingMore ? "正在读取同页更多出处…" : "读取本页更多出处"}
        </button>
      )}
      <h4>本版本已选 {selected.length} 处来源</h4>
      {selected.map((ref, index) => (
        <div
          className="knowledge-selected-source"
          key={`${ref.evidence_id}:${ref.source_revision}`}
        >
          <label>
            物理页 {ref.physical_page} · 本次逐字摘录
            <textarea
              value={ref.excerpt}
              required
              maxLength={20000}
              onChange={(event) =>
                onChange(
                  selected.map((value, position) =>
                    position === index
                      ? { ...value, excerpt: event.target.value }
                      : value,
                  ),
                )
              }
            />
          </label>
          <EvidenceLinks ids={[ref.evidence_id]} label="核对已选原页" />
          <button
            type="button"
            className="text-button"
            onClick={() =>
              onChange(selected.filter((_, position) => position !== index))
            }
          >
            移除此版本出处
          </button>
        </div>
      ))}
      <p className="small-note">
        原件、解析、物理页与来源版本来自服务器投影。切换文件或解析不会悄悄替换已经选定的历史出处。
      </p>
    </fieldset>
  );
}
