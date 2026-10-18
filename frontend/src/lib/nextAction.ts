import type { NextAction, NextActionKey } from '../api/types';

/** 每个“下一步”的按钮文字：说清楚点了要做什么，不用笼统的“去处理”。 */
const CTA: Record<NextActionKey, string> = {
  upload_materials: '上传资料',
  start_analysis: '开始评审',
  wait_analysis: '查看进度',
  retry_analysis: '重新评审',
  handle_disqualification: '处理否决风险',
  handle_critical: '处理关键风险',
  verify_facts: '核实事实',
  improve_score: '查看评分缺口',
  handle_suggestions: '查看建议',
  review_unclear: '逐条核对',
  handle_findings: '处理问题',
  reanalyze: '重新评审',
  confirm_rules: '确认规则',
  verify_sources: '核实补遗依据',
  set_price: '填写报价',
  submit: '登记提交',
  record_outcome: '登记结果',
};

export function actionLabel(a: Pick<NextAction, 'key'>): string {
  return CTA[a.key];
}

/** 下一步 → 项目内路径（base 为 /projects/:id）。落点尽量具体：否决风险直达对应分类，待核对条款直达响应矩阵。 */
export function actionPath(base: string, a: Pick<NextAction, 'key' | 'target'>): string {
  if (a.key === 'handle_disqualification') return `${base}/findings?category=disqualification`;
  if (a.key === 'review_unclear') return `${base}#matrix`;
  if (a.key === 'verify_facts') return `${base}/basis?tab=facts`;
  if (a.key === 'improve_score') return `${base}#pred-h`;
  if (a.key === 'handle_suggestions') return `${base}/findings?category=improvement`;
  switch (a.target) {
    case 'materials':
      return `${base}/materials`;
    case 'findings':
      return `${base}/findings`;
    case 'rules':
      return `${base}/basis`;
    case 'price':
      return `${base}/price`;
    case 'submit':
      return `${base}/submit`;
    case 'outcomes':
      return `${base}/submit?tab=outcomes`;
    case 'report':
      return base;
  }
}

/** 预测覆盖了多少技术分：评分条款分值合计对照评标办法写明的技术标满分。满分未知或已全覆盖时返回 null。 */
export function coverageText(maximum: string | null, fullScore: string | null): string | null {
  if (maximum === null || fullScore === null) return null;
  const covered = Number(maximum);
  const full = Number(fullScore);
  if (!Number.isFinite(covered) || !Number.isFinite(full) || full <= 0 || covered >= full)
    return null;
  return `只覆盖 ${maximum} / ${fullScore} 分`;
}
