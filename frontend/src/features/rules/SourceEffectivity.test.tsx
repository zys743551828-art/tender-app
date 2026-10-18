import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import type { EffectivityPreviewRequest, EffectivityRequest } from '../../api/types';
import { evidence, fileVersion, ruleSet } from '../../test/fixtures';
import { ME, overview, project, renderApp } from '../../test/helpers';
import { server } from '../../test/server';

const ORIGINAL = '总工期不得超过180日历天';
const QUALITY = '质量必须合格';
const QUOTE = '仅将总工期修改为120日历天，其余要求不变';

function backend() {
  const base = ruleSet().rules[0]!;
  const old = evidence({ evidence_id: 'evd_old', version_id: 'ver_t', quote: ORIGINAL });
  const next = evidence({
    evidence_id: 'evd_new',
    version_id: 'ver_s',
    file_role: 'supplement',
    file_name: '补遗.pdf',
    quote: QUOTE,
  });
  let current = ruleSet({
    source_version_ids: ['ver_t', 'ver_s'],
    rules: [
      {
        ...base,
        rule_id: 'rul_old',
        statement: ORIGINAL,
        confirmation: 'pending',
        evidence: [old],
        source_status: 'active',
      },
      {
        ...base,
        rule_id: 'rul_quality',
        statement: QUALITY,
        confirmation: 'pending',
        evidence: [old],
        source_status: 'active',
      },
      {
        ...base,
        rule_id: 'rul_new',
        statement: QUOTE,
        confirmation: 'pending',
        evidence: [next],
        source_status: 'active',
      },
    ],
  });
  const submitted: EffectivityRequest[] = [];
  server.use(
    http.get('/api/v1/me', () => HttpResponse.json(ME)),
    http.get('/api/v1/projects', () => HttpResponse.json([overview()])),
    http.get('/api/v1/projects/prj-1', () => HttpResponse.json(project())),
    http.get('/api/v1/projects/prj-1/rules', () => HttpResponse.json(current)),
    http.get('/api/v1/projects/prj-1/files', () =>
      HttpResponse.json([
        fileVersion('ver_t', 'tender', '招标.pdf'),
        fileVersion('ver_s', 'supplement', '补遗.pdf'),
      ]),
    ),
    http.get('/api/v1/projects/prj-1/rules/source-evidence/ver_s', () => HttpResponse.json([next])),
    http.post(/\/api\/v1\/projects\/prj-1\/rules\/effectivity:preview$/, async ({ request }) => {
      const body = (await request.json()) as EffectivityPreviewRequest;
      return HttpResponse.json({
        rule_set_id: current.rule_set_id,
        revision: current.revision,
        affected_rule_ids: body.rule_ids,
        mixed_source_rule_ids: [],
        related_sections: [
          {
            title: '施工进度计划',
            evidence: [
              evidence({ evidence_id: 'evd_body', version_id: 'ver-b', physical_page: 8 }),
            ],
          },
        ],
        gaps: ['章节为关键词相关候选，需人工核实'],
      });
    }),
    http.post(/\/api\/v1\/projects\/prj-1\/rules\/effectivity:decide$/, async ({ request }) => {
      expect(request.headers.get('Idempotency-Key')).toBeTruthy();
      const body = (await request.json()) as EffectivityRequest;
      submitted.push(body);
      current = {
        ...current,
        revision: 4,
        rules: current.rules.map((rule) =>
          rule.rule_id === 'rul_old' ? { ...rule, source_status: 'superseded' } : rule,
        ),
      };
      return HttpResponse.json(current);
    }),
  );
  return submitted;
}

describe('有据补遗影响', () => {
  it('先查看范围与相关章节，核对原文并填写理由后提交局部替代', async () => {
    const submitted = backend();
    const user = userEvent.setup();
    renderApp('/projects/prj-1/basis');
    await user.click(await screen.findByRole('button', { name: '核实补遗影响' }));
    const dialog = screen.getByRole('dialog');
    await user.click(await within(dialog).findByRole('checkbox', { name: ORIGINAL }));
    const confirm = within(dialog).getByRole('button', { name: '确认补遗影响' });
    expect(confirm).toBeDisabled();
    await user.click(within(dialog).getByRole('button', { name: '查看影响范围' }));
    expect(await within(dialog).findByText('涉及 1 条原要求')).toBeInTheDocument();
    expect(within(dialog).getByText('施工进度计划')).toBeInTheDocument();
    expect(within(dialog).getByRole('link', { name: '第 8 页' })).toHaveAttribute(
      'href',
      '/projects/prj-1/evidence/evd_body',
    );
    await user.click(within(dialog).getByRole('radio', { name: new RegExp(QUOTE) }));
    await user.type(
      within(dialog).getByRole('textbox', { name: '核实理由' }),
      '仅替代工期，质量要求保留',
    );
    expect(confirm).toBeEnabled();
    await user.click(confirm);
    await waitFor(() => {
      expect(submitted).toHaveLength(1);
    });
    expect(submitted[0]).toEqual({
      object_version: '3',
      old_version_id: 'ver_t',
      new_version_id: 'ver_s',
      action: 'partial_replace',
      rule_ids: ['rul_old'],
      scope_basis: [{ evidence_id: 'evd_new', quote: QUOTE }],
      reason: '仅替代工期，质量要求保留',
    });
    expect(await screen.findByText('已被补遗替代，保留查证')).toBeInTheDocument();
    const oldRow = screen.getByText(ORIGINAL).closest('li')!;
    expect(within(oldRow).queryByRole('button', { name: '确认' })).not.toBeInTheDocument();
    expect(screen.getByText('2 条规则还没有人核对')).toBeInTheDocument();
  });

  it('预览后更换范围必须重新查看，不能提交过期预览', async () => {
    backend();
    const user = userEvent.setup();
    renderApp('/projects/prj-1/basis');
    await user.click(await screen.findByRole('button', { name: '核实补遗影响' }));
    const dialog = screen.getByRole('dialog');
    await user.click(await within(dialog).findByRole('checkbox', { name: ORIGINAL }));
    await user.click(within(dialog).getByRole('button', { name: '查看影响范围' }));
    await within(dialog).findByText('涉及 1 条原要求');
    await user.click(within(dialog).getByRole('radio', { name: new RegExp(QUOTE) }));
    await user.type(within(dialog).getByRole('textbox', { name: '核实理由' }), '已核对范围');
    const confirm = within(dialog).getByRole('button', { name: '确认补遗影响' });
    expect(confirm).toBeEnabled();
    await user.click(within(dialog).getByRole('checkbox', { name: QUALITY }));
    expect(confirm).toBeDisabled();
    expect(within(dialog).queryByText('涉及 1 条原要求')).not.toBeInTheDocument();
  });
});
