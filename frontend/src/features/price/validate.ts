import type { BenchmarkMethod, PricePlan, PricePlanRequest, PriceRuleTerm } from '../../api/types';

/** 与后端 PositiveDecimal / NonNegativeDecimal 的 pattern 一致：十进制字符串，不接受科学计数法、符号与千分位。 */
export const POSITIVE_DECIMAL_RE = /^(0\.[0-9]*[1-9][0-9]*|[1-9][0-9]*(\.[0-9]+)?)$/;
export const NON_NEGATIVE_DECIMAL_RE = /^(0|[1-9][0-9]*)(\.[0-9]+)?$/;

/** 与后端一致：十进制字符串至多 24 个字符。 */
export const MAX_DECIMAL_CHARS = 24;
export const MAX_COMPETITORS = 200;
export const MAX_CANDIDATES = 20;
export const MAX_NOTE = 500;

export interface PriceDraft {
  fullScore: string;
  aboveDeduct: string;
  belowDeduct: string;
  maxLimit: string;
  abnormalLowPct: string;
  method: BenchmarkMethod;
  fixedValue: string;
  coefficient: string;
  trimPct: string;
  includeOwn: boolean;
  /** 竞争对手报价，一行一个；粘贴一列也可以。 */
  competitors: string;
  candidates: string;
  note: string;
}

export const EMPTY_DRAFT: PriceDraft = {
  fullScore: '',
  aboveDeduct: '',
  belowDeduct: '',
  maxLimit: '',
  abnormalLowPct: '',
  method: 'average',
  fixedValue: '',
  coefficient: '1',
  trimPct: '0',
  includeOwn: false,
  competitors: '',
  candidates: '',
  note: '',
};

/** 按招标文件提取的评标价规则填入：只覆盖原文写明的项，没写的保持原值。 */
export function draftFromTerm(base: PriceDraft, t: PriceRuleTerm): PriceDraft {
  return {
    ...base,
    fullScore: t.full_score ?? base.fullScore,
    aboveDeduct: t.above_deduct_per_pct ?? base.aboveDeduct,
    belowDeduct: t.below_deduct_per_pct ?? base.belowDeduct,
    maxLimit: t.max_limit ?? base.maxLimit,
    abnormalLowPct: t.abnormal_low_pct ?? base.abnormalLowPct,
    method: t.method ?? base.method,
    coefficient: t.coefficient ?? base.coefficient,
    trimPct: t.trim_pct ?? base.trimPct,
  };
}

/** 常见的评标价办法：只设定取法与扣分规则，满分、限价与报价保持不变。 */
export const PRICE_TEMPLATES: { label: string; apply: Partial<PriceDraft> }[] = [
  {
    label: '有效报价平均值，高 1 低 0.5',
    apply: { method: 'average', coefficient: '1', aboveDeduct: '1', belowDeduct: '0.5' },
  },
  {
    label: '去掉最高最低各 10% 后平均',
    apply: {
      method: 'trimmed_average',
      trimPct: '10',
      coefficient: '1',
      aboveDeduct: '1',
      belowDeduct: '0.5',
    },
  },
  { label: '固定基准价（如招标控制价下浮）', apply: { method: 'fixed' } },
];

export type DraftErrors = Partial<Record<keyof PriceDraft, string>>;

const THOUSANDS_RE = /^[0-9]{1,3}(,[0-9]{3})+(\.[0-9]+)?$/;

/**
 * 把粘贴的文本拆成报价列表：换行、空白、分号、顿号、中文逗号分隔；
 * 英文逗号只有在不是千分位（如 1,200,000）时才当分隔符。千分位会被去掉。
 */
export function splitPrices(text: string): string[] {
  return text
    .split(/[\s;；、，]+/)
    .filter(Boolean)
    .flatMap((tok) => (THOUSANDS_RE.test(tok) ? [tok.replaceAll(',', '')] : tok.split(',')))
    .filter(Boolean);
}

/** 校验一个报价列表，返回第一处错误的中文说明；没有错误返回 null。 */
function listError(text: string, max: number, what: string): string | null {
  const items = splitPrices(text);
  if (items.length > max) return `${what}最多 ${String(max)} 个，现在有 ${String(items.length)} 个`;
  const badIndex = items.findIndex(
    (x) => !POSITIVE_DECIMAL_RE.test(x) || x.length > MAX_DECIMAL_CHARS,
  );
  if (badIndex >= 0) {
    return `第 ${String(badIndex + 1)} 个“${items[badIndex] ?? ''}”不是有效的正数（只写数字，不带单位、符号或科学计数法）`;
  }
  return null;
}

export function validateDraft(d: PriceDraft): DraftErrors {
  const e: DraftErrors = {};
  const tooLong = (v: string) => v.trim().length > MAX_DECIMAL_CHARS;
  if (!POSITIVE_DECIMAL_RE.test(d.fullScore.trim()) || tooLong(d.fullScore))
    e.fullScore = '请填写大于 0 的价格分满分，例如 30';
  if (!NON_NEGATIVE_DECIMAL_RE.test(d.aboveDeduct.trim()))
    e.aboveDeduct = '请填写不小于 0 的数，例如 1；不扣分填 0';
  if (!NON_NEGATIVE_DECIMAL_RE.test(d.belowDeduct.trim()))
    e.belowDeduct = '请填写不小于 0 的数，例如 0.5；不扣分填 0';
  if (d.maxLimit.trim() && (!POSITIVE_DECIMAL_RE.test(d.maxLimit.trim()) || tooLong(d.maxLimit)))
    e.maxLimit = '最高限价须是大于 0 的数；没有可留空';
  if (d.abnormalLowPct.trim() && !NON_NEGATIVE_DECIMAL_RE.test(d.abnormalLowPct.trim()))
    e.abnormalLowPct = '异常低价线须是不小于 0 的百分数，例如 15；没有可留空';
  if (d.method === 'fixed') {
    if (!POSITIVE_DECIMAL_RE.test(d.fixedValue.trim()) || tooLong(d.fixedValue))
      e.fixedValue = '固定基准价须是大于 0 的数';
  }
  if (!POSITIVE_DECIMAL_RE.test(d.coefficient.trim()))
    e.coefficient = '系数须是大于 0 的数，例如 0.98；没有填 1';
  if (d.method === 'trimmed_average' && !NON_NEGATIVE_DECIMAL_RE.test(d.trimPct.trim()))
    e.trimPct = '去极值比例须是不小于 0 的百分数，例如 10';
  const comp = listError(d.competitors, MAX_COMPETITORS, '竞争对手报价');
  if (comp) e.competitors = comp;
  const cand = listError(d.candidates, MAX_CANDIDATES, '候选报价');
  if (cand) e.candidates = cand;
  if (d.note.trim().length > MAX_NOTE) e.note = `备注最多 ${String(MAX_NOTE)} 字`;
  return e;
}

/** 没有错误时把草稿转成请求体；有错误返回 null。 */
export function toRequest(d: PriceDraft): PricePlanRequest | null {
  if (Object.keys(validateDraft(d)).length > 0) return null;
  const optional = (v: string) => (v.trim() ? v.trim() : null);
  return {
    params: {
      full_score: d.fullScore.trim(),
      above_deduct_per_pct: d.aboveDeduct.trim(),
      below_deduct_per_pct: d.belowDeduct.trim(),
      max_limit: optional(d.maxLimit),
      abnormal_low_pct: optional(d.abnormalLowPct),
      benchmark: {
        method: d.method,
        fixed_value: d.method === 'fixed' ? d.fixedValue.trim() : null,
        coefficient: d.coefficient.trim(),
        trim_pct: d.method === 'trimmed_average' ? d.trimPct.trim() : '0',
        include_own: d.method === 'fixed' ? false : d.includeOwn,
      },
    },
    competitor_prices: splitPrices(d.competitors),
    candidate_prices: splitPrices(d.candidates),
    note: d.note.trim(),
  };
}

/** 已保存的方案 → 表单草稿。 */
export function draftFromPlan(
  p: Pick<PricePlan, 'params' | 'competitor_prices' | 'candidate_prices' | 'note'>,
): PriceDraft {
  const b = p.params.benchmark;
  return {
    fullScore: p.params.full_score,
    aboveDeduct: p.params.above_deduct_per_pct,
    belowDeduct: p.params.below_deduct_per_pct,
    maxLimit: p.params.max_limit ?? '',
    abnormalLowPct: p.params.abnormal_low_pct ?? '',
    method: b.method,
    fixedValue: b.fixed_value ?? '',
    coefficient: b.coefficient,
    trimPct: b.trim_pct,
    includeOwn: b.include_own,
    competitors: p.competitor_prices.join('\n'),
    candidates: p.candidate_prices.join('\n'),
    note: p.note,
  };
}
