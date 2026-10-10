import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { Decision, Rule, RuleKind, RuleSet } from '../../api/types';
import { Dialog, DialogActions } from '../../components/Dialog';
import { Icon } from '../../components/Icon';
import { cn } from '../../lib/cn';
import { useToast } from '../../components/Toast';
import { AiBadge, EmptyState, ErrorNotice, Field, Loading, Notice, Tag } from '../../components/ui';
import { ruleKindLabel } from '../../lib/labels';
import { useProjectContext } from '../../routes/ProjectLayout';
import { useConfirmPending, useReviewRule } from './actions';
import { useRuleSet } from './queries';
import { Button, textLink } from '../../components/ui/button';
import { Textarea } from '../../components/ui/input';

/** 废标／否决／强制类规则：违反即可能被否决，登记提交前必须确认或驳回。 */
export const QUALIFICATION_KINDS: readonly RuleKind[] = ['disqualification', 'mandatory'];

/** 分组顺序：废标／否决／强制在前，评分条款其后。 */
const GROUP_ORDER: RuleKind[] = [
  'disqualification',
  'mandatory',
  'scoring',
  'recommendation',
  'exception',
];

export function groupRules(rules: readonly Rule[]): { kind: RuleKind; rules: Rule[] }[] {
  return GROUP_ORDER.map((kind) => ({ kind, rules: rules.filter((r) => r.kind === kind) })).filter(
    (g) => g.rules.length > 0,
  );
}

/** 未确认（待人工确认）的废标／否决／强制类规则条数。 */
export function unconfirmedQualification(rules: readonly Rule[]): number {
  return rules.filter((r) => QUALIFICATION_KINDS.includes(r.kind) && r.confirmation === 'pending')
    .length;
}

function ruleDone(d: Decision): string {
  return d === 'confirm' ? '已确认' : d === 'reject' ? '已驳回' : '已暂缓';
}

/** 各确认状态下可做的决定：未确认可确认、驳回、暂缓；已确认可改为驳回或暂缓；已驳回可重新确认。 */
function decisionsFor(r: Rule): Decision[] {
  if (r.confirmation === 'pending') return ['confirm', 'reject', 'defer'];
  if (r.confirmation === 'confirmed') return ['reject', 'defer'];
  return ['confirm'];
}

/**
 * 依据页的“规则”标签：按性质分组。规则是模型从招标文件里提取的，核对原文后可以一条条确认，
 * 也可以一次“全部按原文确认”；不适用的驳回或暂缓。
 */
export function RulesPanel() {
  const { project } = useProjectContext();
  const pid = project.project_id;
  const toast = useToast();
  const q = useRuleSet(pid);
  const [deciding, setDeciding] = useState<{ rule: Rule; decision: Decision } | null>(null);
  const [corrected, setCorrected] = useState(false);
  const review = useReviewRule(pid, (v) => {
    if (v.corrected) setCorrected(true);
    toast.notify(ruleDone(v.decision));
  });
  const bulk = useConfirmPending(pid, (n) => {
    toast.notify(`已确认 ${String(n)} 条规则`);
  });

  if (q.isPending) return <Loading />;
  if (q.isError) return <ErrorNotice error={q.error} onRetry={() => void q.refetch()} />;
  if (q.data === null) {
    return (
      <EmptyState title="还没有提取规则">
        招标文件解析完成后会自动提取规则。没有规则不代表招标文件没有要求。
      </EmptyState>
    );
  }
  const set = q.data;
  const groups = groupRules(set.rules);
  const pending = set.rules.filter((r) => r.confirmation === 'pending');
  const open = unconfirmedQualification(set.rules);
  return (
    <>
      <BidTermsNote set={set} projectId={pid} />
      {pending.length > 0 ? (
        <div className="mb-5 flex flex-col gap-3 rounded-lg border border-ai-border bg-ai-soft px-4 py-3 text-[13px] text-ai-foreground sm:flex-row sm:items-center">
          <Icon name="Sparkles" className="hidden shrink-0 sm:block" />
          <p className="m-0 flex-1">
            <strong className="font-semibold">{pending.length} 条规则还没有人核对</strong>
            {open > 0 ? `，其中 ${String(open)} 条是废标／否决／强制类，登记提交前须确认` : ''}。
            评审暂按原文判断。
          </p>
          <Button
            variant="primary"
            size="sm"
            disabled={bulk.isPending}
            onClick={() => {
              bulk.mutate({ version: set.revision, ruleIds: pending.map((r) => r.rule_id) });
            }}
          >
            {bulk.isPending ? '正在确认…' : `全部按原文确认（${String(pending.length)} 条）`}
          </Button>
        </div>
      ) : null}
      {bulk.isError ? <ErrorNotice error={bulk.error} title="没有确认成功" /> : null}
      {corrected ? (
        <Notice>
          <strong>规则已更正，重新评审后生效。</strong>{' '}
          <Link className={textLink} to={`/projects/${pid}`}>
            回到报告
          </Link>
        </Notice>
      ) : null}
      {set.rules.length === 0 ? (
        <EmptyState title="没有提取到条款">请检查招标文件是否完整、能否正常打开。</EmptyState>
      ) : (
        groups.map((g) => (
          <section key={g.kind} aria-labelledby={`grp-${g.kind}`} className="mb-6">
            <h3 id={`grp-${g.kind}`} className="mb-2 text-[13px] font-semibold">
              {ruleKindLabel(g.kind)}（{g.rules.length}）
            </h3>
            <ul className="m-0 list-none divide-y divide-border overflow-hidden rounded-lg border border-border bg-card p-0">
              {g.rules.map((r) => (
                <RuleItem
                  key={r.rule_id}
                  rule={r}
                  projectId={pid}
                  busy={review.isPending || bulk.isPending}
                  onConfirm={() => {
                    review.mutate({
                      ruleId: r.rule_id,
                      version: set.revision,
                      decision: 'confirm',
                    });
                  }}
                  onAsk={(decision) => {
                    setDeciding({ rule: r, decision });
                  }}
                />
              ))}
            </ul>
          </section>
        ))
      )}
      {review.isError ? <ErrorNotice error={review.error} title="没有保存" /> : null}
      {deciding ? (
        <RuleReasonDialog
          projectId={pid}
          ruleSet={set}
          rule={deciding.rule}
          decision={deciding.decision}
          onCorrected={() => {
            setCorrected(true);
          }}
          onClose={() => {
            setDeciding(null);
          }}
        />
      ) : null}
    </>
  );
}

/** 从评标办法提取的技术分满分与评标价规则：报价页据此一键填入，预测据此说明覆盖了多少分。 */
function BidTermsNote({ set, projectId }: { set: RuleSet; projectId: string }) {
  const full = set.terms.technical_full_score;
  const price = set.terms.price_rule;
  if (!full && !price) return null;
  return (
    <p className="mb-3 text-[13px] text-muted-foreground">
      {full ? (
        <>
          技术标满分 {full.value} 分
          {full.evidence[0] ? (
            <>
              （
              <Link
                className={textLink}
                to={`/projects/${projectId}/evidence/${full.evidence[0].evidence_id}`}
              >
                原文第 {full.evidence[0].physical_page} 页
              </Link>
              ）
            </>
          ) : null}
        </>
      ) : null}
      {full && price ? ' · ' : null}
      {price ? (
        <>
          已提取评标价规则，
          <Link className={textLink} to={`/projects/${projectId}/price`}>
            在报价页使用
          </Link>
        </>
      ) : null}
    </p>
  );
}

function RuleItem({
  rule: r,
  projectId,
  busy,
  onConfirm,
  onAsk,
}: {
  rule: Rule;
  projectId: string;
  busy: boolean;
  onConfirm: () => void;
  onAsk: (d: Decision) => void;
}) {
  const pending = r.confirmation === 'pending';
  const critical = QUALIFICATION_KINDS.includes(r.kind) && pending;
  return (
    <li
      className={cn(
        'px-4 py-3',
        critical && 'shadow-[inset_3px_0_0_var(--danger)]',
        !critical && pending && 'shadow-[inset_3px_0_0_var(--ai)]',
      )}
    >
      <p className="m-0 text-sm leading-relaxed">{r.statement}</p>
      {r.conditions.length > 0 ? (
        <p className="m-0 mt-1 text-xs text-muted-foreground">
          成立条件：{r.conditions.join('；')}
        </p>
      ) : null}
      {r.exceptions.length > 0 ? (
        <p className="m-0 mt-1 text-xs text-muted-foreground">例外：{r.exceptions.join('；')}</p>
      ) : null}
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs">
        {pending ? <AiBadge>待核对</AiBadge> : null}
        {r.confirmation === 'rejected' ? <Tag tone="gray">已驳回</Tag> : null}
        {r.max_points ? <span className="text-muted-foreground">{r.max_points} 分</span> : null}
        {r.carried_from_rule_id ? (
          <span className="text-muted-foreground">沿用上一版决定</span>
        ) : null}
        {r.evidence.map((ev) => (
          <Link
            key={ev.evidence_id}
            className={cn(textLink, 'text-xs')}
            to={`/projects/${projectId}/evidence/${ev.evidence_id}`}
          >
            原文第 {ev.physical_page} 页
          </Link>
        ))}
        <span className="ml-auto flex items-center gap-1">
          {decisionsFor(r).map((d) => (
            <Button
              key={d}
              size="sm"
              variant={d === 'confirm' ? 'secondary' : 'ghost'}
              className="h-7"
              disabled={busy}
              onClick={() => {
                if (d === 'confirm') onConfirm();
                else onAsk(d);
              }}
            >
              {d === 'confirm' ? '确认' : d === 'reject' ? '驳回' : '暂缓'}
            </Button>
          ))}
        </span>
      </div>
    </li>
  );
}

function RuleReasonDialog({
  projectId,
  ruleSet,
  rule,
  decision,
  onCorrected,
  onClose,
}: {
  projectId: string;
  ruleSet: RuleSet;
  rule: Rule;
  decision: Decision;
  onCorrected: () => void;
  onClose: () => void;
}) {
  const toast = useToast();
  const [reason, setReason] = useState('');
  const [touched, setTouched] = useState(false);
  const m = useReviewRule(projectId, (v) => {
    if (v.corrected) onCorrected();
    toast.notify(ruleDone(decision));
    onClose();
  });
  const title = decision === 'reject' ? '驳回条款' : '暂缓条款';
  const err =
    touched && !reason.trim()
      ? decision === 'reject'
        ? '请写明驳回的理由，例如与本项目无关、条款理解有误'
        : '请写明暂缓的理由，例如等待招标方澄清'
      : null;
  return (
    <Dialog title={title} onClose={onClose}>
      <blockquote className="m-0 mb-3 border-l-2 border-border-strong bg-subtle px-3 py-2 text-sm">
        {rule.statement}
      </blockquote>
      <p className="text-muted-foreground">驳回或暂缓的条款不再参与评审，重新评审后生效。</p>
      <Field label={decision === 'reject' ? '驳回理由' : '暂缓理由'} error={err}>
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
      {m.isError ? <ErrorNotice error={m.error} title="没有保存" /> : null}
      <DialogActions>
        <Button onClick={onClose}>取消</Button>
        <Button
          variant="primary"
          disabled={m.isPending}
          onClick={() => {
            setTouched(true);
            if (reason.trim())
              m.mutate({
                ruleId: rule.rule_id,
                version: ruleSet.revision,
                decision,
                reason: reason.trim(),
              });
          }}
        >
          {title}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
