import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { Badge, ErrorNotice, Loading } from "./components";
import { EvidenceLinks } from "./EvidenceLinks";
import { useRecordedCommand } from "./useRecordedCommand";
import { useResource } from "./useResource";
import { businessStages } from "./businessNames";
import {
  executionId,
  exactKeys,
  recordObject,
} from "./executionInputValidation";
import type {
  PackageRetrospectiveApplied,
  PackageRetrospectiveDetail,
  PackageRetrospectiveKnowledgeApplied,
  PackageRetrospectiveNotes,
  PackageRetrospectivePage,
  PackageRetrospectivePreview,
  PackageRetrospectiveSelection,
  PackageRetrospectiveView,
} from "./packageRetrospectiveContracts";
import {
  retrospectiveBase,
  retrospectiveTag,
  readRetrospectiveText,
  validateRetrospectiveAck,
  validateRetrospectiveChoices,
  validateRetrospectiveDetail,
  validateRetrospectiveHistory,
  validateRetrospectiveKnowledgeAck,
  validateRetrospectivePreview,
  validRetrospectiveSelection,
} from "./packageRetrospectiveProtocol";
import "./PackageRetrospectives.css";

type Props = {
  bidId: string;
  memberId: string;
  onKnowledgeCreated?: (knowledgeId: string) => void;
};
type Draft = {
  title: string;
  selection: PackageRetrospectiveSelection;
  notes: PackageRetrospectiveNotes;
};
type ChoiceKind = "submissions" | "outcomes" | "business_results" | "runs";

function Choice({
  bidId,
  submissionId = null,
  kind,
  label,
  value,
  onChange,
  disabled = false,
}: {
  bidId: string;
  submissionId?: string | null;
  kind: ChoiceKind;
  label: string;
  value: string | null;
  onChange: (id: string | null) => void;
  disabled?: boolean;
}) {
  const [offset, setOffset] = useState(0);
  const query = new URLSearchParams({ kind, offset: String(offset) });
  if (submissionId) query.set("submission_id", submissionId);
  const resource = useResource<unknown>(
    `${retrospectiveBase(bidId)}/choices?${query}`,
  );
  const checked = useMemo(() => {
    if (!resource.data) return null;
    try {
      return {
        value: validateRetrospectiveChoices(
          resource.data,
          bidId,
          kind,
          submissionId,
        ),
        error: null,
      };
    } catch (error) {
      return { value: null, error };
    }
  }, [resource.data, bidId, kind, submissionId]);
  const options = checked?.value?.items ?? [];
  return (
    <div className="retrospective-choice">
      <label>
        {label}
        <select
          aria-label={label}
          value={value ?? ""}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value || null)}
        >
          <option value="">
            {kind === "submissions"
              ? "请明确选择实际提交"
              : "尚未选择／资料待补"}
          </option>
          {value && !options.some((v) => v.id === value) && (
            <option value={value}>已保留选择 · {value}</option>
          )}
          {options.map((v) => (
            <option key={v.id} value={v.id}>
              {v.current === false ? "历史 · " : ""}
              {v.label}
            </option>
          ))}
        </select>
      </label>
      {resource.loading && <small role="status">正在读取可选记录…</small>}
      {resource.unavailable && (
        <p>复盘服务尚未提供，已保存的输入可稍后恢复。</p>
      )}
      {!!(resource.error || checked?.error) && (
        <ErrorNotice
          error={resource.error || checked?.error}
          onRetry={() => void resource.reload()}
        />
      )}
      {checked?.value && !options.length && (
        <small>此页没有可选记录，可保留待补说明后继续整理。</small>
      )}
      <div className="retrospective-paging">
        {offset > 0 && (
          <button
            type="button"
            className="text-button"
            onClick={() => setOffset(Math.max(0, offset - 30))}
          >
            上一页{label}
          </button>
        )}
        {checked?.value?.next_offset != null && (
          <button
            type="button"
            className="text-button"
            onClick={() => setOffset(checked.value!.next_offset!)}
          >
            下一页{label}
          </button>
        )}
      </div>
    </div>
  );
}

function Summary({ value }: { value: PackageRetrospectivePreview }) {
  const p = value.manifest,
    s = p.submission,
    outcome = p.outcome;
  const comparison = p.comparison?.manifest;
  const [page, setPage] = useState(0);
  const scoreKind = {
    technical_total: "技术总分",
    overall_total: "综合总分",
    unknown: "成绩口径未知",
  };
  const verification = {
    pending: "待核验",
    verified: "已核验",
    conflict: "存在冲突",
    rejected: "核验未成立",
  };
  const verdicts = {
    satisfied: "符合",
    violated: "不符合",
    not_found: "未找到响应",
    unable_to_judge: "无法判断",
    not_applicable: "不适用",
  };
  const humanStates = {
    confirmed: "成员确认",
    rejected: "成员否定",
    needs_review: "待进一步核对",
  };
  return (
    <section className="retrospective-summary" aria-label="复盘依据快照">
      <h4>这次复盘固定的依据</h4>
      <p>
        <strong>{s.identity.engineering_title}</strong> ·{" "}
        {s.identity.lot ?? "标段未注明"} · 第 {s.identity.round_no} 轮 ·{" "}
        {s.identity.bidder_name}
      </p>
      <p>
        实际提交：{new Date(s.submitted_at).toLocaleString()}{" "}
        <Badge tone="warning">
          {s.current ? "当前实交记录" : "历史实交记录"}
        </Badge>
      </p>
      <details>
        <summary>核对实交与包身份</summary>
        <dl>
          <dt>实交记录</dt>
          <dd>{s.id}</dd>
          <dt>投标包修订</dt>
          <dd>{s.revision_id}</dd>
          <dt>实交绑定摘要</dt>
          <dd>{s.binding_digest}</dd>
          <dt>登记风险观察时间</dt>
          <dd>{s.registration_assessed_at}</dd>
        </dl>
        <p>登记时的风险观察不冒充提交前检查，也不证明风险已经解决。</p>
      </details>
      {outcome ? (
        <div className="retrospective-result">
          <h4>{scoreKind[outcome.score_kind]}</h4>
          <p>
            <strong>{outcome.value ?? "未知"}</strong> /{" "}
            {outcome.maximum ?? "满分未知"} ·{" "}
            {verification[outcome.verification]}
            {!outcome.current ? " · 历史结果" : ""}
          </p>
          <p>总分不提供逐项扣分原因；原因仍待官方逐项资料核对。</p>
          {outcome.aggregation && <p>聚合口径：{outcome.aggregation}</p>}
          {outcome.evidence_refs.map((reference) => (
            <blockquote key={reference.evidence_id}>
              <p>{reference.quote}</p>
              <cite>官方原件 · 物理页 {reference.physical_page}</cite>
            </blockquote>
          ))}
          <EvidenceLinks
            ids={outcome.evidence_refs.map((ref) => ref.evidence_id)}
            label="查看官方引用原页"
          />
        </div>
      ) : (
        <p>官方成绩待补：{p.selection.outcome_missing_reason}</p>
      )}
      {p.business_result ? (
        <p>
          业务阶段原记录：{businessStages[p.business_result.stage]} ·{" "}
          {verification[p.business_result.verification]}
          。阶段与技术总分独立核验。
        </p>
      ) : (
        <p>业务阶段待补：{p.selection.business_result_missing_reason}</p>
      )}
      {comparison ? (
        <details>
          <summary>
            两轮核查差异：{comparison.counts.verdict_changed} 条判断变化
          </summary>
          <p>
            新增要求 {comparison.counts.added}，移除 {comparison.counts.removed}
            ，定义变更 {comparison.counts.changed}
            。判断或人工处置改变不等于风险已解决。
          </p>
          {comparison.input_changes.method && (
            <p className="notice warning">
              两轮方法不同，差异不能直接解释为整改效果。
            </p>
          )}
          <div className="retrospective-difference-list">
            {comparison.items.slice(page * 20, (page + 1) * 20).map((row) => (
              <article key={row.requirement_id}>
                <h5>
                  {row.right?.requirement_statement ??
                    row.left?.requirement_statement}
                </h5>
                <p>
                  原判断：
                  {row.left ? verdicts[row.left.verdict] : "本轮无此要求"}
                  ；实交侧判断：
                  {row.right ? verdicts[row.right.verdict] : "本轮无此要求"}。
                </p>
                {row.left_human && (
                  <p>
                    基线侧成员意见（{humanStates[row.left_human.state]}）：
                    {row.left_human.reason}
                  </p>
                )}
                {row.right_human && (
                  <p>
                    实交侧成员意见（{humanStates[row.right_human.state]}）：
                    {row.right_human.reason}
                  </p>
                )}
                <details>
                  <summary>原判断与限制</summary>
                  <p>{row.left?.statement}</p>
                  <p>{row.right?.statement}</p>
                  <p>
                    {[
                      ...(row.left?.limitations ?? []),
                      ...(row.right?.limitations ?? []),
                    ].join("；")}
                  </p>
                </details>
              </article>
            ))}
          </div>
          <div className="retrospective-paging">
            <button
              type="button"
              className="text-button"
              disabled={page === 0}
              onClick={() => setPage(page - 1)}
            >
              上一页差异
            </button>
            <span>第 {page + 1} 页</span>
            <button
              type="button"
              className="text-button"
              disabled={(page + 1) * 20 >= comparison.items.length}
              onClick={() => setPage(page + 1)}
            >
              下一页差异
            </button>
          </div>
        </details>
      ) : (
        <p>两轮核查待补：{p.selection.reviews_missing_reason}</p>
      )}
      <details open>
        <summary>待补资料和结论边界（{p.gaps.length}）</summary>
        <ul>
          {p.gaps.map((gap) => (
            <li key={gap.code}>{gap.message}</li>
          ))}
        </ul>
      </details>
      <details>
        <summary>已绑定的原件（{p.documents.length}）</summary>
        <ul>
          {p.documents.map((doc) => (
            <li key={doc.id}>
              {doc.original_name}
              <details>
                <summary>文件版本和摘要</summary>
                <p>{doc.id}</p>
                <p>{doc.digest}</p>
              </details>
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}

function initialDraft(submission: string, storageKey: string): Draft {
  const empty: Draft = {
    title: "",
    selection: {
      submission_id: submission,
      outcome_id: null,
      outcome_missing_reason: "",
      business_result_id: null,
      business_result_missing_reason: "",
      baseline_run_id: null,
      submitted_run_id: null,
      reviews_missing_reason: "",
    },
    notes: {
      observations: "",
      hypotheses: "",
      next_actions: "",
      additional_missing_materials: "",
    },
  };
  try {
    const v: unknown = JSON.parse(sessionStorage.getItem(storageKey) ?? "null");
    if (
      v &&
      typeof v === "object" &&
      "selection" in v &&
      "notes" in v &&
      "title" in v
    ) {
      const candidate = v as Draft;
      if (
        candidate.selection?.submission_id === submission &&
        typeof candidate.title === "string" &&
        recordObject(candidate.notes) &&
        exactKeys(candidate.notes, [
          "observations",
          "hypotheses",
          "next_actions",
          "additional_missing_materials",
        ]) &&
        Object.values(candidate.notes).every((x) => typeof x === "string") &&
        recordObject(candidate.selection) &&
        exactKeys(candidate.selection, [
          "submission_id",
          "outcome_id",
          "outcome_missing_reason",
          "business_result_id",
          "business_result_missing_reason",
          "baseline_run_id",
          "submitted_run_id",
          "reviews_missing_reason",
        ]) &&
        [
          candidate.selection.outcome_id,
          candidate.selection.business_result_id,
          candidate.selection.baseline_run_id,
          candidate.selection.submitted_run_id,
        ].every((x) => x === null || executionId(x)) &&
        [
          candidate.selection.outcome_missing_reason,
          candidate.selection.business_result_missing_reason,
          candidate.selection.reviews_missing_reason,
        ].every((x) => x === null || typeof x === "string")
      )
        return candidate;
    }
  } catch {
    /* An unreadable local draft cannot choose server records. */
  }
  return empty;
}

function Editor({
  bidId,
  memberId,
  submission,
  onSaved,
}: Props & { submission: string; onSaved: (id: string) => void }) {
  const storageKey = `tender:retrospective-draft:${memberId}:${bidId}:${submission}`;
  const [draft, setDraft] = useState(() =>
    initialDraft(submission, storageKey),
  );
  const [preview, setPreview] = useState<{
    value: PackageRetrospectivePreview;
    etag: string;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const generation = useRef(0);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const scope = `package-retrospective:${memberId}:${bidId}:${submission}`;
  const command = useRecordedCommand(scope, async (result) => {
    await validateRetrospectiveAck(result, bidId, memberId, scope);
  });
  const locked = command.busy || command.pending !== null;
  function update(next: Draft) {
    generation.current++;
    setPreview(null);
    setLoading(false);
    setDraft(next);
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(next));
      setError(null);
    } catch {
      setError(
        new Error(
          "浏览器无法保存本次草稿。请先恢复存储空间，当前输入仍保留在页面中。",
        ),
      );
    }
  }
  function pick(
    field: keyof PackageRetrospectiveSelection,
    value: string | null,
  ) {
    const selected = { ...draft.selection, [field]: value };
    if (field === "outcome_id")
      selected.outcome_missing_reason = value ? null : "";
    if (field === "business_result_id")
      selected.business_result_missing_reason = value ? null : "";
    if (field === "baseline_run_id" || field === "submitted_run_id")
      selected.reviews_missing_reason =
        selected.baseline_run_id || selected.submitted_run_id ? null : "";
    update({ ...draft, selection: selected });
  }
  async function readPreview() {
    const turn = ++generation.current;
    setLoading(true);
    setError(null);
    setPreview(null);
    try {
      const result = await api<unknown>(`${retrospectiveBase(bidId)}/preview`, {
        method: "POST",
        body: draft.selection,
      });
      const value = await validateRetrospectivePreview(
        result.data,
        bidId,
        draft.selection,
      );
      if (
        result.etag !==
        `"package-retrospective-preview:${bidId}:${value.digest}"`
      )
        throw new Error("复盘预览版本依据不符，请重新读取。");
      if (active.current && generation.current === turn) {
        setPreview({ value, etag: result.etag });
        command.clearError();
      }
    } catch (failure) {
      if (active.current && generation.current === turn) setError(failure);
    } finally {
      if (active.current && generation.current === turn) setLoading(false);
    }
  }
  async function save() {
    if (!preview) return;
    const response = await command.run<PackageRetrospectiveApplied>(
      retrospectiveBase(bidId),
      {
        selection: draft.selection,
        preview_digest: preview.value.digest,
        title: draft.title,
        notes: draft.notes,
      },
      preview.etag,
    );
    if (response) onSaved(response.data.retrospective.manifest.id);
  }
  async function retry() {
    const response = await command.retry<PackageRetrospectiveApplied>();
    if (response) onSaved(response.data.retrospective.manifest.id);
  }
  const ready = validRetrospectiveSelection(draft.selection);
  return (
    <section className="retrospective-editor" aria-label="新建整包复盘">
      <h3>整理待核复盘</h3>
      {locked && (
        <div className="notice warning">
          <p>原保存请求尚未取得已核对的回执，输入和原请求保留。</p>
          <button
            type="button"
            className="button secondary"
            disabled={command.busy}
            onClick={() => void retry()}
          >
            恢复原复盘保存结果
          </button>
        </div>
      )}
      <fieldset disabled={locked}>
        <label>
          复盘标题
          <input
            value={draft.title}
            maxLength={200}
            onChange={(event) =>
              update({ ...draft, title: event.target.value })
            }
          />
        </label>
        <div className="retrospective-columns">
          <div>
            <Choice
              bidId={bidId}
              submissionId={submission}
              kind="outcomes"
              label="官方成绩记录"
              value={draft.selection.outcome_id}
              onChange={(v) => pick("outcome_id", v)}
            />
            {draft.selection.outcome_id === null && (
              <label>
                官方成绩待补原因
                <textarea
                  value={draft.selection.outcome_missing_reason ?? ""}
                  maxLength={4000}
                  onChange={(event) =>
                    pick("outcome_missing_reason", event.target.value)
                  }
                />
              </label>
            )}
          </div>
          <div>
            <Choice
              bidId={bidId}
              submissionId={submission}
              kind="business_results"
              label="入围／中标结果记录"
              value={draft.selection.business_result_id}
              onChange={(v) => pick("business_result_id", v)}
            />
            {draft.selection.business_result_id === null && (
              <label>
                业务阶段待补原因
                <textarea
                  value={draft.selection.business_result_missing_reason ?? ""}
                  maxLength={4000}
                  onChange={(event) =>
                    pick("business_result_missing_reason", event.target.value)
                  }
                />
              </label>
            )}
          </div>
        </div>
        <details>
          <summary>选择两轮已完成核查</summary>
          <p>基线侧可以来自原稿；实交侧必须属于所选实际提交包的确切修订。</p>
          <Choice
            bidId={bidId}
            submissionId={submission}
            kind="runs"
            label="基线侧核查"
            value={draft.selection.baseline_run_id}
            onChange={(v) => pick("baseline_run_id", v)}
          />
          <Choice
            bidId={bidId}
            submissionId={submission}
            kind="runs"
            label="实交侧核查"
            value={draft.selection.submitted_run_id}
            onChange={(v) => pick("submitted_run_id", v)}
          />
        </details>
        {draft.selection.baseline_run_id === null &&
          draft.selection.submitted_run_id === null && (
            <label>
              两轮核查待补原因
              <textarea
                value={draft.selection.reviews_missing_reason ?? ""}
                maxLength={4000}
                onChange={(event) =>
                  pick("reviews_missing_reason", event.target.value)
                }
              />
            </label>
          )}
        <div className="retrospective-columns">
          <label>
            成员记录的观察（待核）
            <textarea
              value={draft.notes.observations}
              maxLength={12000}
              onChange={(event) =>
                update({
                  ...draft,
                  notes: { ...draft.notes, observations: event.target.value },
                })
              }
            />
          </label>
          <label>
            成员假设（尚无结论，可留空）
            <textarea
              value={draft.notes.hypotheses}
              maxLength={12000}
              onChange={(event) =>
                update({
                  ...draft,
                  notes: { ...draft.notes, hypotheses: event.target.value },
                })
              }
            />
          </label>
        </div>
        <label>
          下一步核对和整改
          <textarea
            value={draft.notes.next_actions}
            maxLength={12000}
            onChange={(event) =>
              update({
                ...draft,
                notes: { ...draft.notes, next_actions: event.target.value },
              })
            }
          />
        </label>
        <label>
          其他待补资料（可留空）
          <textarea
            value={draft.notes.additional_missing_materials}
            maxLength={4000}
            onChange={(event) =>
              update({
                ...draft,
                notes: {
                  ...draft.notes,
                  additional_missing_materials: event.target.value,
                },
              })
            }
          />
        </label>
      </fieldset>
      {!!(error || command.error) && (
        <ErrorNotice error={error || command.error} />
      )}
      <div className="retrospective-actions">
        <button
          type="button"
          className="button secondary"
          disabled={!ready || locked || loading}
          onClick={() => void readPreview()}
        >
          核对复盘依据
        </button>
        <button
          type="button"
          className="button"
          disabled={
            !preview ||
            locked ||
            command.conflict ||
            !draft.title.trim() ||
            !draft.notes.observations.trim() ||
            !draft.notes.next_actions.trim()
          }
          onClick={() => void save()}
        >
          保存不可变待核复盘
        </button>
      </div>
      {!ready && (
        <p className="muted">
          每类资料需要明确选择记录，或填写待补原因；两轮核查需成对选择。
        </p>
      )}
      {loading && <Loading text="正在核对确切实交和所选原始记录…" />}
      {preview && <Summary key={preview.value.digest} value={preview.value} />}
      {command.conflict && (
        <p className="notice warning">
          依据已变化。请保留原文字，重新核对预览后再保存。
        </p>
      )}
    </section>
  );
}

function Detail({
  bidId,
  memberId,
  id,
  onKnowledgeCreated,
}: Props & { id: string }) {
  const resource = useResource<unknown>(`${retrospectiveBase(bidId)}/${id}`);
  const [checked, setChecked] = useState<{
    source: unknown;
    value: PackageRetrospectiveDetail;
  } | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    let active = true;
    if (resource.data)
      void validateRetrospectiveDetail(resource.data, bidId, id).then(
        (value) => {
          if (active) {
            setChecked({ source: resource.data, value });
            setError(null);
          }
        },
        (failure: unknown) => {
          if (active) setError(failure);
        },
      );
    return () => {
      active = false;
    };
  }, [resource.data, bidId, id]);
  const detail = checked?.source === resource.data ? checked?.value : null;
  return (
    <section className="retrospective-detail" aria-label="已保存复盘">
      {resource.loading && !detail && <Loading text="正在读取不可变复盘…" />}
      {!!(resource.error || error) && (
        <ErrorNotice
          error={resource.error || error}
          onRetry={() => void resource.reload()}
        />
      )}
      {detail && (
        <>
          <h3>
            {detail.retrospective.manifest.title}{" "}
            <Badge tone="warning">待人工核对</Badge>
          </h3>
          <p>
            已保存于{" "}
            {new Date(
              detail.retrospective.manifest.created_at,
            ).toLocaleString()}
            。补充资料或更正结论需新建复盘，原记录保留。
          </p>
          <Summary
            key={detail.retrospective.digest}
            value={detail.retrospective.manifest.preview}
          />
          <details open>
            <summary>保存的成员观察和整改计划</summary>
            <h4>成员记录的观察（待核）</h4>
            <p className="retrospective-prose">
              {detail.retrospective.manifest.notes.observations}
            </p>
            <h4>成员假设（尚无结论）</h4>
            <p className="retrospective-prose">
              {detail.retrospective.manifest.notes.hypotheses || "未填写"}
            </p>
            <h4>下一步核对和整改</h4>
            <p className="retrospective-prose">
              {detail.retrospective.manifest.notes.next_actions}
            </p>
            <h4>其他待补资料</h4>
            <p className="retrospective-prose">
              {detail.retrospective.manifest.notes
                .additional_missing_materials || "未填写"}
            </p>
          </details>
          {!detail.current.unchanged && (
            <div className="notice warning">
              <strong>原复盘依据当前已变化</strong>
              <ul>
                {detail.current.issues.map((issue) => (
                  <li key={issue.code}>{issue.message}</li>
                ))}
              </ul>
            </div>
          )}
          <KnowledgeCandidate
            key={detail.retrospective.manifest.id}
            frozen={detail.retrospective}
            detail={detail}
            memberId={memberId}
            onCreated={() => void resource.reload()}
            onOpen={onKnowledgeCreated}
          />
        </>
      )}
    </section>
  );
}

function KnowledgeCandidate({
  frozen,
  detail,
  memberId,
  onCreated,
  onOpen,
}: {
  frozen: PackageRetrospectiveView;
  detail: PackageRetrospectiveDetail;
  memberId: string;
  onCreated: () => void;
  onOpen?: (knowledgeId: string) => void;
}) {
  const scope = `package-retrospective-knowledge:${memberId}:${frozen.manifest.bid_id}:${frozen.manifest.id}`;
  const storageKey = `tender:retrospective-handoff:${memberId}:${frozen.manifest.id}`;
  const [reason, setReason] = useState(
    () => readRetrospectiveText(storageKey) ?? "",
  );
  const [storageError, setStorageError] = useState<unknown>(null);
  const command = useRecordedCommand(scope, async (result) => {
    await validateRetrospectiveKnowledgeAck(result, frozen, memberId, scope);
  });
  const [created, setCreated] = useState<
    PackageRetrospectiveKnowledgeApplied["link"] | null
  >(null);
  const linked = detail.knowledge_link ?? created;
  async function create() {
    const result = await command.run<PackageRetrospectiveKnowledgeApplied>(
      `${retrospectiveBase(frozen.manifest.bid_id)}/${frozen.manifest.id}/knowledge-candidate`,
      { retrospective_digest: frozen.digest, reason },
      retrospectiveTag(frozen),
    );
    if (result) {
      setCreated(result.data.link);
      onCreated();
    }
  }
  async function retry() {
    const result = await command.retry<PackageRetrospectiveKnowledgeApplied>();
    if (result) {
      setCreated(result.data.link);
      onCreated();
    }
  }
  return (
    <section className="retrospective-handoff" aria-label="知识候选流转">
      <h4>进入企业知识候选</h4>
      <p>
        这个动作只建立待核候选。还需在企业知识中补齐适用主体、条件、期限和精确出处，再分别送确认和发布。复盘不会自动创建研究样本或发布模型。
      </p>
      {linked ? (
        <div role="status">
          <p>已建立企业知识候选。正式发布状态请在企业知识中核对。</p>
          {onOpen ? (
            <button
              type="button"
              className="button secondary"
              onClick={() => onOpen(linked.knowledge_id)}
            >
              打开企业知识候选
            </button>
          ) : (
            <p>
              候选编号：{linked.knowledge_id}。可从企业知识维护目录继续核对。
            </p>
          )}
        </div>
      ) : (
        <>
          <label>
            建立候选的原因
            <textarea
              value={reason}
              maxLength={4000}
              disabled={command.busy || !!command.pending}
              onChange={(event) => {
                setReason(event.target.value);
                try {
                  sessionStorage.setItem(storageKey, event.target.value);
                  setStorageError(null);
                } catch {
                  setStorageError(
                    new Error(
                      "候选说明暂时不能保存在浏览器中，请恢复存储空间后重试。",
                    ),
                  );
                }
              }}
            />
          </label>
          <button
            type="button"
            className="button"
            disabled={
              !reason.trim() ||
              !detail.current.unchanged ||
              command.busy ||
              !!command.pending ||
              !!storageError
            }
            onClick={() => void create()}
          >
            明确建立企业知识候选
          </button>
        </>
      )}
      {command.pending && (
        <button
          type="button"
          className="button secondary"
          disabled={command.busy}
          onClick={() => void retry()}
        >
          恢复原知识候选结果
        </button>
      )}
      {!!(command.error || storageError) && (
        <ErrorNotice error={command.error || storageError} />
      )}
    </section>
  );
}

function Workspace(props: Props) {
  const { bidId, memberId } = props;
  const storageKey = `tender:retrospective-selection:${memberId}:${bidId}`;
  const [submission, setSubmission] = useState<string | null>(() =>
    readRetrospectiveText(storageKey),
  );
  const [storageError, setStorageError] = useState<unknown>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const history = useResource<PackageRetrospectivePage>(
    `${retrospectiveBase(bidId)}?offset=${offset}`,
  );
  const checkedHistory = useMemo(() => {
    if (!history.data) return null;
    try {
      return {
        value: validateRetrospectiveHistory(history.data, bidId),
        error: null,
      };
    } catch (error) {
      return { value: null, error };
    }
  }, [history.data, bidId]);
  const entries = checkedHistory?.value?.items ?? [];
  return (
    <section className="package-retrospectives" aria-label="整包复盘">
      <header>
        <h2>整包复盘</h2>
        <p>选择确切实交、结果和两轮核查，整理有出处的观察与待补资料。</p>
      </header>
      <Choice
        bidId={bidId}
        kind="submissions"
        label="本次复盘的实际提交"
        value={submission}
        onChange={(id) => {
          setSubmission(id);
          try {
            if (id) sessionStorage.setItem(storageKey, id);
            else sessionStorage.removeItem(storageKey);
            setStorageError(null);
          } catch {
            setStorageError(
              new Error(
                "浏览器暂时无法保留本次实交选择；刷新前请核对输入是否已保存。",
              ),
            );
          }
        }}
      />
      {!!storageError && <ErrorNotice error={storageError} />}
      {submission ? (
        <Editor
          key={`${memberId}:${bidId}:${submission}`}
          {...props}
          submission={submission}
          onSaved={(id) => {
            setSelected(id);
            void history.reload();
          }}
        />
      ) : (
        <p className="notice">
          先选择已经登记的整包实交。没有实交记录时，请先到实际提交完成登记。
        </p>
      )}
      <section aria-label="复盘历史">
        <h3>已保存的待核复盘</h3>
        {history.loading && <Loading text="正在读取复盘历史…" />}
        {!!(history.error || checkedHistory?.error) && (
          <ErrorNotice
            error={history.error || checkedHistory?.error}
            onRetry={() => void history.reload()}
          />
        )}
        {!history.loading && !entries.length && (
          <p>尚无已保存复盘。填写并核对上方依据后，可保存第一条待核记录。</p>
        )}
        <ul>
          {entries.map((entry) => (
            <li key={entry.id}>
              <button
                type="button"
                className="text-button"
                aria-pressed={selected === entry.id}
                onClick={() => setSelected(entry.id)}
              >
                {entry.title} · {new Date(entry.created_at).toLocaleString()}
              </button>
            </li>
          ))}
        </ul>
        <div className="retrospective-paging">
          {offset > 0 && (
            <button
              type="button"
              className="text-button"
              onClick={() => setOffset(Math.max(0, offset - 30))}
            >
              上一页复盘
            </button>
          )}
          {checkedHistory?.value?.next_offset != null && (
            <button
              type="button"
              className="text-button"
              onClick={() => setOffset(checkedHistory.value!.next_offset!)}
            >
              下一页复盘
            </button>
          )}
        </div>
      </section>
      {selected && (
        <Detail key={`${bidId}:${selected}`} {...props} id={selected} />
      )}
    </section>
  );
}

export function PackageRetrospectives(props: Props) {
  return <Workspace key={`${props.memberId}:${props.bidId}`} {...props} />;
}
