import { useEffect, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import type {
  BidPackageStoredView,
  PackageRequirementInventoryView,
  PackageTechnicalScopeContext,
  PackageTechnicalScopePage,
  PackageTechnicalScopePreview,
  PackageTechnicalScopeRequest,
  PackageTechnicalScopeView,
} from "./contracts";
import { ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { useDirectory } from "./useDirectory";
import { usePackageScopeGuard } from "./packageScopeGuard";
import { usePackageTechnicalScopeCommand } from "./usePackageTechnicalScopeCommand";
import {
  PackageTechnicalScopeSnapshot,
  TechnicalPager,
} from "./PackageTechnicalScopeSnapshot";
import { technicalPartLabel } from "./packageTechnicalScopeLabels";
import { PackageTechnicalEligibility } from "./PackageTechnicalEligibility";
import { PackageTechnicalExecution } from "./PackageTechnicalExecution";
import {
  technicalContextPath,
  technicalDefaultRequest,
  technicalScopePath,
  technicalSelection,
  technicalSame,
  validateTechnicalContext,
  validateTechnicalPreview,
  validateTechnicalView,
  validTechnicalHistory,
  validTechnicalRequest,
  type TechnicalHistoryEntry,
  type TechnicalScope,
} from "./packageTechnicalScopeProtocol";
import "./PackageTechnicalScope.css";

type Props = {
  bidId: string;
  memberId: string;
  packageView: BidPackageStoredView;
  inventory: PackageRequirementInventoryView | null;
  disabled?: boolean;
};
export function PackageTechnicalScope(props: Props) {
  if (!props.inventory) return null;
  let scope: TechnicalScope;
  try {
    scope = technicalSelection(
      props.bidId,
      props.memberId,
      props.packageView,
      props.inventory,
    );
  } catch (error) {
    return <ErrorNotice error={error} />;
  }
  return (
    <TechnicalScopeWorkspace
      key={JSON.stringify(scope)}
      scope={scope}
      disabled={!!props.disabled}
    />
  );
}

function TechnicalScopeWorkspace({
  scope,
  disabled,
}: {
  scope: TechnicalScope;
  disabled: boolean;
}) {
  const command = usePackageTechnicalScopeCommand(scope);
  const [context, setContext] = useState<PackageTechnicalScopeContext | null>(
    null,
  );
  const [request, setRequest] = useState<PackageTechnicalScopeRequest | null>(
    null,
  );
  const [preview, setPreview] = useState<PackageTechnicalScopePreview | null>(
    null,
  );
  const [confirmed, setConfirmed] = useState(false),
    [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null),
    [historyOpen, setHistoryOpen] = useState(false);
  const [historical, setHistorical] =
    useState<PackageTechnicalScopeView | null>(null);
  const [partsPage, setPartsPage] = useState(0),
    [rulesPage, setRulesPage] = useState(0);
  const active = useRef(false),
    running = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const base = technicalScopePath(scope),
    path = `${base}/technical-scopes`;
  const history = useDirectory<PackageTechnicalScopePage>(
    historyOpen ? `${path}?limit=20` : null,
    validTechnicalHistory,
  );
  const dirty =
    !!request &&
    !!context &&
    !technicalSame(request, technicalDefaultRequest(context));
  usePackageScopeGuard(
    `technical-scope:${scope.revisionId}:${scope.inventoryId}`,
    {
      busy: busy || command.busy,
      pending: !!command.pending || command.blocked,
      dirty,
    },
  );
  const locked =
    disabled || busy || command.busy || !!command.pending || command.blocked;
  const currentPreview =
    !!preview && !!request && technicalSame(preview.manifest.request, request);
  const parts =
    context?.target.manifest.members.flatMap((member, memberIndex) =>
      member.parts.map((part) => ({ part, memberIndex })),
    ) ?? [];
  const rules =
    context?.inventory.manifest.requirements.filter(
      (rule) => rule.rule_snapshot.kind === "scoring",
    ) ?? [];

  function change(value: PackageTechnicalScopeRequest) {
    setRequest(value);
    setPreview(null);
    setConfirmed(false);
  }
  async function readContext() {
    if (locked || running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    setPreview(null);
    setConfirmed(false);
    try {
      const response = await api<unknown>(technicalContextPath(scope));
      const value = await validateTechnicalContext(
        response.data,
        response.etag,
        scope,
      );
      if (!active.current) return;
      setContext(value);
      setRequest((old) => old ?? technicalDefaultRequest(value));
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  async function prepare() {
    if (
      locked ||
      running.current ||
      !context?.can_freeze ||
      !request ||
      !validTechnicalRequest(request, scope)
    )
      return;
    running.current = true;
    setBusy(true);
    setError(null);
    setPreview(null);
    setConfirmed(false);
    const captured = structuredClone(request);
    try {
      const response = await api<unknown>(`${base}/technical-scope-previews`, {
        method: "POST",
        body: captured,
      });
      const value = await validateTechnicalPreview(response.data, scope, {
        request: captured,
        context,
        etag: response.etag,
      });
      if (active.current) setPreview(value);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  async function save() {
    if (
      locked ||
      !confirmed ||
      !currentPreview ||
      !preview ||
      !context ||
      !request
    )
      return;
    const result = await command.save({
      body: {
        request: structuredClone(request),
        preview_digest: preview.digest,
      },
      etag: context.etag,
      expected: {
        context_digest: context.context_digest,
        method_digest: context.method.digest,
      },
    });
    if (!active.current) return;
    setPreview(null);
    setConfirmed(false);
    if (result) {
      setRequest(technicalDefaultRequest(context));
      if (historyOpen) void history.reload();
    }
  }
  async function recover() {
    const result = await command.retry();
    if (active.current && result) {
      setPreview(null);
      setConfirmed(false);
      if (context) setRequest(technicalDefaultRequest(context));
      if (historyOpen) void history.reload();
    }
  }
  async function readHistory(entry: TechnicalHistoryEntry) {
    if (busy || running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    setHistorical(null);
    try {
      const response = await api<unknown>(`${path}/${entry.id}`);
      const value = await validateTechnicalView(
        response.data,
        response.etag,
        scope,
        entry,
      );
      if (active.current) setHistorical(value);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  function selectPart(id: string, selected: boolean) {
    if (!request) return;
    change({
      ...request,
      technical_part_ids: selected
        ? [...request.technical_part_ids, id]
        : request.technical_part_ids.filter((value) => value !== id),
      rule_scopes: request.rule_scopes.map((rule) =>
        selected
          ? rule
          : {
              ...rule,
              part_ids: rule.part_ids.filter((value) => value !== id),
            },
      ),
    });
  }
  function updateRule(
    id: string,
    values: Partial<PackageTechnicalScopeRequest["rule_scopes"][number]>,
  ) {
    if (request)
      change({
        ...request,
        rule_scopes: request.rule_scopes.map((rule) =>
          rule.rule_id === id ? { ...rule, ...values } : rule,
        ),
      });
  }
  return (
    <section className="technical-scope card" aria-label="施组评分范围">
      <header>
        <h3>施组评分范围</h3>
        <p>
          明确选择施组正文、附表和适用评分条款，核对原页后保存本次范围。读取与保存均不启动模型。
        </p>
      </header>
      <div className="technical-scope__actions">
        <button
          type="button"
          disabled={locked || !supportsApi("GET", technicalContextPath(scope))}
          onClick={() => void readContext()}
        >
          {context ? "重新读取范围依据" : "读取技术范围依据"}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            setHistoryOpen(true);
            if (historyOpen) void history.reload();
          }}
        >
          读取已保存范围
        </button>
      </div>
      {busy && <p role="status">正在核对技术范围…</p>}
      {error != null && <ErrorNotice error={error} />}
      {command.error != null && <ErrorNotice error={command.error} />}
      {command.pending && (
        <div className="notice" role="status">
          <p>
            上次保存回执尚未确认，原请求已保留。恢复时继续使用原选择与版本。
          </p>
          <button
            type="button"
            disabled={command.busy || command.blocked}
            onClick={() => void recover()}
          >
            恢复原技术范围请求
          </button>
        </div>
      )}
      {command.busy && <p role="status">正在核验原件并保存范围…</p>}
      {context && request && (
        <>
          {!context.can_freeze && (
            <div role="alert">
              <p>当前依据不允许保存新的技术范围：</p>
              <ul>
                {context.blocking_reasons.map((reason) => (
                  <li key={reason.id}>{reason.message}</li>
                ))}
              </ul>
            </div>
          )}
          <fieldset disabled={locked || !context.can_freeze}>
            <legend>1. 选择要纳入的完整页段</legend>
            <p>
              已选 {request.technical_part_ids.length}{" "}
              个页段。跨册附表须明确纳入；本次不会自动选择所有技术附件。
            </p>
            <div className="technical-scope__parts">
              {parts
                .slice(partsPage * 20, (partsPage + 1) * 20)
                .map(({ part, memberIndex }) => (
                  <label key={part.part_id}>
                    <input
                      type="checkbox"
                      checked={request.technical_part_ids.includes(
                        part.part_id,
                      )}
                      onChange={(event) =>
                        selectPart(part.part_id, event.target.checked)
                      }
                    />
                    {technicalPartLabel(part, memberIndex)}
                  </label>
                ))}
            </div>
          </fieldset>
          {parts.length > 20 && (
            <TechnicalPager
              page={partsPage}
              total={parts.length}
              onPage={setPartsPage}
              label="页段"
            />
          )}
          <fieldset disabled={locked || !context.can_freeze}>
            <legend>2. 逐项确认评分条款与页段</legend>
            {!rules.length && (
              <p>当前要求清单没有评分条款，不能据此认定施组无需评分。</p>
            )}
            {rules
              .slice(rulesPage * 20, (rulesPage + 1) * 20)
              .map((row, index) => {
                const choice = request.rule_scopes.find(
                  (rule) => rule.rule_id === row.rule_id,
                )!;
                const ordinal = rulesPage * 20 + index + 1;
                return (
                  <article className="technical-scope__rule" key={row.rule_id}>
                    <h4>评分条款 {ordinal}</h4>
                    <p>
                      {typeof row.rule_snapshot.statement === "string"
                        ? row.rule_snapshot.statement
                        : "未记录原条款文字"}
                    </p>
                    <label>
                      条款 {ordinal} 的范围判断
                      <select
                        aria-label={`条款 ${ordinal} 的范围判断`}
                        value={choice.selection}
                        onChange={(event) => {
                          const selection = event.target
                            .value as typeof choice.selection;
                          updateRule(row.rule_id, {
                            selection,
                            part_ids:
                              selection === "include" ? choice.part_ids : [],
                          });
                        }}
                      >
                        <option value="unclassified">尚未归类</option>
                        <option
                          value="include"
                          disabled={
                            row.rule_snapshot.provenance_status !== "effective"
                          }
                        >
                          纳入本次技术范围
                        </option>
                        <option value="exclude">明确排除</option>
                      </select>
                    </label>
                    {choice.selection === "include" && (
                      <fieldset>
                        <legend>条款 {ordinal} 关联的已选页段</legend>
                        {!request.technical_part_ids.length && (
                          <p>请先选择上方页段。</p>
                        )}
                        {parts
                          .filter(({ part }) =>
                            request.technical_part_ids.includes(part.part_id),
                          )
                          .map(({ part, memberIndex }) => (
                            <label key={part.part_id}>
                              <input
                                type="checkbox"
                                checked={choice.part_ids.includes(part.part_id)}
                                onChange={(event) =>
                                  updateRule(row.rule_id, {
                                    part_ids: event.target.checked
                                      ? [...choice.part_ids, part.part_id]
                                      : choice.part_ids.filter(
                                          (id) => id !== part.part_id,
                                        ),
                                  })
                                }
                              />
                              {technicalPartLabel(part, memberIndex)}
                            </label>
                          ))}
                      </fieldset>
                    )}
                    <label>
                      条款 {ordinal} 的选择理由
                      <textarea
                        maxLength={2000}
                        value={choice.reason}
                        onChange={(event) =>
                          updateRule(row.rule_id, {
                            reason: event.target.value,
                          })
                        }
                      />
                    </label>
                  </article>
                );
              })}
          </fieldset>
          {rules.length > 20 && (
            <TechnicalPager
              page={rulesPage}
              total={rules.length}
              onPage={setRulesPage}
              label="评分项"
            />
          )}
          <label>
            本次范围说明
            <textarea
              maxLength={2000}
              disabled={locked || !context.can_freeze}
              value={request.reason}
              onChange={(event) =>
                change({ ...request, reason: event.target.value })
              }
            />
          </label>
          <button
            type="button"
            disabled={
              locked ||
              !context.can_freeze ||
              !validTechnicalRequest(request, scope)
            }
            onClick={() => void prepare()}
          >
            预览技术范围与缺口
          </button>
          {currentPreview && preview && (
            <>
              <PackageTechnicalScopeSnapshot
                key={preview.digest}
                value={preview}
                title="待保存的技术范围"
              />
              <label className="technical-scope__confirmation">
                <input
                  type="checkbox"
                  disabled={locked}
                  checked={confirmed}
                  onChange={(event) => setConfirmed(event.target.checked)}
                />
                我已核对本次选择与缺口，确认保存为范围记录。
              </label>
              <button
                type="button"
                disabled={locked || !confirmed || !supportsApi("POST", path)}
                onClick={() => void save()}
              >
                确认保存技术范围
              </button>
            </>
          )}
        </>
      )}
      {command.result && (
        <div>
          <p role="status">技术范围已保存，原件字节已在登记时核验。</p>
          <PackageTechnicalScopeSnapshot
            key={command.result.digest}
            value={command.result.manifest.preview}
            title="本次已保存范围"
          />
          <PackageTechnicalEligibility saved={command.result} />
          <PackageTechnicalExecution saved={command.result} />
        </div>
      )}
      {historyOpen && (
        <section aria-label="技术范围历史">
          <h4>已保存范围</h4>
          <ResourceState
            {...history}
            hasData={!!history.data}
            onRetry={() => void history.reload()}
          />
          {history.data && !history.items.length && (
            <p>此包修订尚无技术范围记录。</p>
          )}
          {history.items.map((entry) => (
            <button
              type="button"
              key={entry.id}
              disabled={busy}
              onClick={() => void readHistory(entry)}
            >
              {new Date(entry.created_at).toLocaleString()} ·{" "}
              {entry.selected_part_count} 个页段 · {entry.included_rule_count}{" "}
              项条款
            </button>
          ))}
          {history.hasMore && (
            <button
              type="button"
              disabled={history.moreBusy}
              onClick={() => void history.loadMore()}
            >
              更多范围记录
            </button>
          )}
          {history.moreError != null && (
            <ErrorNotice
              error={history.moreError}
              onRetry={() => void history.loadMore()}
            />
          )}
          {historical && (
            <>
              <p>以下为原记录，后续来源变化不会改写当时内容。</p>
              <PackageTechnicalScopeSnapshot
                key={historical.digest}
                value={historical.manifest.preview}
                title="历史技术范围"
              />
              <PackageTechnicalEligibility saved={historical} />
              <PackageTechnicalExecution saved={historical} />
            </>
          )}
        </section>
      )}
    </section>
  );
}
