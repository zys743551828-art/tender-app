import { describe, expect, it } from 'vitest';
import { parseEvidenceIds, toFactRequest, validateFact, type FactDraft } from './validate';

const draft: FactDraft = {
  name: '总工期',
  subject: '本公司',
  scope: '一标段',
  value: '180',
  unit: '日历天',
  statement: '承诺总工期 180 日历天',
  evidenceIds: 'evd-1, evd-2、evd-1\nevd-3',
};

describe('事实录入校验', () => {
  it('证据 ID 去重并支持多种分隔符', () => {
    expect(parseEvidenceIds(draft.evidenceIds)).toEqual(['evd-1', 'evd-2', 'evd-3']);
    expect(parseEvidenceIds('  ')).toEqual([]);
  });
  it('合法草稿无错误；数值与单位可为空并转成 null', () => {
    expect(validateFact(draft)).toEqual({});
    expect(toFactRequest({ ...draft, value: ' ', unit: '' })).toMatchObject({
      value_decimal: null,
      unit: null,
    });
    expect(toFactRequest(draft)).toMatchObject({
      value_decimal: '180',
      evidence_ids: ['evd-1', 'evd-2', 'evd-3'],
    });
  });
  it('必填项、数值格式与证据数量', () => {
    const e = validateFact({ ...draft, name: ' ', value: '1e3', evidenceIds: '' });
    expect(Object.keys(e).sort()).toEqual(['evidenceIds', 'name', 'value']);
  });
});
