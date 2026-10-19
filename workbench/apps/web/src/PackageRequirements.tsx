import { useEffect, useRef, useState } from "react";
import { api, ApiError, supportsApi } from "./api";
import type {
  BidPackageHeadPage,
  BidPackageRevisionSummaryPage,
  BidPackageStoredView,
  CreatePackageRequirementInventory,
  PackageCoverageAttemptView,
  PackageRequirementHistoryPage,
  PackageRequirementInventoryPage,
  PackageRequirementInventoryView,
  RuleSetView,
} from "./contracts";
import { ErrorNotice } from "./components";
import { EvidenceLinks } from "./EvidenceLinks";
import { ResourceState } from "./ResourceState";
import { useDirectory } from "./useDirectory";
import { useResource } from "./useResource";

type Props = {
  bidId: string;
  memberId: string;
  packageView: BidPackageStoredView;
  disabled?: boolean;
};
type Scope = {
  bidId: string;
  memberId: string;
  packageId: string;
  revisionId: string;
  digest: string;
};
type Pending = {
  version: 1;
  scope: Scope;
  body: CreatePackageRequirementInventory;
  key: string;
  etag: string | null;
  ifNoneMatch: "*" | null;
};
const sha = /^[a-f0-9]{64}$/;
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const storageKey = (scope: Scope) =>
  `tender:requirements-pending:${scope.memberId}:${scope.bidId}:${scope.packageId}:${scope.revisionId}`;
function restore(scope: Scope): { pending: Pending | null; blocked: boolean } {
  try {
    const raw = sessionStorage.getItem(storageKey(scope));
    if (!raw) return { pending: null, blocked: false };
    const value = JSON.parse(raw) as Pending;
    if (
      value.version !== 1 ||
      !value.scope ||
      Object.keys(scope).some(
        (k) => value.scope[k as keyof Scope] !== scope[k as keyof Scope],
      ) ||
      typeof value.key !== "string" ||
      !uuid.test(value.key) ||
      !value.body ||
      Object.keys(value.body).sort().join(",") !==
        "authority_revision_id,mappings,rule_set_id" ||
      !uuid.test(value.body.authority_revision_id) ||
      !uuid.test(value.body.rule_set_id) ||
      !Array.isArray(value.body.mappings) ||
      value.body.mappings.length !== 0 ||
      !(
        (value.ifNoneMatch === "*" && value.etag === null) ||
        (value.ifNoneMatch === null &&
          typeof value.etag === "string" &&
          value.etag.length > 0)
      )
    )
      throw new Error("invalid pending scope");
    return { pending: value, blocked: false };
  } catch {
    return { pending: null, blocked: true };
  }
}
const strings = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.filter((v): v is string => typeof v === "string")
    : [];
const text = (value: unknown) => (typeof value === "string" ? value : "未记录");
const categories: Record<string, string> = {
  unclassified: "未分类",
  qualification: "资格",
  business: "商务",
  technical: "技术",
  price: "报价",
  commercial: "商务",
  attachment: "附件",
  annex: "附件",
};
const decisions: Record<string, string> = {
  confirmed: "已确认",
  rejected: "已否决",
  deferred: "暂缓",
  pending: "待确认",
};
const gapNames: Record<string, string> = {
  page_count_unknown: "页数未知",
  parts_unassigned: "逻辑范围未分配",
  parse_identity_not_frozen: "解析身份尚未冻结",
};
function Conditions({ value, label }: { value: unknown; label: string }) {
  const valid =
    Array.isArray(value) && value.every((v) => typeof v === "string");
  return (
    <>
      <p>
        {label}：
        {valid
          ? value.join("；") || `原规则未列${label.replace("原始", "")}`
          : "记录格式待核"}
      </p>
      {!valid && (
        <details>
          <summary>{label}原始记录</summary>
          <pre>{JSON.stringify(value ?? null, null, 2)}</pre>
        </details>
      )}
    </>
  );
}
const names: Record<string, string> = {
  unknown: "未知",
  not_provided: "未提供",
  missing: "缺项",
  pending_parse: "待解析",
  parse_gap: "解析有缺口",
  unsupported: "不支持",
  verified: "人工声明已核对范围",
  not_applicable: "人工声明不适用",
  conflict: "存在冲突",
};

export function PackageRequirements(props: Props) {
  const [expanded, setExpanded] = useState(false);
  const m = props.packageView.manifest;
  if (
    m.kind !== "bid" ||
    m.scope.bid_id !== props.bidId ||
    !sha.test(props.packageView.digest)
  )
    return (
      <p role="alert">要求工作面的本方资料包身份不一致，未加载其他记录。</p>
    );
  return (
    <>
      <button
        type="button"
        className="button secondary requirements-toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        要求清单与覆盖
      </button>
      {expanded && (
        <Workspace
          key={`${props.bidId}:${props.memberId}:${m.package_id}:${m.revision_id}:${props.packageView.digest}`}
          {...props}
        />
      )}
    </>
  );
}

function Workspace({ bidId, memberId, packageView, disabled = false }: Props) {
  const m = packageView.manifest;
  const scope: Scope = {
    bidId,
    memberId,
    packageId: m.package_id,
    revisionId: m.revision_id,
    digest: packageView.digest,
  };
  const base = `/bids/${bidId}/packages/${m.package_id}/revisions/${m.revision_id}/requirement-inventories`;
  const [recovery] = useState(() => restore(scope));
  const [pending, setPending] = useState<Pending | null>(recovery.pending);
  const [authorityId, setAuthorityId] = useState("");
  const [authorityRevision, setAuthorityRevision] = useState("");
  const [inventoryId, setInventoryId] = useState("");
  const [attemptId, setAttemptId] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const [notice, setNotice] = useState("");
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const authorities = useDirectory<BidPackageHeadPage>(
    `/bids/${bidId}/packages?kind=authority&limit=20`,
  );
  const revisions = useDirectory<BidPackageRevisionSummaryPage>(
    authorityId
      ? `/bids/${bidId}/packages/${authorityId}/revisions?limit=20`
      : null,
  );
  const authority = useResource<BidPackageStoredView>(
    authorityId && authorityRevision
      ? `/bids/${bidId}/packages/${authorityId}/revisions/${authorityRevision}`
      : null,
  );
  const rules = useResource<RuleSetView>(`/bids/${bidId}/rules`);
  const inventories = useDirectory<PackageRequirementInventoryPage>(
    `${base}?limit=20`,
  );
  const inventory = useResource<PackageRequirementInventoryView>(
    inventoryId ? `${base}/${inventoryId}` : null,
  );
  const attempts = useDirectory<PackageRequirementHistoryPage>(
    inventoryId ? `${base}/${inventoryId}/coverage-attempts?limit=20` : null,
  );
  const attempt = useResource<PackageCoverageAttemptView>(
    inventoryId && attemptId
      ? `${base}/${inventoryId}/coverage-attempts/${attemptId}`
      : null,
  );
  const a = authority.data;
  const authorityValid =
    !!a &&
    a.manifest.kind === "authority" &&
    a.manifest.package_id === authorityId &&
    a.manifest.revision_id === authorityRevision &&
    sha.test(a.digest) &&
    Object.keys(m.scope).every(
      (key) =>
        m.scope[key as keyof typeof m.scope] ===
        a.manifest.scope[key as keyof typeof m.scope],
    );
  const rulesValid =
    !!rules.data &&
    uuid.test(rules.data.id) &&
    rules.data.bid_id === bidId &&
    Array.isArray(rules.data.rules) &&
    rules.data.rules.every(
      (r) => r.rule_set_id === rules.data?.id && r.scope.bid_id === bidId,
    );
  const frozen = inventory.data?.manifest;
  const inventoryValid =
    !!frozen &&
    frozen.bid_id === bidId &&
    frozen.package_id === m.package_id &&
    frozen.target_revision_id === m.revision_id &&
    frozen.package_digest === packageView.digest &&
    frozen.id === inventoryId;
  const checked = attempt.data?.manifest;
  const attemptValid =
    inventoryValid &&
    !!checked &&
    checked.bid_id === bidId &&
    checked.inventory_id === inventoryId &&
    checked.id === attemptId &&
    checked.inventory_digest === inventory.data?.digest &&
    checked.package_digest === packageView.digest;
  const locked = disabled || busy || !!pending || recovery.blocked;
  const canCreate =
    supportsApi("POST", base) &&
    !locked &&
    authorityValid &&
    rulesValid &&
    !authority.error &&
    !rules.error &&
    !inventories.error &&
    !inventories.loading &&
    !authority.loading &&
    !rules.loading &&
    !!inventories.data &&
    (!inventories.data.current_inventory_id || !!inventories.etag);

  async function save() {
    if (busy || recovery.blocked || (!pending && (disabled || !canCreate)))
      return;
    const operation: Pending = pending ?? {
      version: 1,
      scope,
      body: {
        authority_revision_id: authorityRevision,
        rule_set_id: rules.data!.id,
        mappings: [],
      },
      key: crypto.randomUUID(),
      etag: inventories.data?.current_inventory_id ? inventories.etag : null,
      ifNoneMatch: inventories.data?.current_inventory_id ? null : "*",
    };
    setBusy(true);
    setFailure(null);
    setNotice("");
    let sent = false;
    try {
      sessionStorage.setItem(storageKey(scope), JSON.stringify(operation));
      setPending(operation);
      sent = true;
      const result = await api<PackageRequirementInventoryView>(base, {
        method: "POST",
        body: operation.body,
        key: operation.key,
        etag: operation.etag,
        ifNoneMatch: operation.ifNoneMatch,
      });
      if (!active.current) return;
      const saved = result.data.manifest;
      if (
        saved.bid_id !== bidId ||
        saved.package_id !== m.package_id ||
        saved.target_revision_id !== m.revision_id ||
        saved.package_digest !== packageView.digest ||
        saved.authority_revision_id !== operation.body.authority_revision_id ||
        saved.rule_set_id !== operation.body.rule_set_id ||
        !sha.test(result.data.digest)
      )
        throw new Error("保存响应身份不一致，保留原操作待核对。");
      sessionStorage.removeItem(storageKey(scope));
      setPending(null);
      setInventoryId(saved.id);
      setAttemptId("");
      setNotice(
        `已保存要求清单修订 ${saved.revision}，所有条款保持未映射；未形成完整覆盖结论。`,
      );
      void inventories.reload();
    } catch (error) {
      if (!active.current) return;
      setFailure(
        sent
          ? error
          : new Error(
              "本地操作记录无法保存，请求尚未发送；请恢复浏览器存储后重试。",
            ),
      );
      if (
        error instanceof ApiError &&
        [409, 412, 422, 428].includes(error.status) &&
        !error.retryable &&
        (!pending ||
          error.code.startsWith("PACKAGE_REQUIREMENT_") ||
          ["REVISION_CONFLICT", "PROJECT_WORK_CLOSED"].includes(error.code))
      ) {
        try {
          sessionStorage.removeItem(storageKey(scope));
          setPending(null);
          void inventories.reload();
        } catch {
          setFailure(new Error("无法清理本地未决记录，保留原操作等待核对。"));
        }
      }
    } finally {
      if (active.current) setBusy(false);
    }
  }

  return (
    <section className="package-requirements" aria-label="整包要求与覆盖">
      <h3>整包要求与覆盖</h3>
      <p>
        本方资料包修订 {m.revision} · {m.members.length}{" "}
        份文件。本工作面固定到当前明确修订，切换包或修订分别读取。
      </p>
      <p role="note">
        历史规则集未冻结完整抽取解析身份。清单完整性未知，尚不可正式审查。人工范围声明不等于系统独立验收或合规结论。
      </p>
      <details>
        <summary>本方冻结身份</summary>
        <p>
          包 {m.package_id} · 修订 {m.revision_id} · SHA256 {packageView.digest}
        </p>
        <p>
          标段 {m.scope.lot_id} · 轮次 {m.scope.round_id} · 主体{" "}
          {m.scope.bidder_id}
        </p>
      </details>
      <fieldset disabled={locked}>
        <legend>建立未映射要求清单</legend>
        <p>
          明确选择权威依据包与修订，仅冻结现有原规则；分类、数量及适用性保持未知。不会自动生成已核验记录。
        </p>
        <p>
          新建清单须使用当前本方修订与当前依据修订；历史修订仍可读取，服务端会核对是否允许新建。
        </p>
        {!!inventories.data?.current_inventory_id && (
          <p>
            当前已有要求清单。本次创建将追加全未映射修订，不沿用原检查计划与覆盖声明；旧版仍保留可读。
          </p>
        )}
        <ResourceState
          {...authorities}
          hasData={!!authorities.data}
          onRetry={() => void authorities.reload()}
        />
        <label>
          权威依据包
          <select
            value={authorityId}
            onChange={(e) => {
              setAuthorityId(e.target.value);
              setAuthorityRevision("");
            }}
          >
            <option value="">请选择依据包</option>
            {authorities.items
              .filter((p) => p.kind === "authority")
              .map((p, i) => (
                <option key={p.id} value={p.id}>
                  依据包 {i + 1} · 当前修订 {p.revision}
                </option>
              ))}
          </select>
        </label>
        {authorities.hasMore && (
          <button
            type="button"
            disabled={authorities.moreBusy}
            onClick={() => void authorities.loadMore()}
          >
            更多依据包
          </button>
        )}
        {!!authorities.moreError && (
          <ErrorNotice
            error={authorities.moreError}
            onRetry={() => void authorities.loadMore()}
          />
        )}
        {authorityId && (
          <>
            <ResourceState
              {...revisions}
              hasData={!!revisions.data}
              onRetry={() => void revisions.reload()}
            />
            <label>
              依据包明确修订
              <select
                value={authorityRevision}
                onChange={(e) => setAuthorityRevision(e.target.value)}
              >
                <option value="">请选择修订，不自动取最新</option>
                {revisions.items.map((p) => (
                  <option key={p.id} value={p.id}>
                    修订 {p.revision} ·{" "}
                    {new Date(p.created_at).toLocaleString()}
                  </option>
                ))}
              </select>
            </label>
            {revisions.hasMore && (
              <button
                type="button"
                onClick={() => void revisions.loadMore()}
                disabled={revisions.moreBusy}
              >
                更多依据修订
              </button>
            )}
            {!!revisions.moreError && (
              <ErrorNotice
                error={revisions.moreError}
                onRetry={() => void revisions.loadMore()}
              />
            )}
          </>
        )}
        {authorityRevision && (
          <ResourceState
            {...authority}
            hasData={!!authority.data}
            onRetry={() => void authority.reload()}
          />
        )}
        {a && !authorityValid && (
          <p role="alert">
            依据包与本方工程、标段、轮次或主体不一致，禁止创建。
          </p>
        )}
        {authorityValid && a && (
          <details>
            <summary>已选依据修订 {a.manifest.revision} 的冻结身份</summary>
            <p>
              {a.manifest.revision_id} · SHA256 {a.digest}
            </p>
          </details>
        )}
        <ResourceState
          {...rules}
          hasData={!!rules.data}
          onRetry={() => void rules.reload()}
        />
        {rulesValid && (
          <p>
            现有规则 {rules.data!.rules.length} 条 · 抽取范围{" "}
            {
              {
                complete: "完整范围",
                partial: "部分范围",
                conflict: "范围冲突",
              }[rules.data!.coverage]
            }
            （不表示整包完整）
          </p>
        )}
        {rules.data && !rulesValid && (
          <p role="alert">规则集精确身份或项目范围不一致，禁止推算或创建。</p>
        )}
        <button
          type="button"
          className="button"
          disabled={!canCreate}
          onClick={() => void save()}
        >
          创建未映射清单
        </button>
      </fieldset>
      {recovery.blocked && (
        <p role="alert">
          本地未决操作记录损坏或范围不符，创建已锁定。请保留记录核对，不能另发新操作。
        </p>
      )}
      {pending && (
        <div role="status">
          <p>
            保存结果未知，已保留原请求、幂等键和版本条件。请重试同一操作或读取历史核对；刷新也会恢复，不能修改成新操作。
          </p>
          <details>
            <summary>待核原操作身份</summary>
            <p>
              依据修订 {pending.body.authority_revision_id} · 规则集{" "}
              {pending.body.rule_set_id}
            </p>
          </details>
          <button type="button" disabled={busy} onClick={() => void save()}>
            重试原清单操作
          </button>
        </div>
      )}
      {!!failure && <ErrorNotice error={failure} />}
      {notice && <p role="status">{notice}</p>}
      <h4>要求清单历史</h4>
      <ResourceState
        {...inventories}
        hasData={!!inventories.data}
        onRetry={() => void inventories.reload()}
      />
      <button type="button" onClick={() => void inventories.reload()}>
        刷新清单历史
      </button>
      {inventories.data && !inventories.items.length && (
        <p>此包修订尚无冻结要求清单；不能据此认定无要求。</p>
      )}
      {inventories.items.map((item, i) => (
        <button
          type="button"
          key={item.id}
          aria-pressed={inventoryId === item.id}
          onClick={() => {
            setInventoryId(item.id);
            setAttemptId("");
          }}
        >
          读取清单 {i + 1} · {new Date(item.created_at).toLocaleString()}
          {inventories.data?.current_inventory_id === item.id
            ? "（当前）"
            : "（历史）"}
        </button>
      ))}
      {inventories.hasMore && (
        <button
          type="button"
          disabled={inventories.moreBusy}
          onClick={() => void inventories.loadMore()}
        >
          更多清单
        </button>
      )}
      {!!inventories.moreError && (
        <ErrorNotice
          error={inventories.moreError}
          onRetry={() => void inventories.loadMore()}
        />
      )}
      {inventoryId && (
        <ResourceState
          {...inventory}
          hasData={!!inventory.data}
          onRetry={() => void inventory.reload()}
        />
      )}
      {inventory.data && !inventoryValid && (
        <p role="alert">清单冻结范围不一致，未展示其他包的条款。</p>
      )}
      {inventoryValid && frozen && (
        <>
          <h4>
            清单修订 {frozen.revision} · {frozen.requirements.length} 条冻结要求
          </h4>
          <details>
            <summary>清单冻结依据及摘要</summary>
            <p>
              清单 {frozen.id} · SHA256 {inventory.data!.digest}
            </p>
            <p>
              依据修订 {frozen.authority_revision_id} · SHA256{" "}
              {frozen.authority_digest}
            </p>
            <p>
              原规则集 {frozen.rule_set_id} · SHA256 {frozen.rule_set_digest}
            </p>
            <p>抽取身份 {frozen.extraction_binding}</p>
            <p>inventory_complete=false · review_ready=false</p>
          </details>
          {frozen.requirements.map((binding, i) => {
            const r = binding.requirement;
            return (
              <article key={binding.rule_id}>
                <h5>
                  要求 {i + 1} ·{" "}
                  {r.categories.map((v) => categories[v] ?? v).join("、")}
                </h5>
                <p>{text(binding.rule_snapshot.statement)}</p>
                <p>
                  来源绑定：
                  {binding.source_bound ? "有精确引用关联" : "未知／未绑定"} ·
                  原规则决定：
                  {decisions[text(binding.decision_snapshot?.decision)] ??
                    "未知／未记录"}{" "}
                  · 人工检查计划：
                  {binding.annotation.mapped ? "已映射" : "未映射"}
                </p>
                <p>
                  数量：{r.minimum_count === null ? "未知" : r.minimum_count} ·
                  适用性：
                  {
                    {
                      unknown: "未知",
                      applicable: "适用",
                      not_applicable: "有据不适用",
                    }[r.applicability]
                  }{" "}
                  · 有效时点：{r.valid_at ?? "未知"}
                </p>
                <p>
                  目标范围：
                  {r.target_part_ids.length
                    ? r.target_part_ids.join("、")
                    : "分类内范围，尚未指定具体页段"}{" "}
                  · 核验项：{r.checks.length ? r.checks.join("、") : "未声明"}
                </p>
                <Conditions
                  value={binding.rule_snapshot.conditions}
                  label="原始条件"
                />
                <Conditions
                  value={binding.rule_snapshot.exceptions}
                  label="原始例外"
                />
                <EvidenceLinks
                  ids={strings(binding.rule_snapshot.evidence_ids)}
                  label={`查看要求 ${i + 1} 的原页依据`}
                />
                <details>
                  <summary>要求及来源身份</summary>
                  <p>
                    {binding.rule_id} · SHA256 {binding.requirement_digest}
                  </p>
                  <p>{r.source_refs.join("；")}</p>
                  <p>
                    适用依据：{r.applicability_evidence.join("；") || "未记录"}
                  </p>
                </details>
              </article>
            );
          })}
          <h4>人工范围声明历史</h4>
          <p>这里可读取已保存的人工核验记录，暂未提供人工核验填写。</p>
          <ResourceState
            {...attempts}
            hasData={!!attempts.data}
            onRetry={() => void attempts.reload()}
          />
          {attempts.data && !attempts.items.length && (
            <p>尚无人工范围声明，所有条款核验状态为未知。</p>
          )}
          {attempts.items.map((item, i) => (
            <button
              type="button"
              key={item.id}
              aria-pressed={attemptId === item.id}
              onClick={() => setAttemptId(item.id)}
            >
              读取范围声明 {i + 1} ·{" "}
              {new Date(item.created_at).toLocaleString()}
            </button>
          ))}
          {attempts.hasMore && (
            <button
              type="button"
              disabled={attempts.moreBusy}
              onClick={() => void attempts.loadMore()}
            >
              更多范围声明
            </button>
          )}
          {!!attempts.moreError && (
            <ErrorNotice
              error={attempts.moreError}
              onRetry={() => void attempts.loadMore()}
            />
          )}
          {attemptId && (
            <ResourceState
              {...attempt}
              hasData={!!attempt.data}
              onRetry={() => void attempt.reload()}
            />
          )}
          {attempt.data && !attemptValid && (
            <p role="alert">范围声明的包、清单或摘要不一致，未显示其他记录。</p>
          )}
          {attemptValid && checked && (
            <>
              <h5>本次人工记录 · 整包完整性仍未知</h5>
              <p>
                完整核验：否 ·
                可正式审查：否。下列状态是人工记录，不是系统验收。
              </p>
              {frozen.requirements.map((r, i) => (
                <p key={r.rule_id}>
                  要求 {i + 1}：
                  {names[
                    checked.assessment.requirement_states[r.rule_id] ??
                      "unknown"
                  ] ?? "未知"}
                </p>
              ))}
              <h6>成员缺口</h6>
              {!checked.assessment.member_gaps.length && (
                <p>本次未记录成员缺口；不代表整包完整。</p>
              )}
              {checked.assessment.member_gaps.map((gap, i) => (
                <div key={i}>
                  <p>
                    {strings(gap.purposes)
                      .map((v) => categories[v] ?? v)
                      .join("、") || `文件 ${i + 1}`}
                    ：
                    {strings(gap.codes)
                      .map((v) => gapNames[v] ?? "有待核对的缺口")
                      .join("、") || "缺口类型待核"}{" "}
                    ·{" "}
                    {typeof gap.reason === "string" ? gap.reason : "原因未记录"}
                  </p>
                  <details>
                    <summary>缺口成员身份</summary>
                    <p>
                      {text(gap.member_id)} · 文件版本{" "}
                      {text(gap.document_version_id)}
                    </p>
                  </details>
                </div>
              ))}
              <h6>本次受检物理范围</h6>
              {!checked.assessment.inspected_ranges.length && (
                <p>未记录受检范围，不能认定已检查。</p>
              )}
              <ul>
                {checked.assessment.inspected_ranges.map((range, i) => (
                  <li key={i}>
                    {text(range.part_id)} · 物理页{" "}
                    {typeof range.first_page === "number"
                      ? range.first_page
                      : "待核"}
                    —
                    {typeof range.last_page === "number"
                      ? range.last_page
                      : "待核"}
                    <details>
                      <summary>受检范围冻结身份</summary>
                      <p>
                        要求 {text(range.requirement_id)} · 文件版本{" "}
                        {text(range.document_version_id)} · 要求摘要{" "}
                        {text(range.requirement_digest)}
                      </p>
                    </details>
                  </li>
                ))}
              </ul>
              {checked.results.map((result) => (
                <div key={result.coverage.requirement_id}>
                  <p>
                    依据类型：
                    {result.basis_type === "human_scope_declaration"
                      ? "人工范围声明"
                      : "人工观察"}{" "}
                    · {result.coverage.reason}
                  </p>
                  <ul>
                    {result.coverage.inspected.map((range, i) => (
                      <li key={i}>
                        {range.part_id} · 物理页 {range.first_page}—
                        {range.last_page}
                      </li>
                    ))}
                  </ul>
                  <EvidenceLinks
                    ids={result.evidence_ids}
                    label="查看本次声明证据"
                  />
                </div>
              ))}
              <details>
                <summary>本次声明冻结身份</summary>
                <p>
                  {checked.id} · SHA256 {attempt.data!.digest}
                </p>
              </details>
            </>
          )}
        </>
      )}
      {!supportsApi("POST", base) && (
        <p>当前服务尚未提供清单创建接口，保留只读历史。</p>
      )}
    </section>
  );
}
