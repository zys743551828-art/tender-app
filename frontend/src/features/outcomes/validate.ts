import type { OutcomeRequest, OutcomeTarget, StageResult } from '../../api/types';
import { compareDecimal, DECIMAL_RE } from '../../lib/format';

export interface OutcomeDraft {
  submissionId: string;
  sourceKind: 'user_reported' | 'official';
  target: OutcomeTarget;
  value: string;
  maximum: string;
  aggregation: string;
  stageResult: StageResult;
  publishedAt: string;
  sourceArtifactId: string;
  sourcePage: string;
  sourceDescription: string;
  supersedes: string;
  scoreUnknown?: boolean;
}

const needScoreText = (what: string) => `请填写${what}；未公布请勾选「分值未知」`;

export type OutcomeErrors = Partial<Record<keyof OutcomeDraft, string>>;

/** 分值只做十进制字符串校验与比较；未知须显式选择，保留成绩类型与 null。 */
export function validateOutcome(d: OutcomeDraft): OutcomeErrors {
  const e: OutcomeErrors = {};
  if (!d.submissionId.trim()) e.submissionId = '请先关联实际提交（填写提交 ID）';
  const scored = d.target !== 'no_score';
  const value = d.value.trim();
  const max = d.maximum.trim();
  if (scored && d.scoreUnknown) {
    if (value) e.value = '分值未知时不能填写分值';
    if (max && (!DECIMAL_RE.test(max) || compareDecimal(max, '0') <= 0))
      e.maximum = '已知满分须为大于 0 的十进制数字';
  } else if (scored) {
    // 没有明确选择未知时，仍要求同时给出分值与满分。
    if (!value) e.value = needScoreText('分值');
    else if (!DECIMAL_RE.test(value)) e.value = '分值须为十进制数字，如 86.5';
    if (!max) e.maximum = needScoreText('满分');
    else if (!DECIMAL_RE.test(max)) e.maximum = '满分须为十进制数字，如 100';
    if (value && max && !e.value && !e.maximum && compareDecimal(value, max) > 0)
      e.value = '分值不能大于满分';
  } else if (value || max) {
    e.value = '“无分值”只登记阶段结果，请清空分值与满分';
  }
  if (d.sourcePage.trim() && !/^[1-9][0-9]*$/.test(d.sourcePage.trim()))
    e.sourcePage = '页码须为正整数';
  if (d.sourcePage.trim() && !d.sourceArtifactId)
    e.sourceArtifactId = '填写了来源页码，请同时选择来源资料';
  if (d.stageResult === 'awarded' && (!d.sourceArtifactId || !d.sourcePage.trim())) {
    e.stageResult = '登记“最终中标”需要官方来源资料和页码，不会仅凭报送把候选人转为中标';
  }
  if (!d.sourceDescription.trim())
    e.sourceDescription = '请说明结果来源（例如公示网站、文件名或通知方式）';
  return e;
}

export function toOutcomeRequest(
  d: OutcomeDraft,
  toIso: (v: string) => string | null,
): OutcomeRequest {
  const scored = d.target !== 'no_score';
  return {
    submission_id: d.submissionId.trim(),
    source_kind: d.sourceKind,
    target: d.target,
    value: scored && d.value.trim() ? d.value.trim() : null,
    maximum: scored && d.maximum.trim() ? d.maximum.trim() : null,
    aggregation: d.aggregation.trim() || null,
    stage_result: d.stageResult,
    source_page: d.sourcePage.trim() ? Number(d.sourcePage.trim()) : null,
    published_at: toIso(d.publishedAt),
    supersedes: d.supersedes.trim() || null,
    source_artifact_id: d.sourceArtifactId || null,
    source_description: d.sourceDescription.trim(),
    score_unknown: scored && !!d.scoreUnknown,
  };
}
