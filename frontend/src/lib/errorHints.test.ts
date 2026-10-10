import { describe, expect, it } from 'vitest';
import { ApiError } from '../api/errors';
import { submissionErrorHint, submissionGateItems } from './errorHints';

const conflict = (code: string) => new ApiError({ status: 409, code, message: '后端消息' });

describe('提交闸门的错误提示', () => {
  it('规则未确认：指向依据页，并列出未满足的条件', () => {
    const e = conflict('qualification_rules_unconfirmed');
    expect(submissionErrorHint(e)).toContain('“依据”页');
    expect(submissionGateItems(e)).toEqual(['废标／否决／强制类规则尚未全部确认']);
  });
  it('关键问题未处理（含废标／响应类）：指向问题页', () => {
    const e = conflict('critical_findings_open');
    expect(submissionErrorHint(e)).toContain('“问题”页');
    expect(submissionGateItems(e)).toHaveLength(1);
  });
  it('评审不是最新：指向报告重新评审', () => {
    expect(submissionErrorHint(conflict('snapshot_not_latest'))).toContain('重新评审');
    expect(submissionErrorHint(conflict('snapshot_stale'))).toContain('重新评审');
  });
  it('不认识的错误码、非 409 错误不加提示', () => {
    expect(submissionErrorHint(conflict('something_else'))).toBeNull();
    expect(
      submissionErrorHint(
        new ApiError({ status: 500, code: 'critical_findings_open', message: 'x' }),
      ),
    ).toBeNull();
    expect(submissionErrorHint(new Error('x'))).toBeNull();
    expect(submissionGateItems(null)).toEqual([]);
  });
});
