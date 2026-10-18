import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { evidence, ruleSet } from '../../test/fixtures';
import {
  ME,
  apiError,
  overview,
  project,
  renderApp,
  renderAppWithClient,
} from '../../test/helpers';
import { server } from '../../test/server';
import { rulesKey } from './queries';

function backend() {
  const set = ruleSet({
    status: 'conflict',
    terms: {
      technical_full_score: null,
      price_rule: null,
      conflicts: [
        {
          term: 'technical_full_score',
          alternatives: [
            {
              option_id: 'trm_tender',
              values: { value: '60' },
              quote: '技术标满分60分',
              evidence: [evidence()],
            },
            {
              option_id: 'trm_supplement',
              values: { value: '80' },
              quote: '技术标满分80分',
              evidence: [
                evidence({
                  evidence_id: 'evd-2',
                  file_role: 'supplement',
                  file_name: '补遗二.pdf',
                }),
              ],
            },
          ],
        },
      ],
    },
  });
  server.use(
    http.get('/api/v1/me', () => HttpResponse.json(ME)),
    http.get('/api/v1/projects', () => HttpResponse.json([overview()])),
    http.get('/api/v1/projects/prj-1', () => HttpResponse.json(project())),
    http.get('/api/v1/projects/prj-1/rules', () => HttpResponse.json(set)),
  );
  return set;
}

describe('投标条件歧义核实', () => {
  it('并列展示原文及来源，填写依据后才提交所见版本与候选', async () => {
    const set = backend();
    let submitted: unknown;
    server.use(
      http.post('/api/v1/projects/prj-1/rules/terms:resolve', async ({ request }) => {
        submitted = await request.json();
        expect(request.headers.get('Idempotency-Key')).toBeTruthy();
        return HttpResponse.json({ ...set, revision: 4, terms: { ...set.terms, conflicts: [] } });
      }),
    );
    const user = userEvent.setup();
    renderApp('/projects/prj-1/basis');
    expect(await screen.findByText('技术标满分存在不同要求，请核实采用哪一项')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '补遗二.pdf · 第 3 页' })).toHaveAttribute(
      'href',
      '/projects/prj-1/evidence/evd-2',
    );
    await user.click(screen.getAllByRole('button', { name: '采用此项' })[1]!);
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: '确认采用此项' }));
    expect(submitted).toBeUndefined();
    expect(within(dialog).getByText(/请说明该项为何适用于当前投标/)).toBeInTheDocument();
    await user.type(
      within(dialog).getByRole('textbox', { name: '采用依据' }),
      '已核对补遗替代说明',
    );
    await user.click(within(dialog).getByRole('button', { name: '确认采用此项' }));
    await waitFor(() => {
      expect(submitted).toEqual({
        object_version: '3',
        term: 'technical_full_score',
        option_id: 'trm_supplement',
        reason: '已核对补遗替代说明',
      });
    });
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });

  it('过期版本拒绝时保留待核实内容并提示刷新', async () => {
    const set = backend();
    let submittedVersion: string | undefined;
    server.use(
      http.post('/api/v1/projects/prj-1/rules/terms:resolve', async ({ request }) => {
        submittedVersion = ((await request.json()) as { object_version: string }).object_version;
        return HttpResponse.json(apiError('stale_version', '规则包已有更新'), { status: 412 });
      }),
    );
    const user = userEvent.setup();
    const { qc } = renderAppWithClient('/projects/prj-1/basis');
    await screen.findByText('技术标满分存在不同要求，请核实采用哪一项');
    await user.click(screen.getAllByRole('button', { name: '采用此项' })[0]!);
    act(() => {
      qc.setQueryData(rulesKey('prj-1'), { ...set, revision: 4 });
    });
    await user.type(screen.getByRole('textbox', { name: '采用依据' }), '核实原文');
    await user.click(screen.getByRole('button', { name: '确认采用此项' }));
    expect(await screen.findByText('没有保存，请刷新后核实当前规则版本')).toBeInTheDocument();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(submittedVersion).toBe('3');
  });
});
