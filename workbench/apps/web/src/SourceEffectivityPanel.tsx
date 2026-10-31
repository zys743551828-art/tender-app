import { useState } from "react";
import type {
  Bid,
  DocumentEvidenceView,
  RuleSetView,
  SourceEffectivityView,
  SourceEffectivityRequest,
} from "./contracts";
import { supportsApi } from "./api";
import { ErrorNotice } from "./components";
import { EvidenceLinks } from "./EvidenceLinks";
import { ResourceState } from "./ResourceState";
import { useRecordedCommand } from "./useRecordedCommand";
import { useResource } from "./useResource";
import "./SourceEffectivityPanel.css";

type View = SourceEffectivityView;
type Body = SourceEffectivityRequest & {
  action: "partial_replace";
  new_document_version_id: string;
  additions: never[];
  acknowledged_ambiguity_ids: string[];
};
const hex = /^[a-f0-9]{64}$/;
const strings = (v: unknown): v is string[] =>
  Array.isArray(v) && v.every((x) => typeof x === "string" && x.length > 0);
function pendingValid(
  request: { path: string; body: unknown; method?: string },
  path: string,
) {
  if (
    request.path !== path ||
    (request.method && request.method !== "POST") ||
    !request.body ||
    typeof request.body !== "object"
  )
    return false;
  const b = request.body as Body;
  return (
    Object.keys(b).sort().join(",") ===
      "acknowledged_ambiguity_ids,action,additions,base_rule_set_id,new_document_version_id,old_document_version_id,reason,rule_ids,scope_basis" &&
    b.action === "partial_replace" &&
    typeof b.base_rule_set_id === "string" &&
    !!b.base_rule_set_id &&
    typeof b.old_document_version_id === "string" &&
    !!b.old_document_version_id &&
    typeof b.new_document_version_id === "string" &&
    !!b.new_document_version_id &&
    b.old_document_version_id !== b.new_document_version_id &&
    strings(b.rule_ids) &&
    b.rule_ids.length > 0 &&
    b.rule_ids.length <= 500 &&
    new Set(b.rule_ids).size === b.rule_ids.length &&
    strings(b.acknowledged_ambiguity_ids) &&
    b.acknowledged_ambiguity_ids.length > 0 &&
    b.acknowledged_ambiguity_ids.every((id) => hex.test(id)) &&
    new Set(b.acknowledged_ambiguity_ids).size ===
      b.acknowledged_ambiguity_ids.length &&
    Array.isArray(b.additions) &&
    b.additions.length === 0 &&
    typeof b.reason === "string" &&
    !!b.reason.trim() &&
    b.reason.length <= 2000 &&
    Array.isArray(b.scope_basis) &&
    b.scope_basis.length > 0 &&
    b.scope_basis.length <= 100 &&
    b.scope_basis.every(
      (q) =>
        q &&
        typeof q.evidence_id === "string" &&
        !!q.evidence_id &&
        typeof q.quote === "string" &&
        !!q.quote.trim() &&
        q.quote.length <= 20000,
    )
  );
}

export function SourceEffectivityPanel(props: {
  bid: Bid;
  memberId: string;
  onChanged: () => void;
}) {
  return (
    <SourceEffectivityForm
      key={`${props.memberId}:${props.bid.id}`}
      {...props}
    />
  );
}

function SourceEffectivityForm({
  bid,
  memberId,
  onChanged,
}: {
  bid: Bid;
  memberId: string;
  onChanged: () => void;
}) {
  const path = `/bids/${bid.id}/source-effectivity`;
  const decisionPath = `/bids/${bid.id}/source-effectivity-decisions`;
  const resource = useResource<View>(path);
  const rules = useResource<RuleSetView>(`/bids/${bid.id}/rules`);
  const [base, setBase] = useState<{ etag: string; ruleSet: string } | null>(
    null,
  );
  const [oldId, setOldId] = useState("");
  const [newId, setNewId] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [acknowledged, setAcknowledged] = useState<string[]>([]);
  const [quotes, setQuotes] = useState<
    { evidence_id: string; quote: string }[]
  >([]);
  const [reason, setReason] = useState("");
  const [newReviewed, setNewReviewed] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [saved, setSaved] = useState(false);
  const evidence = useResource<DocumentEvidenceView>(
    newId ? `/documents/${newId}/evidence` : null,
  );
  const command = useRecordedCommand(
    `source-effectivity:${memberId}:${bid.id}`,
    ({ data }) => {
      const result = data as RuleSetView;
      if (
        !result ||
        result.bid_id !== bid.id ||
        typeof result.id !== "string" ||
        result.material_revision !== bid.material_revision ||
        !Array.isArray(result.rules) ||
        result.rules.some((r) => r.scope?.bid_id !== bid.id)
      )
        throw new Error("来源核对回执身份不一致，请保留原请求并核对。");
    },
  );
  const view = resource.data;
  const validView =
    !!view &&
    view.bid_id === bid.id &&
    Array.isArray(view.sources) &&
    Array.isArray(view.rules) &&
    Array.isArray(view.ambiguities) &&
    view.ambiguities.length > 0 &&
    view.ambiguities.every(
      (a) => hex.test(a.id) && typeof a.text === "string",
    ) &&
    new Set(view.ambiguities.map((a) => a.id)).size === view.ambiguities.length;
  const current =
    validView &&
    !!memberId &&
    !!rules.data &&
    rules.data.bid_id === bid.id &&
    rules.data.coverage === "conflict" &&
    rules.data.material_revision === bid.material_revision &&
    rules.data.id === view.rule_set_id;
  const busy = command.busy || !!command.pending;
  const ready =
    current &&
    view.ambiguity_resolution_available === true &&
    !!resource.etag &&
    !resource.loading &&
    !resource.error &&
    !rules.loading &&
    !rules.error &&
    supportsApi("POST", decisionPath);
  const stale =
    !!base &&
    (base.etag !== resource.etag ||
      base.ruleSet !== view?.rule_set_id ||
      !current);
  const oldSource = view?.sources?.find(
    (s) => s.document_version_id === oldId && s.roles.includes("tender"),
  );
  const newSource = view?.sources?.find(
    (s) =>
      s.document_version_id === newId &&
      s.current &&
      s.roles.includes("supplement"),
  );
  const affected = oldSource
    ? view!.rules.filter(
        (r) =>
          r.provenance_status !== "superseded" &&
          r.evidence_ids.some((id) => oldSource.evidence_ids.includes(id)),
      )
    : [];
  const newRulesPresent =
    !!newSource &&
    view!.rules.some(
      (r) =>
        r.provenance_status !== "superseded" &&
        !selected.includes(r.id) &&
        r.evidence_ids.some((id) => newSource.evidence_ids.includes(id)),
    );
  const evidenceCurrent =
    evidence.data?.document_version_id === newId && !!newSource;
  const eligibleEvidence = evidenceCurrent
    ? evidence.data!.items.filter(
        (e) =>
          e.document_version_id === newId &&
          newSource!.evidence_ids.includes(e.id) &&
          e.source_status === "published",
      )
    : [];
  const validQuotes =
    quotes.length > 0 &&
    quotes.length <= 100 &&
    quotes.every(
      (q) =>
        q.quote.length <= 20000 &&
        eligibleEvidence.some(
          (e) =>
            e.id === q.evidence_id &&
            !!q.quote.trim() &&
            e.quote.includes(q.quote.trim()),
        ),
    );
  const allAcknowledged =
    validView &&
    acknowledged.length === view.ambiguities.length &&
    view.ambiguities.every((a) => acknowledged.includes(a.id));
  const canSubmit =
    !!base &&
    ready &&
    !stale &&
    !busy &&
    !command.error &&
    !!oldSource &&
    !!newSource &&
    oldId !== newId &&
    selected.length > 0 &&
    selected.length <= 500 &&
    selected.every((id) => affected.some((r) => r.id === id)) &&
    allAcknowledged &&
    validQuotes &&
    !evidence.loading &&
    !evidence.error &&
    newRulesPresent &&
    newReviewed &&
    !!reason.trim();
  function reset() {
    setOldId("");
    setNewId("");
    setSelected([]);
    setAcknowledged([]);
    setQuotes([]);
    setReason("");
    setNewReviewed(false);
    setConfirm(false);
  }
  function start() {
    if (!ready || busy) return;
    reset();
    command.clearError();
    setSaved(false);
    setBase({ etag: resource.etag!, ruleSet: view!.rule_set_id! });
  }
  async function refresh() {
    if (busy) return;
    setConfirm(false);
    await Promise.all([resource.reload(), rules.reload()]);
  }
  function accept(result: unknown) {
    if (!result) return;
    setBase(null);
    reset();
    setSaved(true);
    onChanged();
    window.dispatchEvent(new Event("server-snapshot-change"));
  }
  if (
    view &&
    Array.isArray(view.ambiguities) &&
    view.ambiguities.length === 0 &&
    !base &&
    !command.pending &&
    !saved
  )
    return null;
  return (
    <section
      className="panel source-effectivity-panel"
      aria-label="补遗来源消歧"
    >
      <div className="section-heading">
        <h2>补遗来源核对</h2>
        <button
          className="text-button"
          disabled={busy || resource.loading}
          onClick={() => void refresh()}
        >
          重新读取来源
        </button>
      </div>
      <p className="muted">
        只局部结束所选旧条款，其余条款保留。请逐项核对补遗范围；“其他条款不变”不能作为整份替代。保存不等于正式签收，后续复评须明确发起。
      </p>
      <ResourceState
        {...resource}
        hasData={!!view}
        onRetry={() => void refresh()}
      />
      <ResourceState
        {...rules}
        hasData={!!rules.data}
        onRetry={() => void refresh()}
      />
      {view && !validView && (
        <p className="notice warning">
          当前来源信息不支持明确消歧，请重新读取后核对。
        </p>
      )}
      {validView && !view.ambiguity_resolution_available && (
        <p className="notice warning">
          当前不能提交消歧，请先核对材料解析与条款来源，再重新读取。
        </p>
      )}
      {!base && validView && (
        <button
          className="button secondary"
          disabled={!ready || busy}
          onClick={start}
        >
          开始逐项核对
        </button>
      )}
      {base && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (canSubmit) setConfirm(true);
          }}
        >
          {stale && (
            <p role="alert" className="notice warning">
              来源或条款已变化。已填写内容保留，请读取最新来源并重新选择，不能自动套用旧确认。
            </p>
          )}
          {command.conflict && (
            <p role="alert" className="notice warning">
              保存时来源已变化，请重新读取；不会自动重发或更换依据。
            </p>
          )}
          {(stale || !!command.error) && (
            <button
              type="button"
              className="button secondary"
              disabled={!ready || busy}
              onClick={start}
            >
              重新核对当前来源
            </button>
          )}
          <fieldset disabled={busy || !ready || stale || !!command.error}>
            <legend>选择局部替代范围</legend>
            <label>
              旧招标文件
              <select
                value={oldId}
                onChange={(e) => {
                  setOldId(e.target.value);
                  setSelected([]);
                  setAcknowledged([]);
                  setConfirm(false);
                }}
              >
                <option value="">请选择</option>
                {view?.sources
                  .filter((s) => s.roles.includes("tender"))
                  .map((s) => (
                    <option
                      key={s.document_version_id}
                      value={s.document_version_id}
                    >
                      {s.original_name}
                    </option>
                  ))}
              </select>
            </label>
            {oldSource && (
              <EvidenceLinks
                ids={oldSource.evidence_ids}
                label="查看旧招标原页"
              />
            )}
            <label>
              新补遗文件
              <select
                value={newId}
                onChange={(e) => {
                  setNewId(e.target.value);
                  setQuotes([]);
                  setAcknowledged([]);
                  setNewReviewed(false);
                  setConfirm(false);
                }}
              >
                <option value="">请选择</option>
                {view?.sources
                  .filter(
                    (s) =>
                      s.current &&
                      s.roles.includes("supplement") &&
                      s.document_version_id !== oldId,
                  )
                  .map((s) => (
                    <option
                      key={s.document_version_id}
                      value={s.document_version_id}
                    >
                      {s.original_name}
                    </option>
                  ))}
              </select>
            </label>
            {newSource && (
              <EvidenceLinks
                ids={newSource.evidence_ids}
                label="查看补遗原页"
              />
            )}
            <fieldset>
              <legend>仅选择受影响的旧条款</legend>
              {affected.map((r) => (
                <label key={r.id} className="source-effectivity-choice">
                  <input
                    type="checkbox"
                    checked={selected.includes(r.id)}
                    onChange={(e) => {
                      setSelected((v) =>
                        e.target.checked
                          ? [...v, r.id]
                          : v.filter((id) => id !== r.id),
                      );
                      setConfirm(false);
                    }}
                  />
                  {r.statement}
                </label>
              ))}
              {oldSource && affected.length === 0 && (
                <p>该旧文件没有可关联的当前条款，不能凭空选择。</p>
              )}
            </fieldset>
            {newSource && !newRulesPresent && (
              <p className="notice warning">
                补遗的新要求尚未列入当前条款。请先使用下方“补充并确认条款”入口处理，再回来核对；此处不会自动创建新要求。
              </p>
            )}
            <label className="source-effectivity-choice">
              <input
                type="checkbox"
                checked={newReviewed}
                onChange={(e) => {
                  setNewReviewed(e.target.checked);
                  setConfirm(false);
                }}
              />
              我已核对补遗新要求已进入当前条款，未列出的要求应先补充。
            </label>
            <fieldset>
              <legend>逐条核对歧义（全部须明确确认）</legend>
              {view?.ambiguities.map((a) => (
                <label key={a.id} className="source-effectivity-choice">
                  <input
                    type="checkbox"
                    checked={acknowledged.includes(a.id)}
                    onChange={(e) => {
                      setAcknowledged((v) =>
                        e.target.checked
                          ? [...v, a.id]
                          : v.filter((id) => id !== a.id),
                      );
                      setConfirm(false);
                    }}
                  />
                  {a.text}
                </label>
              ))}
            </fieldset>
            {newId && (
              <ResourceState
                {...evidence}
                hasData={evidenceCurrent}
                onRetry={() => void evidence.reload()}
              />
            )}
            <fieldset>
              <legend>补遗原页逐字引用</legend>
              {eligibleEvidence.map((item) => {
                const quote = quotes.find((q) => q.evidence_id === item.id);
                return (
                  <div key={item.id}>
                    <label className="source-effectivity-choice">
                      <input
                        type="checkbox"
                        checked={!!quote}
                        onChange={(e) => {
                          setQuotes((v) =>
                            e.target.checked
                              ? [
                                  ...v,
                                  { evidence_id: item.id, quote: item.quote },
                                ]
                              : v.filter((q) => q.evidence_id !== item.id),
                          );
                          setConfirm(false);
                        }}
                      />
                      物理页 {item.physical_page}：{item.quote}
                    </label>
                    {quote && (
                      <label>
                        引用原文（须与该证据逐字对应）
                        <textarea
                          maxLength={20000}
                          value={quote.quote}
                          onChange={(e) => {
                            const value = e.target.value;
                            // textarea exposes LF; restore only an exact substring
                            // of this evidence, without normalizing its other text.
                            const exact = [
                              value,
                              value.replace(/\n/g, "\r\n"),
                              value.replace(/\n/g, "\r"),
                            ].find((candidate) =>
                              item.quote.includes(candidate),
                            );
                            setQuotes((v) =>
                              v.map((q) =>
                                q.evidence_id === item.id
                                  ? { ...q, quote: exact ?? value }
                                  : q,
                              ),
                            );
                            setConfirm(false);
                          }}
                        />
                      </label>
                    )}
                  </div>
                );
              })}
            </fieldset>
            <label>
              局部替代的核对理由
              <textarea
                required
                maxLength={2000}
                value={reason}
                onChange={(e) => {
                  setReason(e.target.value);
                  setConfirm(false);
                }}
              />
            </label>
            <div className="review-shortcuts">
              <button className="button primary" disabled={!canSubmit}>
                核对本次局部变更
              </button>
              <button
                type="button"
                className="button secondary"
                onClick={() => {
                  reset();
                  setBase(null);
                }}
              >
                取消本次核对
              </button>
            </div>
            {confirm && (
              <div className="notice warning">
                <p>
                  将局部结束已选 {selected.length}{" "}
                  条旧要求，保留其余条款；保存全部歧义的明确确认，不自动补充要求或启动复评。
                </p>
                <button
                  type="button"
                  className="button primary"
                  disabled={!canSubmit}
                  onClick={() => {
                    if (!canSubmit) return;
                    const body: Body = {
                      base_rule_set_id: base.ruleSet,
                      action: "partial_replace",
                      old_document_version_id: oldId,
                      new_document_version_id: newId,
                      rule_ids: selected,
                      scope_basis: quotes.map((q) => ({
                        ...q,
                        quote: q.quote.trim(),
                      })),
                      additions: [],
                      reason: reason.trim(),
                      acknowledged_ambiguity_ids: view!.ambiguities.map(
                        (a) => a.id,
                      ),
                    };
                    void command
                      .run<RuleSetView>(decisionPath, body, base.etag)
                      .then(accept);
                  }}
                >
                  确认保存局部变更
                </button>
                <button
                  type="button"
                  className="text-button"
                  onClick={() => setConfirm(false)}
                >
                  返回修改
                </button>
              </div>
            )}
          </fieldset>
        </form>
      )}
      <ErrorNotice error={command.error} />
      {command.pending && (
        <div className="notice warning">
          <p>原请求结果未确认，请恢复同一请求；不要另建变更或用新来源重发。</p>
          {!pendingValid(command.pending, decisionPath) && (
            <p role="alert">
              恢复记录与当前操作不一致，已阻止发送，请核对原项目记录。
            </p>
          )}
          <button
            className="button secondary"
            disabled={
              command.busy || !pendingValid(command.pending, decisionPath)
            }
            onClick={() => void command.retry<RuleSetView>().then(accept)}
          >
            恢复原来源核对回执
          </button>
        </div>
      )}
      {saved && (
        <p className="notice neutral" role="status">
          已记录局部来源核对。请查看最新条款及剩余缺口，必要时明确发起复评；这不是正式业务签收。
        </p>
      )}
    </section>
  );
}
