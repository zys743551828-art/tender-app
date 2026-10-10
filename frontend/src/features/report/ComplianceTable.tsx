import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { Compliance, RuleSet, RuleVerdict, Verdict } from '../../api/types';
import { useToast } from '../../components/Toast';
import { Icon } from '../../components/Icon';
import { Alert, ErrorNotice, Tag } from '../../components/ui';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '../../components/ui/card';
import { cn } from '../../lib/cn';
import { ruleKindLabel, verdictLabel, type Tone } from '../../lib/labels';
import { useReviewRule } from '../rules/actions';
import { useRuleSet } from '../rules/queries';
import { Button, textLink } from '../../components/ui/button';

const ORDER: Record<Verdict, number> = { violated: 0, failed: 1, unclear: 2, satisfied: 3 };
const TONE: Record<Verdict, Tone> = {
  violated: 'red',
  failed: 'red',
  unclear: 'amber',
  satisfied: 'green',
};
const GLYPH: Record<Verdict, string> = { violated: '✕', failed: '!', unclear: '?', satisfied: '✓' };

/** 违反与检查失败、无法判断排在前面：它们需要人看，“满足”放最后。 */
export function sortVerdictRows(rows: readonly RuleVerdict[]): RuleVerdict[] {
  return [...rows].sort((a, b) => ORDER[a.verdict] - ORDER[b.verdict]);
}

const QUALIFICATION_KINDS = new Set(['disqualification', 'mandatory']);

/**
 * 废标／否决与强制类规则的“无法判断”“检查失败”都不等于“满足”，整行醒目标出；
 * 评分条款没有“满足”一说（得分由评分预测评估），不标。
 */
export function needsAttention(r: Pick<RuleVerdict, 'verdict' | 'kind'>): boolean {
  return (r.verdict === 'unclear' || r.verdict === 'failed') && QUALIFICATION_KINDS.has(r.kind);
}

/** 默认展开的行：违反的条款，以及废标／强制类里正文没有明确响应或检查失败的条款。评分条款的得分看预测。 */
export function needsReview(r: Pick<RuleVerdict, 'verdict' | 'kind'>): boolean {
  return r.verdict === 'violated' || needsAttention(r);
}

/** 当前规则包里仍待核对的规则：只有它们能在报告里直接确认（规则包已更新的旧行不提供确认）。 */
function pendingIds(set: RuleSet | null | undefined): Set<string> {
  return new Set(
    (set?.rules ?? []).filter((r) => r.confirmation === 'pending').map((r) => r.rule_id),
  );
}

/**
 * 响应矩阵：废标／否决、强制性要求与评分条款逐条的判定和正文依据。
 * 默认只展开需要人看的行（违反、无法判断、检查失败），满足的收起；未核对的规则可以在行内直接确认。
 * 窄屏下每行变成一张卡片。
 */
export function ComplianceTable({
  compliance,
  projectId,
}: {
  compliance: Compliance;
  projectId: string;
}) {
  const [showAll, setShowAll] = useState(false);
  const toast = useToast();
  const rules = useRuleSet(projectId);
  const pending = pendingIds(rules.data);
  const confirm = useReviewRule(projectId, () => {
    toast.notify('已确认');
  });
  const rows = sortVerdictRows(compliance.rows);
  const flagged = rows.filter(needsReview);
  const shown = showAll ? rows : flagged;
  const hidden = rows.length - shown.length;
  const q = compliance.qualification;
  const coverage = compliance.coverage;
  return (
    <Card id="matrix" aria-labelledby="matrix-h" className="mb-5 scroll-mt-6">
      <CardHeader className="items-start">
        <div>
          <CardTitle id="matrix-h">逐条响应</CardTitle>
          <CardDescription className="mt-0.5">
            废标／强制要求 {q.total} 条：满足 {q.satisfied}
            {q.violated ? `，违反 ${String(q.violated)}` : ''}
            {q.unclear ? `，正文没有明确响应 ${String(q.unclear)}` : ''}
            {q.failed ? `，检查失败 ${String(q.failed)}` : ''}
            {compliance.scoring.total ? ` · 评分条款 ${String(compliance.scoring.total)} 条` : ''}
          </CardDescription>
        </div>
        {hidden > 0 || showAll ? (
          <Button
            size="sm"
            variant="ghost"
            aria-expanded={showAll}
            onClick={() => {
              setShowAll((v) => !v);
            }}
          >
            {showAll ? '只看需要处理的' : `显示其余 ${String(hidden)} 条（已满足或评分条款）`}
          </Button>
        ) : null}
      </CardHeader>
      <CardContent>
        {coverage && coverage.status !== 'complete' ? (
          <Alert tone="danger">
            这一轮只核对了 {coverage.rules_checked} / {coverage.rules_total} 条规则，结果不完整。
          </Alert>
        ) : null}
        {rows.length === 0 ? (
          <p className="m-0 text-[13px] text-muted-foreground">没有可核对的规则。</p>
        ) : shown.length === 0 ? (
          <p className="m-0 flex items-center gap-2 text-[13px] text-success-foreground">
            <Icon name="CircleCheck" />
            废标／强制要求在正文里都有明确响应。
          </p>
        ) : (
          <div className="relative w-full overflow-x-auto">
            <table className="data-table stack-mobile">
              <caption className="sr-only">规则逐条判定</caption>
              <thead>
                <tr>
                  <th scope="col">条款</th>
                  <th scope="col" className="w-28">
                    判定
                  </th>
                  <th scope="col">正文怎么写的</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.rule_id} className={needsAttention(r) ? 'row-alert' : undefined}>
                    <th scope="row" className="min-w-[220px]">
                      <span className="mb-0.5 block text-xs text-muted-foreground">
                        {ruleKindLabel(r.kind)}
                      </span>
                      <span className="font-medium">{r.statement}</span>
                      {r.note ? <small className="mt-0.5">{r.note}</small> : null}
                      {r.rule_basis === 'unconfirmed' ? (
                        <span className="mt-1.5 flex items-center gap-2 text-xs text-warning-foreground">
                          <span aria-hidden="true" className="size-1.5 rounded-full bg-warning" />
                          规则未核对
                          {pending.has(r.rule_id) && rules.data ? (
                            <button
                              type="button"
                              className={cn(textLink, 'text-xs')}
                              disabled={confirm.isPending}
                              onClick={() => {
                                confirm.mutate({
                                  ruleId: r.rule_id,
                                  version: rules.data?.revision ?? 0,
                                  decision: 'confirm',
                                });
                              }}
                            >
                              按原文确认
                            </button>
                          ) : null}
                        </span>
                      ) : null}
                    </th>
                    <td data-label="判定">
                      <Tag tone={TONE[r.verdict]}>
                        <span aria-hidden="true">{GLYPH[r.verdict]}</span>
                        {verdictLabel(r.verdict)}
                      </Tag>
                    </td>
                    <td data-label="正文怎么写的">
                      {r.evidence.length === 0 && r.finding_ids.length > 0 ? (
                        <Link
                          className={textLink}
                          to={`/projects/${projectId}/findings?category=${r.kind === 'disqualification' ? 'disqualification' : r.kind === 'mandatory' ? 'response' : 'improvement'}`}
                        >
                          看问题（{r.finding_ids.length} 个）
                        </Link>
                      ) : r.evidence.length === 0 ? (
                        <span className="text-muted-foreground">正文没有写到</span>
                      ) : (
                        r.evidence.map((ev) => (
                          <p key={ev.evidence_id} className="m-0 mb-1 leading-relaxed">
                            <q className="text-foreground">{ev.quote}</q>{' '}
                            <Link
                              className={cn(textLink, 'text-xs whitespace-nowrap')}
                              to={`/projects/${projectId}/evidence/${ev.evidence_id}`}
                            >
                              第 {ev.physical_page} 页
                            </Link>
                          </p>
                        ))
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {confirm.isError ? <ErrorNotice error={confirm.error} title="没有确认成功" /> : null}
      </CardContent>
    </Card>
  );
}
