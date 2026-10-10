import { isApiError } from '../api/errors';

/**
 * 登记提交、重新评审时后端可能返回的 409。后端中文 message 始终原样显示；
 * 这里只补一句“接下来怎么做”。错误码按关键字匹配（不区分大小写），认不出的不加提示。
 */
function codeOf(e: unknown): string | null {
  return isApiError(e) && e.kind === 'conflict' ? e.code.toLowerCase() : null;
}

export function submissionErrorHint(e: unknown): string | null {
  const c = codeOf(e);
  if (!c) return null;
  if (c === 'qualification_rules_unconfirmed')
    return '废标／否决／强制类规则还没有全部确认：请到“依据”页确认或驳回，确认后才能登记提交。';
  if (c === 'critical_findings_open')
    return '还有关键问题或废标／强制响应类问题未处理完：请到“问题”页确认并修改、驳回或标记已解决。';
  if (/(undiagnos|not_diagnosed|no_diagnosis)/.test(c))
    return '这一轮评审还没有完成：请回到“报告”查看评审进度。';
  if (c.includes('diagnosis_incomplete'))
    return '这一轮评审没有完整覆盖全部规则（有规则核对失败）：请回到“报告”点击“重新评审”。';
  if (/(latest|stale|outdated)/.test(c))
    return '资料、规则或事实在这一轮评审之后有更新：请回到“报告”点击“重新评审”，完成后再登记。';
  return null;
}

/** 提交闸门里逐项未满足的条件（对应 409 的错误码），用于在表单上方列出。 */
export function submissionGateItems(e: unknown): string[] {
  const c = codeOf(e);
  if (c === 'qualification_rules_unconfirmed') return ['废标／否决／强制类规则尚未全部确认'];
  if (c === 'critical_findings_open') return ['关键问题或废标／强制响应类问题尚未处理完'];
  return [];
}
