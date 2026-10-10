import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { Decision, EvidenceRef, Finding, Revision } from '../../api/types';
import { AiBadge, ErrorNotice, Field, Loading, Notice, Tag } from '../../components/ui';
import { cn } from '../../lib/cn';
import { Icon } from '../../components/Icon';
import { Dialog, DialogActions } from '../../components/Dialog';
import { useToast } from '../../components/Toast';
import { isApiError } from '../../api/errors';
import {
  decisionLabel,
  evidenceKindLabel,
  findingCategoryLabel,
  findingImpactLabel,
  findingNatureLabel,
  droppedReasonLabel,
  findingStatusLabel,
  revisionStatusLabel,
} from '../../lib/labels';
import { PdfViewer } from '../evidence/PdfViewer';
import { FactPicker } from '../facts/FactPicker';
import { useFacts } from '../facts/queries';
import { useFiles } from '../materials/queries';
import {
  ALLOWED_DECISIONS,
  RESOLVE_WARNING,
  findingCode,
  isPrimaryDecision,
  statusTone,
} from './shared';
import { TaskProgress } from '../tasks/TaskProgress';
import {
  revisionKeys,
  useAdoptRevision,
  useProposeRevision,
  useRejectRevision,
  useRevisionDiff,
  useRevisions,
  useReviewFinding,
  useSnapshot,
} from './queries';
import { Button, textLink } from '../../components/ui/button';
import { Input, Textarea } from '../../components/ui/input';

const SEMANTIC_TEXT: Record<EvidenceRef['semantic_review'], string> = {
  pending: '',
  supported: '已核对',
  unsupported: '摘录不支持该问题',
};

type Side = 'tender' | 'body' | 'other';

/** 证据出自哪一侧：招标文件与补遗是“要求”，施组正文是“写法”，其余资料单列。 */
export function sideOf(ev: Pick<EvidenceRef, 'file_role'>): Side {
  if (ev.file_role === 'tender' || ev.file_role === 'supplement') return 'tender';
  if (ev.file_role === 'body' || ev.file_role === 'submission') return 'body';
  return 'other';
}

/** 问题的处理进度条：待确认 → 已确认 → 修改建议已采纳 → 待复检 → 已解决。驳回、暂缓不在主线上，单独标出。 */
const LIFECYCLE = ['待确认', '已确认', '已采纳修改', '待复检', '已解决'] as const;
const LIFECYCLE_AT: Partial<Record<string, number>> = {
  candidate: 0,
  deferred: 0,
  confirmed: 1,
  revision_pending: 2,
  recheck_pending: 3,
  resolved: 4,
};

function Lifecycle({ status }: { status: string }) {
  const at = LIFECYCLE_AT[status];
  if (at === undefined)
    return (
      <p className="m-0 mt-3 text-xs text-muted-foreground">
        已驳回：不再处理，需要时可以重新打开。
      </p>
    );
  return (
    <ol
      className="m-0 mt-3 flex list-none flex-wrap items-center gap-1 p-0 text-xs"
      aria-label="处理进度"
    >
      {LIFECYCLE.map((l, i) => (
        <li
          key={l}
          aria-current={i === at ? 'step' : undefined}
          className={cn(
            'flex items-center gap-1',
            i < at && 'is-done text-success-foreground',
            i === at && 'is-now font-medium text-foreground',
            i > at && 'text-muted-foreground',
          )}
        >
          {i > 0 ? <Icon name="ChevronRight" size={12} className="text-border-strong" /> : null}
          <span
            className={cn(
              'rounded-sm px-1.5 py-0.5',
              i === at && 'bg-primary-soft text-primary-soft-foreground',
            )}
          >
            {l}
            {i === at && status === 'deferred' ? '（暂缓）' : ''}
          </span>
        </li>
      ))}
    </ol>
  );
}

/**
 * 问题详情：招标文件怎么要求、正文怎么写的并排对照，下面是处理与改稿建议。
 * 并排是为了一眼看出差在哪里，不用在两个页签之间来回切。
 */
export function FindingDetail({
  finding,
  projectId,
  onReviewed,
}: {
  finding: Finding;
  projectId: string;
  /** 一次审核保存成功后调用（问题页据此跳到下一条未处理的问题）。 */
  onReviewed?: () => void;
}) {
  const [reviseOpen, setReviseOpen] = useState(false);
  const sides: Record<Side, EvidenceRef[]> = { tender: [], body: [], other: [] };
  for (const ev of finding.evidence) sides[sideOf(ev)].push(ev);
  const showRevise = reviseOpen || ['confirmed', 'revision_pending'].includes(finding.status);

  return (
    <section
      className="overflow-hidden rounded-lg border border-border bg-card"
      aria-label={`问题 ${findingCode(finding.finding_id)} 详情`}
    >
      <div className="border-b border-border px-5 pt-4 pb-4">
        <p className="m-0 mb-2 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>
            问题 {findingCode(finding.finding_id)} · {findingCategoryLabel(finding.category)} ·{' '}
            {findingImpactLabel(finding.impact)}
          </span>
          {finding.status === 'candidate' ? (
            <AiBadge />
          ) : (
            <Tag tone={statusTone(finding.status)}>{findingStatusLabel(finding.status)}</Tag>
          )}
        </p>
        <h2 className="text-base leading-snug font-semibold tracking-tight">{finding.statement}</h2>
        <p className="m-0 mt-1 text-xs text-muted-foreground">
          {findingNatureLabel(finding.nature)}
          {finding.rule_basis === 'unconfirmed' ? ' · 依据的规则还没核对，暂按原文判断' : ''}
        </p>
        <Lifecycle status={finding.status} />
      </div>
      {finding.evidence.length === 0 ? (
        <div className="p-4">
          <Notice>这条问题没有可回溯的原文，不能据此确认；请要求补充事实或驳回。</Notice>
        </div>
      ) : (
        <div className="grid border-b border-border md:grid-cols-2 [&>*+*]:border-t [&>*+*]:border-border md:[&>*+*]:border-t-0 md:[&>*+*]:border-l">
          <EvidenceColumn title="招标文件要求" list={sides.tender} projectId={projectId} />
          <EvidenceColumn
            title="施组正文写法"
            list={sides.body}
            projectId={projectId}
            empty="正文里没有找到对应内容"
          />
          {sides.other.length ? (
            <EvidenceColumn title="其他资料" list={sides.other} projectId={projectId} />
          ) : null}
        </div>
      )}
      <ReviewArea finding={finding} projectId={projectId} onReviewed={onReviewed} />
      <section
        className="border-t border-border px-5 py-4"
        aria-labelledby={`rv-${finding.finding_id}`}
      >
        <div className="flex items-center justify-between gap-3">
          <h3
            id={`rv-${finding.finding_id}`}
            className="flex items-center gap-1.5 text-[13px] font-semibold"
          >
            <Icon name="Sparkles" className="text-ai" />
            改稿建议
          </h3>
          {showRevise ? null : (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setReviseOpen(true);
              }}
            >
              展开
            </Button>
          )}
        </div>
        {showRevise ? (
          <div className="mt-2">
            <RevisionTab key={finding.finding_id} finding={finding} projectId={projectId} />
          </div>
        ) : null}
      </section>
    </section>
  );
}

function EvidenceColumn({
  title,
  list,
  projectId,
  empty,
}: {
  title: string;
  list: EvidenceRef[];
  projectId: string;
  empty?: string;
}) {
  return (
    <div className="min-w-0 px-5 py-4">
      <h3 className="mb-2 text-xs font-medium text-muted-foreground">{title}</h3>
      {list.length === 0 ? (
        <p className="text-muted-foreground">{empty ?? '没有引用'}</p>
      ) : (
        list.map((ev) => <EvidenceItem key={ev.evidence_id} ev={ev} projectId={projectId} />)
      )}
    </div>
  );
}

function EvidenceItem({ ev, projectId }: { ev: EvidenceRef; projectId: string }) {
  const [open, setOpen] = useState(false);
  const semantic = SEMANTIC_TEXT[ev.semantic_review];
  return (
    <article className="[&+&]:mt-3 [&+&]:border-t [&+&]:border-border [&+&]:pt-3">
      <blockquote className="m-0 border-l-2 border-highlight-border bg-highlight/40 px-3 py-2 text-sm leading-7 break-words">
        {ev.quote || '（摘录为空）'}
      </blockquote>
      <p className="m-0 mt-1.5 text-xs text-muted-foreground">
        {ev.file_name} · 第 {ev.physical_page} 页
        {ev.printed_page && ev.printed_page !== String(ev.physical_page)
          ? `（页码 ${ev.printed_page}）`
          : ''}
        {ev.kind !== 'text' ? ` · ${evidenceKindLabel(ev.kind)}` : ''}
        {semantic ? ` · ${semantic}` : ''}
      </p>
      <p className="m-0 mt-1 flex gap-4">
        <button
          type="button"
          className={textLink}
          aria-expanded={open}
          onClick={() => {
            setOpen((o) => !o);
          }}
        >
          {open ? '收起原页' : '看原页'}
        </button>
        <Link className={textLink} to={`/projects/${projectId}/evidence/${ev.evidence_id}`}>
          整页打开
        </Link>
      </p>
      {open ? (
        <PdfViewer
          versionId={ev.version_id}
          page={ev.physical_page}
          printedPage={ev.printed_page}
          bbox={ev.bbox}
        />
      ) : null}
    </article>
  );
}

function ReviewArea({
  finding,
  projectId,
  onReviewed,
}: {
  finding: Finding;
  projectId: string;
  onReviewed?: () => void;
}) {
  const toast = useToast();
  const [reason, setReason] = useState('');
  const [touched, setTouched] = useState(false);
  const review = useReviewFinding(projectId, finding, () => {
    setReason('');
    setTouched(false);
  });
  const allowed = ALLOWED_DECISIONS[finding.status] ?? [];
  const trimmed = reason.trim();
  const reasonErr =
    touched && !trimmed ? '请填写理由：驳回、暂缓、重新打开等决定都要写明原因' : null;

  const submit = (decision: Decision) => {
    setTouched(true);
    if (decision !== 'confirm' && !trimmed) return;
    review.mutate(
      { decision, ...(trimmed ? { reason: trimmed } : {}) },
      {
        onSuccess: () => {
          toast.notify(`已记录：${decisionLabel(decision)}`);
          onReviewed?.();
        },
      },
    );
  };

  return (
    <div className="px-5 py-4">
      <h3 className="mb-3 text-[13px] font-semibold">处理</h3>
      {finding.required_facts.length > 0 ? (
        <div className="mb-4 rounded-md bg-subtle px-3 py-2.5 text-[13px]">
          <p className="m-0 font-medium">还需要的事实</p>
          <ul className="my-1 list-disc pl-5">
            {finding.required_facts.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
          <p className="text-muted-foreground">
            先到
            <Link className={textLink} to={`/projects/${projectId}/basis?tab=facts`}>
              事实库
            </Link>
            录入，再回报告重新评审。
          </p>
        </div>
      ) : null}
      <StatusHint finding={finding} projectId={projectId} />
      {allowed.length === 0 ? (
        <p className="text-muted-foreground">
          当前状态“{findingStatusLabel(finding.status)}”下没有可提交的审核动作。
        </p>
      ) : (
        <>
          <Field label="理由" hint="确认可以不写；驳回、暂缓、重新打开要写" error={reasonErr}>
            {(p) => (
              <Textarea
                {...p}
                value={reason}
                rows={3}
                onChange={(e) => {
                  setReason(e.target.value);
                }}
              />
            )}
          </Field>
          {review.isError ? (
            <ErrorNotice
              error={review.error}
              title={
                isApiError(review.error) && review.error.kind === 'stale'
                  ? '版本已变化'
                  : '没有保存'
              }
            />
          ) : null}
          {allowed.includes('resolve') && RESOLVE_WARNING[finding.status] ? (
            <Notice>{RESOLVE_WARNING[finding.status]}</Notice>
          ) : null}
          {allowed.includes('reopen') ? (
            <p className="text-muted-foreground">
              重新打开会让这条问题回到待处理，之前的处理记录保留。
            </p>
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            {allowed.map((d, i) => (
              <Button
                key={d}
                variant={isPrimaryDecision(finding.status, d, i) ? 'primary' : 'secondary'}
                disabled={review.isPending}
                onClick={() => {
                  submit(d);
                }}
              >
                {decisionLabel(d)}
              </Button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/** 各状态下的下一步说明。上传新正文会自动开新一轮评审，但旧问题不会自动结案，需要人核对后处理。 */
function StatusHint({ finding, projectId }: { finding: Finding; projectId: string }) {
  if (finding.status === 'confirmed') {
    return (
      <p className="text-muted-foreground">
        问题已确认，可以在下面生成改稿建议，或直接修改正文后重新上传。
      </p>
    );
  }
  if (finding.status === 'revision_pending') {
    return (
      <div
        className="mb-4 rounded-md border border-warning-border bg-warning-soft px-3 py-2.5 text-[13px] text-warning-foreground [&_p]:m-0"
        role="note"
      >
        <p>
          改稿建议已采纳，等你修改正文。上传新正文后自动开始新一轮评审；
          <strong>在新一轮报告里看这条问题还在不在</strong>，再标记已解决。
        </p>
        <p>
          <Link className={textLink} to={`/projects/${projectId}/materials?role=body`}>
            上传修改后的正文
          </Link>
        </p>
      </div>
    );
  }
  if (finding.status === 'deferred' && finding.required_facts.length > 0) {
    return (
      <div
        className="mb-4 rounded-md border border-warning-border bg-warning-soft px-3 py-2.5 text-[13px] text-warning-foreground [&_p]:m-0"
        role="note"
      >
        <p>已暂缓，等待补充事实：录入事实后回报告重新评审。</p>
        <p>
          <Link className={textLink} to={`/projects/${projectId}/basis?tab=facts`}>
            录入事实
          </Link>
        </p>
      </div>
    );
  }
  return null;
}

function revisionErrorTitle(e: unknown, fallback: string): string {
  if (isApiError(e)) {
    if (e.is('base_version_stale')) return '底稿已有新版本，这份建议已过期';
    if (e.is('revision_already_reviewed')) return '这份建议已被处理';
  }
  return fallback;
}

/** 这两类错误重试没有意义：列表已刷新，应以最新状态为准。 */
function isTerminalRevisionError(e: unknown): boolean {
  return isApiError(e) && (e.is('base_version_stale') || e.is('revision_already_reviewed'));
}

function RevisionTab({ finding, projectId }: { finding: Finding; projectId: string }) {
  const files = useFiles(projectId).data;
  const qc = useQueryClient();
  const snap = useSnapshot(finding.snapshot_id);
  const revisions = useRevisions(projectId);
  const facts = useFacts(projectId);
  const [pickedFacts, setPickedFacts] = useState<Set<string>>(new Set());
  const [scope, setScope] = useState('');
  const [touched, setTouched] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [adopting, setAdopting] = useState<Revision | null>(null);
  const [rejecting, setRejecting] = useState<Revision | null>(null);
  const propose = useProposeRevision(projectId, (t) => {
    setTaskId(t.task_id);
    setScope('');
    setPickedFacts(new Set());
    setTouched(false);
  });
  // 改稿的底稿必须是本轮评审的输入里的正文版本（后端校验），不由用户另选。
  const baseId = snap.data?.body_version_id ?? '';
  const baseFile = files?.find((f) => f.version_id === baseId);
  const canRevise = finding.status === 'confirmed' && finding.required_facts.length === 0;
  const factItems = facts.data?.items ?? [];
  // 事实集更换（录入／撤回）后条目 ID 全部更换：清空此前的勾选。
  const factSetKey = facts.data?.fact_set_id ?? null;
  const [seenFactSet, setSeenFactSet] = useState(factSetKey);
  if (seenFactSet !== factSetKey) {
    setSeenFactSet(factSetKey);
    setPickedFacts(new Set());
  }
  const scopeErr = touched && !scope.trim() ? '请写明允许修改的范围，例如章节名' : null;
  const mine = (revisions.data ?? []).filter((r) => r.finding_ids.includes(finding.finding_id));

  return (
    <div>
      <p className="text-muted-foreground">
        建议只改你写明的范围，不会改动正文文件。采纳后自己修改正文并重新上传。
      </p>
      {!canRevise ? (
        <Notice>
          {finding.required_facts.length > 0 ? (
            <>
              还缺事实，不能生成建议：先到
              <Link className={textLink} to={`/projects/${projectId}/basis?tab=facts`}>
                事实库
              </Link>
              录入，再回报告重新评审。
            </>
          ) : (
            '先确认问题，再生成改稿建议。'
          )}
        </Notice>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setTouched(true);
            if (!scope.trim() || !baseId) return;
            propose.mutate({
              base_version_id: baseId,
              snapshot_id: finding.snapshot_id,
              finding_ids: [finding.finding_id],
              allowed_fact_ids: factItems
                .filter((f) => pickedFacts.has(f.fact_id))
                .map((f) => f.fact_id),
              scope: scope.trim(),
            });
          }}
          noValidate
        >
          {snap.isError ? (
            <ErrorNotice error={snap.error} title="无法读取这一轮的资料范围" />
          ) : null}
          <div className="grid gap-x-4 sm:grid-cols-2">
            <Field label="修改底稿" hint="这一轮评审用的施组正文">
              {(p) => (
                <Input
                  {...p}
                  readOnly
                  value={
                    baseId
                      ? `${baseFile?.original_name ?? '施组正文'}（第 ${String(baseFile?.version_number ?? 1)} 版）`
                      : snap.isPending
                        ? '读取中…'
                        : '未知'
                  }
                />
              )}
            </Field>
            <Field
              label="允许修改的范围"
              error={scopeErr}
              hint="例如章节名；建议只在这一范围内修改"
            >
              {(p) => (
                <Input
                  {...p}
                  value={scope}
                  onChange={(e) => {
                    setScope(e.target.value);
                  }}
                />
              )}
            </Field>
          </div>
          {facts.isError ? <ErrorNotice error={facts.error} title="事实库无法读取" /> : null}
          {factItems.length > 0 ? (
            <FactPicker facts={factItems} selected={pickedFacts} onChange={setPickedFacts} />
          ) : (
            <p className="text-muted-foreground">事实库是空的，建议里不会出现正文以外的参数。</p>
          )}
          {propose.isError ? <ErrorNotice error={propose.error} title="没有生成建议" /> : null}
          <Button type="submit" disabled={propose.isPending || !baseId}>
            {propose.isPending ? '正在提交…' : '生成改稿建议'}
          </Button>
        </form>
      )}
      {taskId ? (
        <TaskProgress
          key={taskId}
          taskId={taskId}
          projectId={projectId}
          onSucceeded={() => {
            void qc.invalidateQueries({ queryKey: revisionKeys.list(projectId) });
          }}
        />
      ) : null}
      {revisions.isError ? (
        <ErrorNotice error={revisions.error} onRetry={() => void revisions.refetch()} />
      ) : null}
      {mine.map((r) => (
        <div
          key={r.revision_id}
          className="mt-4 rounded-md border border-ai-border bg-ai-soft/60 px-4 py-3 [&>p]:m-0"
        >
          <p>
            {r.status === 'proposed' ? (
              <AiBadge />
            ) : (
              <Tag tone={r.status === 'adopted' ? 'green' : 'gray'}>
                {revisionStatusLabel(r.status)}
              </Tag>
            )}
          </p>
          <RevisionDiffView revisionId={r.revision_id} />
          {r.status === 'proposed' ? (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                onClick={() => {
                  setAdopting(r);
                }}
              >
                采纳
              </Button>
              <Button
                onClick={() => {
                  setRejecting(r);
                }}
              >
                驳回
              </Button>
            </div>
          ) : null}
          {r.status === 'stale' ? (
            <p className="text-muted-foreground">
              正文已经更新，这份建议过期了，可以基于新正文重新生成。
            </p>
          ) : null}
        </div>
      ))}
      {adopting ? (
        <AdoptDialog
          projectId={projectId}
          revision={adopting}
          onClose={() => {
            setAdopting(null);
          }}
        />
      ) : null}
      {rejecting ? (
        <RejectDialog
          projectId={projectId}
          revision={rejecting}
          onClose={() => {
            setRejecting(null);
          }}
        />
      ) : null}
    </div>
  );
}

/** 展开后读取差异正文：逐条“原文 → 替换文”，并汇总被丢弃的候选及原因。 */
function RevisionDiffView({
  revisionId,
  defaultOpen = false,
}: {
  revisionId: string;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const q = useRevisionDiff(revisionId, open);
  const dropped = q.data?.dropped ?? [];
  const reasons = new Map<string, number>();
  for (const d of dropped) reasons.set(d.reason, (reasons.get(d.reason) ?? 0) + 1);
  return (
    <div className="mt-2">
      <button
        type="button"
        className={textLink}
        aria-expanded={open}
        onClick={() => {
          setOpen((o) => !o);
        }}
      >
        {open ? '收起修改内容' : '查看修改内容'}
      </button>
      {open && q.isPending ? <Loading label="正在读取修改内容…" /> : null}
      {open && q.isError ? (
        <ErrorNotice error={q.error} title="修改内容无法读取" onRetry={() => void q.refetch()} />
      ) : null}
      {open && q.data ? (
        <>
          {q.data.edits.length === 0 ? (
            <p className="text-muted-foreground">这份建议没有可采纳的具体修改。</p>
          ) : (
            <ol className="mt-2 mb-0 list-decimal space-y-3 pl-5 text-[13px]">
              {q.data.edits.map((e, i) => (
                <li key={`${e.evidence_id}-${String(i)}`}>
                  <p className="m-0">
                    <span className="mr-2 text-xs text-muted-foreground">原文</span>
                    <del className="text-danger-foreground decoration-danger/60">{e.original}</del>
                  </p>
                  <p className="m-0">
                    <span className="mr-2 text-xs text-muted-foreground">改为</span>
                    <ins className="bg-success-soft text-success-foreground no-underline">
                      {e.replacement}
                    </ins>
                  </p>
                  {e.note ? <p className="text-muted-foreground">说明：{e.note}</p> : null}
                  {e.facts_used.length > 0 ? (
                    <p className="text-muted-foreground">使用的事实：{e.facts_used.join('、')}</p>
                  ) : null}
                </li>
              ))}
            </ol>
          )}
          {dropped.length > 0 ? (
            <p className="text-muted-foreground">
              另有 {dropped.length} 条候选修改被系统丢弃：
              {[...reasons.entries()]
                .map(([r, n]) => `${droppedReasonLabel(r)} ${String(n)} 条`)
                .join('；')}
              。
            </p>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function AdoptDialog({
  projectId,
  revision,
  onClose,
}: {
  projectId: string;
  revision: Revision;
  onClose: () => void;
}) {
  const toast = useToast();
  const adopt = useAdoptRevision(projectId, () => {
    toast.notify('已采纳改稿建议');
    onClose();
  });
  const blocked = isTerminalRevisionError(adopt.error);
  return (
    <Dialog title="采纳改稿建议" onClose={onClose}>
      <p>采纳后这条问题进入“待修改”。按建议改好正文后重新上传，系统自动开始新一轮评审。</p>
      <RevisionDiffView revisionId={revision.revision_id} defaultOpen />
      {adopt.isError ? (
        <ErrorNotice error={adopt.error} title={revisionErrorTitle(adopt.error, '采纳未完成')} />
      ) : null}
      <DialogActions>
        <Button onClick={onClose}>{blocked ? '关闭' : '取消'}</Button>
        <Button
          variant="primary"
          disabled={adopt.isPending || blocked}
          onClick={() => {
            adopt.mutate(revision);
          }}
        >
          {adopt.isPending ? '正在采纳…' : '确认采纳'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function RejectDialog({
  projectId,
  revision,
  onClose,
}: {
  projectId: string;
  revision: Revision;
  onClose: () => void;
}) {
  const toast = useToast();
  const [reason, setReason] = useState('');
  const [touched, setTouched] = useState(false);
  const reject = useRejectRevision(projectId, () => {
    toast.notify('已驳回改稿建议');
    onClose();
  });
  const blocked = isTerminalRevisionError(reject.error);
  const err = touched && !reason.trim() ? '请填写驳回理由' : null;
  return (
    <Dialog title="驳回改稿建议" onClose={onClose}>
      <Field label="理由" error={err}>
        {(p) => (
          <Textarea
            {...p}
            rows={3}
            value={reason}
            onChange={(e) => {
              setReason(e.target.value);
            }}
            data-autofocus
          />
        )}
      </Field>
      {reject.isError ? (
        <ErrorNotice error={reject.error} title={revisionErrorTitle(reject.error, '驳回未完成')} />
      ) : null}
      <DialogActions>
        <Button onClick={onClose}>{blocked ? '关闭' : '取消'}</Button>
        <Button
          variant="primary"
          disabled={reject.isPending || blocked}
          onClick={() => {
            setTouched(true);
            if (reason.trim()) reject.mutate({ revision, reason: reason.trim() });
          }}
        >
          {reject.isPending ? '正在提交…' : '确认驳回'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
