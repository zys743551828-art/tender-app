import { describe, expect, it } from 'vitest';
import { actionLabel, actionPath, coverageText } from './nextAction';

describe('下一步', () => {
  it('按钮文字说明要做什么', () => {
    expect(actionLabel({ key: 'handle_disqualification' })).toBe('处理否决／强制风险');
    expect(actionLabel({ key: 'confirm_rules' })).toBe('确认规则');
  });

  it('落点具体到分类或响应矩阵', () => {
    expect(actionPath('/p', { key: 'handle_disqualification', target: 'findings' })).toBe(
      '/p/findings?priority=qualification',
    );
    expect(actionPath('/p', { key: 'review_unclear', target: 'report' })).toBe('/p#matrix');
    expect(actionPath('/p', { key: 'confirm_rules', target: 'rules' })).toBe('/p/basis');
    expect(actionPath('/p', { key: 'record_outcome', target: 'outcomes' })).toBe(
      '/p/submit?tab=outcomes',
    );
    expect(actionPath('/p', { key: 'reanalyze', target: 'report' })).toBe('/p');
  });

  it('覆盖程度：只在满分已知且没有全覆盖时提示', () => {
    expect(coverageText('8', '60')).toBe('只覆盖 8 / 60 分');
    expect(coverageText('60', '60')).toBeNull();
    expect(coverageText('8', null)).toBeNull();
    expect(coverageText(null, '60')).toBeNull();
  });
});
