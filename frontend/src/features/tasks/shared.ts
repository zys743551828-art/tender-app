import type { Task } from '../../api/types';
import type { Tone } from '../../lib/labels';

export const STATE_TONE: Record<Task['state'], Tone> = {
  queued: 'gray',
  running: 'blue',
  waiting_input: 'amber',
  succeeded: 'green',
  failed: 'red',
  cancel_requested: 'amber',
  cancelled: 'gray',
};

export const ERROR_HINT: Record<string, string> = {
  MISSING_FACTS: '缺少必要的工程事实：补充事实后可重试。',
  RULE_CONFLICT: '规则之间存在冲突：先在“依据”页并列依据并确认。',
  PROVIDER_RATE_LIMIT: '模型服务限流：稍后重试，已有资料保留。',
  BUDGET_LIMIT: '已达额度上限：已有资料保留，请联系负责人。',
  PROVIDER_TIMEOUT: '模型服务超时：可重试，已完成的人工工作保留。',
  STORAGE_UNAVAILABLE: '原件存储暂不可用：不要把打不开的证据当作“没有问题”，恢复后核对原页。',
  INCOMPLETE_GENERATION: '模型输出被截断：本次没有有效结果，可有限重试。',
  PARSE_UNREADABLE: '没有读到文字：请提供可复制文字的 PDF 后重新上传。',
  PARSE_UNSUPPORTED: '只支持 PDF 格式：请转换后重新上传。',
  EVIDENCE_UNSUPPORTED: '证据不足以支持结论：本次结果不作为完成的评审。',
};

export function errorHint(code: string): string {
  return (
    ERROR_HINT[code.toUpperCase()] ??
    `任务失败（${code}）。已完成的人工工作保留，可在条件满足后重试。`
  );
}
