import { useCallback, useEffect, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import type {
  PackageOutcomeContext,
  PackageSubmissionView,
  ResearchOutcomeDetail,
  ResearchOutcomePage,
} from "./contracts";
import { Badge, ErrorNotice } from "./components";
import { ArtifactActions } from "./ArtifactActions";
import { PackageOutcomeRegistration } from "./PackageOutcomeRegistration";
import { PackageOutcomeVerification } from "./PackageOutcomeVerification";
import {
  outcomeHeadEtag,
  packageOutcomeReason,
  packageOutcomeScope,
  validateOutcomeContext,
  validateOutcomeDetail,
  validateOutcomePage,
} from "./packageOutcomeProtocol";
import { usePackageOutcomeCommand } from "./usePackageOutcomeCommand";
import "./PackageOfficialOutcomes.css";

type Props = {
  bidId: string;
  memberId: string;
  submission: PackageSubmissionView;
};
type Snapshot = {
  readSequence: number;
  context: PackageOutcomeContext;
  page: ResearchOutcomePage;
  detail: ResearchOutcomeDetail | null;
  verificationEtag: string | null;
  headEtag: string | null;
};
type Form = {
  kind: "register" | "correct" | "verify";
  basis: Snapshot;
  token: string;
};
const scoreNames = {
  technical_total: "技术总分",
  comprehensive_total: "综合总分",
  unknown: "成绩口径未知",
};
const states = {
  pending: "待核验",
  verified: "已记录核验通过",
  conflict: "存在核验冲突",
  rejected: "核验已驳回",
};

export function PackageOfficialOutcomes(props: Props) {
  const [open, setOpen] = useState(false);
  if (!supportsApi("GET", `/bids/${props.bidId}/outcome-context`)) return null;
  return (
    <div className="package-official-outcomes">
      <button
        type="button"
        className="text-button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {open ? "收起整包官方成绩" : "登记／核验此整包的官方成绩"}
      </button>
      {open && (
        <OutcomeWorkspace
          key={`${props.memberId}:${props.submission.id}:${props.submission.package_binding.digest}`}
          {...props}
        />
      )}
    </div>
  );
}

function OutcomeWorkspace({ bidId, memberId, submission }: Props) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null),
    [rejectedAfter, setRejectedAfter] = useState(0),
    [loading, setLoading] = useState(false),
    [readError, setReadError] = useState<unknown>(null),
    [form, setForm] = useState<Form | null>(null),
    [success, setSuccess] = useState<string | null>(null),
    [shown, setShown] = useState(10);
  const active = useRef(false),
    generation = useRef(0);
  const invalidate = useCallback(() => {
    generation.current++;
  }, []);
  const read = useCallback(
    async (selectedId?: string): Promise<Snapshot | null> => {
      const request = ++generation.current;
      setLoading(true);
      setReadError(null);
      try {
        const [contextResult, pageResult] = await Promise.all([
          api<unknown>(
            `/bids/${bidId}/outcome-context?submission_id=${submission.id}`,
          ),
          api<unknown>(`/bids/${bidId}/outcomes`),
        ]);
        const context = validateOutcomeContext(contextResult.data, submission),
          page = validateOutcomePage(pageResult.data, bidId);
        const head = page.heads.find(
          (item) => item.submission_id === submission.id,
        );
        const id = selectedId ?? head?.outcome_id;
        if (
          (id &&
            !page.items.some(
              (item) => item.id === id && item.submission_id === submission.id,
            )) ||
          (!head &&
            page.items.some((item) => item.submission_id === submission.id))
        )
          throw new Error(
            "这次实交的成绩头或记录不完整，请重新读取，未猜测当前成绩。",
          );
        let detail: ResearchOutcomeDetail | null = null,
          verificationEtag: string | null = null;
        const headEtag = head
          ? outcomeHeadEtag(submission.id, head.revision)
          : null;
        if (id) {
          const result = await api<unknown>(`/outcomes/${id}`);
          detail = await validateOutcomeDetail(
            result.data,
            submission,
            id,
            result.etag,
            result.outcomeHeadEtag,
          );
          if (
            result.outcomeHeadEtag !== headEtag ||
            detail.current !== (id === head?.outcome_id)
          )
            throw new Error("读取期间成绩版本已变化，请再次核对当前记录。");
          verificationEtag = result.etag;
        }
        const value = {
          readSequence: request,
          context,
          page,
          detail,
          verificationEtag,
          headEtag,
        };
        if (active.current && generation.current === request) {
          setSnapshot(value);
          return value;
        }
      } catch (error) {
        if (active.current && generation.current === request)
          setReadError(error);
      } finally {
        if (active.current && generation.current === request) setLoading(false);
      }
      return null;
    },
    [bidId, submission],
  );
  useEffect(() => {
    active.current = true;
    void read();
    return () => {
      active.current = false;
      invalidate();
    };
  }, [read, invalidate]);
  const scope = packageOutcomeScope(bidId, memberId, submission);
  const command = usePackageOutcomeCommand(
    scope,
    submission,
    (id) => {
      setForm(null);
      setSuccess(id);
      void read(id);
      window.dispatchEvent(new Event("server-snapshot-change"));
    },
    () => setRejectedAfter(generation.current),
  );
  const locked = command.busy || !!command.pending || command.blocked;
  const detail = snapshot?.detail;
  const formHeadSame =
    !!form &&
    !!snapshot &&
    (form.kind === "register"
      ? snapshot.headEtag === null
      : snapshot.detail?.id === form.basis.detail?.id &&
        snapshot.detail?.current === true);
  const formTagSame =
    formHeadSame &&
    (form?.kind === "verify"
      ? snapshot?.verificationEtag === form.basis.verificationEtag
      : snapshot?.headEtag === form?.basis.headEtag);
  const stale = !!form && (!formTagSame || command.rejected);
  async function open(kind: Form["kind"]) {
    if (locked || loading) return;
    const value = await read();
    if (
      !value ||
      (kind === "register" ? value.headEtag !== null : !value.detail?.current)
    )
      return;
    command.reviewed();
    setSuccess(null);
    setForm({ kind, basis: value, token: crypto.randomUUID() });
  }
  const items =
    snapshot?.page.items
      .filter((item) => item.submission_id === submission.id)
      .reverse() ?? [];
  return (
    <section
      className="package-outcome-workspace"
      aria-label="整包官方成绩工作面"
    >
      <div className="section-heading">
        <h3>官方成绩与原页核验</h3>
        <button
          type="button"
          className="text-button"
          disabled={loading || command.busy}
          onClick={() => void read(detail?.id)}
        >
          {loading ? "正在读取…" : "重新读取并核对当前记录"}
        </button>
      </div>
      <p className="small-note">
        这一工作面只关联这次实际提交及其固定包。保存成绩后进入待核验；成绩更正会产生新记录，原成绩和原核验继续留存。
      </p>
      <p className="notice neutral">
        整包正式研究样本与事前评分尚未开放。本处核验通过也不会将成绩加入训练样本或评分误差统计。
      </p>
      <ErrorNotice error={readError} />
      {loading && <p role="status">正在读取原提交身份、成绩头与来源状态…</p>}
      {success && (
        <p role="status" className="notice success">
          已取得原操作回执。记录 {success} 的当前状态以重新读取结果为准。
        </p>
      )}
      {snapshot && (
        <>
          <p>
            {snapshot.context.display.project_title} ·{" "}
            {snapshot.context.display.lot ?? "未声明标段"} · 第{" "}
            {snapshot.context.display.round_no} 轮 ·{" "}
            {snapshot.context.display.bidder_name}
          </p>
          <details>
            <summary>查看原整包身份与固定依据</summary>
            <dl>
              <dt>原实交记录</dt>
              <dd>{submission.id}</dd>
              <dt>整包修订</dt>
              <dd>{snapshot.context.identity.revision_id}</dd>
              <dt>实交绑定摘要</dt>
              <dd>{snapshot.context.identity.binding_digest}</dd>
              <dt>原招标依据修订</dt>
              <dd>
                {snapshot.context.authority?.revision_id ??
                  "原提交明确未关联依据包"}
              </dd>
            </dl>
          </details>
          {detail ? (
            <article className="package-outcome-current">
              <div className="section-heading">
                <h4>{scoreNames[detail.score_kind]}</h4>
                <Badge>
                  {detail.current ? "当前成绩记录" : "历史成绩记录"}
                </Badge>
                <Badge tone="warning">{states[detail.verification]}</Badge>
              </div>
              <p className="outcome-value">
                {detail.value === null ? "未知" : detail.value}
                {detail.maximum !== null && <small> / {detail.maximum}</small>}
              </p>
              <p className="small-note">
                取得于 {detail.known_at} · 核验修订{" "}
                {detail.verification_revision}
              </p>
              <p
                className={`notice ${detail.package_association?.available ? "success" : "warning"}`}
              >
                {detail.package_association?.available
                  ? "这条官方成绩关联目前仍有有效依据。"
                  : `当前关联不可用：${detail.package_association?.reasons.map(packageOutcomeReason).join("；") ?? "尚未取得当前核验结果"}。`}
                <span> 核验历史不会因来源后续变化被改写。</span>
              </p>
              {detail.verification_details &&
                "subject_kind" in detail.verification_details && (
                  <p>核验说明：{detail.verification_details.request.reason}</p>
                )}
              <ArtifactActions
                bidId={bidId}
                documentId={detail.source_version_id}
                isPdf={false}
                expectedArtifactKind="source_original"
                downloadLabel="下载这版成绩来源原件"
              />
            </article>
          ) : (
            <p className="small-empty">
              这次整包实交尚未登记官方成绩，结果保持未知。
            </p>
          )}
          {!form && (
            <div className="review-shortcuts">
              {snapshot.headEtag === null && (
                <button
                  type="button"
                  className="button secondary"
                  disabled={locked || loading || !!readError}
                  onClick={() => void open("register")}
                >
                  登记官方成绩
                </button>
              )}
              {detail?.current && (
                <>
                  <button
                    type="button"
                    className="button secondary"
                    disabled={locked || loading || !!readError}
                    onClick={() => void open("correct")}
                  >
                    追加更正官方成绩
                  </button>
                  <button
                    type="button"
                    className="button secondary"
                    disabled={locked || loading || !!readError}
                    onClick={() => void open("verify")}
                  >
                    核验这一版官方成绩
                  </button>
                </>
              )}
            </div>
          )}
        </>
      )}
      <ErrorNotice error={command.error} />
      {command.pending && (
        <div className="notice warning" role="status">
          <p>
            上次成绩操作尚未取得可核对的回执。原请求、版本和幂等键已保留；请先恢复原操作。
          </p>
          <button
            type="button"
            className="button secondary"
            disabled={command.busy}
            onClick={() => void command.retry()}
          >
            {command.busy ? "正在恢复…" : "恢复原成绩操作"}
          </button>
        </div>
      )}
      {form && (
        <div className="package-outcome-editor" key={form.token}>
          {stale && (
            <div className="notice warning">
              <p>
                输入仍保留，原成绩版本或核验条件已变化。请重新读取并核对，再明确采用已读取的版本。
              </p>
              <p>
                原成绩：{form.basis.detail?.id ?? "尚无记录"}；现在读取：
                {snapshot?.detail?.id ?? "尚无记录"}。
              </p>
              <button
                type="button"
                className="button secondary"
                disabled={
                  locked ||
                  loading ||
                  !!readError ||
                  !formHeadSame ||
                  (command.rejected &&
                    (snapshot?.readSequence ?? 0) <= rejectedAfter)
                }
                onClick={() => {
                  if (
                    snapshot &&
                    (!command.rejected || snapshot.readSequence > rejectedAfter)
                  ) {
                    setForm((old) =>
                      old ? { ...old, basis: snapshot } : null,
                    );
                    command.reviewed();
                  }
                }}
              >
                采用已核对版本，保留当前输入
              </button>
              {!formHeadSame && (
                <p>
                  成绩头已指向另一条记录，不能将本次输入自动覆盖到它。可先核对历史，再结束本次编辑并选择新记录。
                </p>
              )}
            </div>
          )}
          {form.kind === "verify" && form.basis.detail ? (
            <PackageOutcomeVerification
              submission={submission}
              context={form.basis.context}
              base={form.basis.detail}
              locked={locked || loading || !!readError || stale}
              onSubmit={(body) => {
                const base = form.basis.detail!;
                void command.run({
                  kind: "verify",
                  key: crypto.randomUUID(),
                  baseId: base.id,
                  etag: form.basis.verificationEtag!,
                  baseRevision: base.verification_revision,
                  score: {
                    submission_id: submission.id,
                    score_kind: base.score_kind,
                    value: base.value,
                    maximum: base.maximum,
                    source_version_id: base.source_version_id,
                    known_at: base.known_at,
                    supersedes_id: base.supersedes_id,
                  },
                  body,
                });
              }}
            />
          ) : (
            <PackageOutcomeRegistration
              submission={submission}
              context={form.basis.context}
              base={form.kind === "correct" ? form.basis.detail : null}
              locked={locked || loading || !!readError || stale}
              onSubmit={(body) => {
                void command.run({
                  kind: form.kind === "correct" ? "correct" : "register",
                  key: crypto.randomUUID(),
                  baseId:
                    form.kind === "correct" ? form.basis.detail!.id : null,
                  etag: form.kind === "correct" ? form.basis.headEtag : null,
                  body,
                });
              }}
            />
          )}
          <button
            type="button"
            className="text-button"
            disabled={locked}
            onClick={() => setForm(null)}
          >
            结束本次编辑
          </button>
        </div>
      )}
      {!!items.length && (
        <details className="package-outcome-history">
          <summary>这次实交的成绩历史（{items.length} 条）</summary>
          <ul>
            {items.slice(0, shown).map((item) => (
              <li key={item.id}>
                <span>
                  {scoreNames[item.score_kind]} ·{" "}
                  {item.value === null
                    ? "未知"
                    : `${item.value} / ${item.maximum}`}{" "}
                  · {states[item.verification]}
                </span>
                <small>{item.known_at}</small>
                <button
                  type="button"
                  className="text-button"
                  disabled={loading || command.busy}
                  onClick={() => void read(item.id)}
                >
                  查看记录 {item.id.slice(0, 8)}
                </button>
              </li>
            ))}
          </ul>
          {shown < items.length && (
            <button
              type="button"
              className="text-button"
              onClick={() => setShown((value) => value + 20)}
            >
              显示更多成绩历史
            </button>
          )}
        </details>
      )}
    </section>
  );
}
