import { describe, expect, it } from 'vitest';
import { pricePlan } from '../../test/fixtures';
import {
  EMPTY_DRAFT,
  PRICE_TEMPLATES,
  draftFromPlan,
  draftFromTerm,
  splitPrices,
  toRequest,
  validateDraft,
  type PriceDraft,
} from './validate';

const ok: PriceDraft = {
  ...EMPTY_DRAFT,
  method: 'fixed',
  fullScore: '30',
  aboveDeduct: '1',
  belowDeduct: '0.5',
  fixedValue: '1000',
  candidates: '980\n1010',
};

describe('报价表单校验（与后端十进制字符串规则一致）', () => {
  it('完整且合法的草稿没有错误，转成请求体时用字符串小数', () => {
    expect(validateDraft(ok)).toEqual({});
    expect(toRequest(ok)).toEqual({
      params: {
        full_score: '30',
        above_deduct_per_pct: '1',
        below_deduct_per_pct: '0.5',
        max_limit: null,
        abnormal_low_pct: null,
        benchmark: {
          method: 'fixed',
          fixed_value: '1000',
          coefficient: '1',
          trim_pct: '0',
          include_own: false,
        },
      },
      competitor_prices: [],
      candidate_prices: ['980', '1010'],
      note: '',
    });
  });

  it('满分必须大于 0；扣分率可以是 0 但不能为负或带符号', () => {
    expect(validateDraft({ ...ok, fullScore: '0' }).fullScore).toBeTruthy();
    expect(validateDraft({ ...ok, fullScore: '0.0' }).fullScore).toBeTruthy();
    expect(validateDraft({ ...ok, fullScore: '' }).fullScore).toBeTruthy();
    expect(validateDraft({ ...ok, aboveDeduct: '0' }).aboveDeduct).toBeUndefined();
    expect(validateDraft({ ...ok, aboveDeduct: '-1' }).aboveDeduct).toBeTruthy();
    expect(validateDraft({ ...ok, belowDeduct: '+1' }).belowDeduct).toBeTruthy();
  });

  it('拒绝科学计数法、千分位、前导零与多余空白之外的写法', () => {
    for (const bad of ['1e3', '1,000', '01', '.5', '5.', 'NaN', '１２']) {
      expect(validateDraft({ ...ok, fullScore: bad }).fullScore, bad).toBeTruthy();
    }
    expect(validateDraft({ ...ok, fullScore: ' 0.5 ' }).fullScore).toBeUndefined();
  });

  it('固定基准价必须给出；平均值法不需要固定值但需要系数为正', () => {
    expect(validateDraft({ ...ok, fixedValue: '' }).fixedValue).toBeTruthy();
    const avg = { ...ok, method: 'average' as const, fixedValue: '' };
    expect(validateDraft(avg)).toEqual({});
    expect(validateDraft({ ...avg, coefficient: '0' }).coefficient).toBeTruthy();
    expect(toRequest({ ...avg, includeOwn: true })?.params.benchmark).toEqual({
      method: 'average',
      fixed_value: null,
      coefficient: '1',
      trim_pct: '0',
      include_own: true,
    });
  });

  it('固定基准价不会带上“计入己方报价”', () => {
    expect(toRequest({ ...ok, includeOwn: true })?.params.benchmark.include_own).toBe(false);
  });

  it('去极值比例只在去极值平均法下校验与提交', () => {
    const t = { ...ok, method: 'trimmed_average' as const, trimPct: '10' };
    expect(toRequest(t)?.params.benchmark.trim_pct).toBe('10');
    expect(validateDraft({ ...t, trimPct: '-1' }).trimPct).toBeTruthy();
    expect(validateDraft({ ...ok, trimPct: 'abc' }).trimPct).toBeUndefined();
  });

  it('最高限价与异常低价线选填，填了就必须合法', () => {
    expect(validateDraft({ ...ok, maxLimit: '', abnormalLowPct: '' })).toEqual({});
    expect(validateDraft({ ...ok, maxLimit: '0' }).maxLimit).toBeTruthy();
    expect(validateDraft({ ...ok, abnormalLowPct: '-5' }).abnormalLowPct).toBeTruthy();
    expect(toRequest({ ...ok, maxLimit: '1050', abnormalLowPct: '15' })?.params).toMatchObject({
      max_limit: '1050',
      abnormal_low_pct: '15',
    });
  });

  it('报价列表：指出第几个不合法；数量上限 200／20', () => {
    const e = validateDraft({ ...ok, candidates: '980\nabc' });
    expect(e.candidates).toContain('第 2 个“abc”');
    const many = Array.from({ length: 21 }, (_, i) => String(900 + i)).join('\n');
    expect(validateDraft({ ...ok, candidates: many }).candidates).toContain('最多 20 个');
    const comp = Array.from({ length: 201 }, (_, i) => String(900 + i)).join('\n');
    expect(validateDraft({ ...ok, competitors: comp }).competitors).toContain('最多 200 个');
    expect(validateDraft({ ...ok, candidates: '0' }).candidates).toBeTruthy();
  });

  it('备注最多 500 字', () => {
    expect(validateDraft({ ...ok, note: 'a'.repeat(501) }).note).toBeTruthy();
    expect(validateDraft({ ...ok, note: 'a'.repeat(500) }).note).toBeUndefined();
  });

  it('有错误时不生成请求体', () => {
    expect(toRequest({ ...ok, fullScore: '' })).toBeNull();
  });
});

describe('报价粘贴解析', () => {
  it('换行、空白、分号、顿号、中文逗号和英文逗号都是分隔符', () => {
    expect(splitPrices('100\n200  300;400；500、600，70,80')).toEqual([
      '100',
      '200',
      '300',
      '400',
      '500',
      '600',
      '70',
      '80',
    ]);
  });

  it('千分位写法（1,200,000）整体当作一个数并去掉逗号', () => {
    expect(splitPrices('1,200,000\n950,500.5')).toEqual(['1200000', '950500.5']);
  });

  it('空文本没有报价', () => {
    expect(splitPrices('  \n ')).toEqual([]);
  });
});

describe('方案 ⇄ 草稿', () => {
  it('已保存的方案可以还原成草稿并得到同样的请求体', () => {
    const p = pricePlan();
    const draft = draftFromPlan(p);
    expect(toRequest(draft)).toEqual({
      params: { ...p.params, abnormal_low_pct: null },
      competitor_prices: p.competitor_prices,
      candidate_prices: p.candidate_prices,
      note: p.note,
    });
  });
});

describe('数值长度', () => {
  it('超过 24 个字符的报价按无效处理（与后端一致）', async () => {
    const { validateDraft, EMPTY_DRAFT } = await import('./validate');
    const d = {
      ...EMPTY_DRAFT,
      fullScore: '30',
      aboveDeduct: '1',
      belowDeduct: '0',
      fixedValue: '100',
    };
    expect(validateDraft({ ...d, candidates: '9'.repeat(24) }).candidates).toBeUndefined();
    expect(validateDraft({ ...d, candidates: '9'.repeat(25) }).candidates).toMatch(
      /不是有效的正数/,
    );
  });
});

describe('从招标文件与常见办法填入', () => {
  it('新方案默认平均值法', () => {
    expect(EMPTY_DRAFT.method).toBe('average');
  });

  it('按招标文件填入：只覆盖原文写明的项', () => {
    const d = draftFromTerm(
      { ...EMPTY_DRAFT, maxLimit: '12000', candidates: '980' },
      {
        full_score: '30',
        above_deduct_per_pct: '1',
        below_deduct_per_pct: null,
        method: 'trimmed_average',
        coefficient: '0.95',
        trim_pct: '10',
        max_limit: null,
        abnormal_low_pct: null,
        quote: '原文',
        evidence: [],
      },
    );
    expect(d).toMatchObject({
      fullScore: '30',
      aboveDeduct: '1',
      belowDeduct: '',
      method: 'trimmed_average',
      coefficient: '0.95',
      trimPct: '10',
      maxLimit: '12000',
      candidates: '980',
    });
  });

  it('常见办法只设定取法与扣分，不动满分与报价', () => {
    for (const t of PRICE_TEMPLATES) {
      expect(Object.keys(t.apply)).not.toContain('fullScore');
      expect(Object.keys(t.apply)).not.toContain('candidates');
    }
  });
});
