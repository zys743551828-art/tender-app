import type { Decision, FindingNature, FindingStatus } from '../../api/types';
import type { Tone } from '../../lib/labels';

export const NATURE_TONE: Record<FindingNature, Tone> = {
  fact_conflict: 'amber',
  needs_confirmation: 'amber',
  suggestion: 'gray',
};

export function statusTone(s: FindingStatus): Tone {
  if (s === 'resolved') return 'green';
  if (s === 'rejected') return 'gray';
  if (s === 'candidate') return 'ai';
  return 'blue';
}

/** 未结案（需要人处理）的状态。 */
export const OPEN_STATUSES: readonly FindingStatus[] = [
  'candidate',
  'deferred',
  'confirmed',
  'revision_pending',
  'recheck_pending',
];

/**
 * 各状态下允许提交的审核动作，对应后端 services/findings.py 的状态转换
 * （第一项作为主按钮，除非见 RESOLVE_WARNING）。已驳回、已解决可“重新打开”。
 * 最终是否允许仍由服务端判定。
 */
export const ALLOWED_DECISIONS: Record<string, Decision[]> = {
  candidate: ['confirm', 'reject', 'defer', 'request_facts'],
  deferred: ['confirm', 'reject'],
  confirmed: ['resolve'],
  recheck_pending: ['resolve', 'confirm'],
  revision_pending: ['reject', 'resolve'],
  rejected: ['reopen'],
  resolved: ['reopen'],
};

/**
 * 在这些状态下“标记已解决”是绕过正常路径（采纳修改 → 改正文 → 复检）的人工结案：
 * 只作次要按钮，并在旁边写明风险。
 */
export const RESOLVE_WARNING: Partial<Record<FindingStatus, string>> = {
  confirmed:
    '尚未采纳修改建议，也未复检：直接标记“已解决”表示你已确认无需修改或已在系统外处理，理由里请写明依据。',
  revision_pending:
    '修改建议已采纳，但新正文尚未复检（重新评审）：此时标记“已解决”只代表你人工认定，系统没有核对过。',
};

/** 主按钮：列表第一项；带风险提示的“标记已解决”永远不做主按钮。 */
export function isPrimaryDecision(status: string, decision: Decision, index: number): boolean {
  if (decision === 'resolve' && RESOLVE_WARNING[status as FindingStatus]) return false;
  return index === 0;
}

/** 问题的稳定短码：取 ID 去掉前缀后的前 6 位，列表顺序变化、翻页、筛选都不会改变它。 */
export function findingCode(id: string): string {
  return `#${id
    .replace(/^[a-z]+[_-]/i, '')
    .slice(0, 6)
    .toUpperCase()}`;
}
