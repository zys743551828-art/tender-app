import { describe, expect, it } from 'vitest';
import { compareDecimal } from '../../lib/format';
import { toOutcomeRequest, validateOutcome, type OutcomeDraft } from './validate';

const base: OutcomeDraft = {
  submissionId: 'sub-1',
  sourceKind: 'user_reported',
  target: 'no_score',
  value: '',
  maximum: '',
  aggregation: '',
  stageResult: 'pending',
  publishedAt: '',
  sourceArtifactId: '',
  sourcePage: '',
  sourceDescription: '招标网站公示',
  supersedes: '',
};
const scored: OutcomeDraft = { ...base, target: 'technical_total' };

describe('结果录入校验', () => {
  it('分值未公布时选“无分值”：合法，请求里是 null 而不是 0', () => {
    expect(validateOutcome(base)).toEqual({});
    const r = toOutcomeRequest(base, () => null);
    expect(r.value).toBeNull();
    expect(r.maximum).toBeNull();
  });
  it('有分值的类型必须同时填分值与满分；留空不当作“未知”，并提示改选“无分值”', () => {
    const e = validateOutcome(scored);
    expect(e.value).toBe('请填写分值；未公布请勾选「分值未知」');
    expect(e.maximum).toBe('请填写满分；未公布请勾选「分值未知」');
    expect(validateOutcome({ ...scored, value: '80' }).maximum).toMatch(/请填写满分/);
    expect(validateOutcome({ ...scored, maximum: '100' }).value).toMatch(/请填写分值/);
    expect(validateOutcome({ ...scored, target: 'composite_total' }).value).toBeTruthy();
  });
  it('十进制校验：拒绝 NaN、科学计数、前导零、负数、逗号', () => {
    for (const bad of ['abc', '1e3', '08', '-1', '1,5', '.5', '5.']) {
      expect(validateOutcome({ ...scored, value: bad, maximum: '100' }).value, bad).toBeTruthy();
    }
    expect(validateOutcome({ ...scored, value: '86.50', maximum: '100' })).toEqual({});
  });
  it('分值不得大于满分', () => {
    expect(validateOutcome({ ...scored, value: '101', maximum: '100' }).value).toMatch(
      /不能大于满分/,
    );
    expect(validateOutcome({ ...scored, value: '100', maximum: '100' })).toEqual({});
  });
  it('无分值类型不允许带分值，并且请求里清空', () => {
    expect(
      validateOutcome({ ...base, target: 'no_score', value: '5', maximum: '' }).value,
    ).toBeTruthy();
    const r = toOutcomeRequest(
      { ...base, target: 'no_score', stageResult: 'rejected' },
      () => null,
    );
    expect([r.value, r.maximum]).toEqual([null, null]);
  });
  it('最终中标需要来源资料与页码；来源页码必须配来源资料', () => {
    expect(validateOutcome({ ...base, stageResult: 'awarded' }).stageResult).toMatch(/官方来源/);
    expect(
      validateOutcome({
        ...base,
        stageResult: 'awarded',
        sourceArtifactId: 'art-1',
        sourcePage: '3',
      }),
    ).toEqual({});
    expect(validateOutcome({ ...base, sourcePage: '3' }).sourceArtifactId).toBeTruthy();
  });
  it('必须关联提交并说明来源', () => {
    const e = validateOutcome({ ...base, submissionId: ' ', sourceDescription: '' });
    expect(Object.keys(e).sort()).toEqual(['sourceDescription', 'submissionId']);
  });
});

describe('compareDecimal', () => {
  it('按数值比较十进制字符串，不经过浮点', () => {
    expect(compareDecimal('86.5', '100')).toBe(-1);
    expect(compareDecimal('100', '100.0')).toBe(0);
    expect(compareDecimal('100.01', '100')).toBe(1);
    expect(compareDecimal('9', '10')).toBe(-1);
    expect(compareDecimal('0.1', '0.10000000000000000001')).toBe(-1);
  });
});
