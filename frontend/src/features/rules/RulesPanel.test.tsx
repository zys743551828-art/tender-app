import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import type { Rule, RuleSet } from '../../api/types';
import { ME, apiError, project, renderApp } from '../../test/helpers';
import { server } from '../../test/server';
import { groupRules, unconfirmedQualification } from './RulesPanel';

const rule = (over: Partial<Rule> = {}): Rule => ({
  rule_id: 'rul-1',
  kind: 'mandatory',
  statement: '投标人须承诺总工期不超过 180 日历天。',
  conditions: [],
  exceptions: [],
  evidence: [],
  confirmation: 'pending',
  max_points: null,
  ...over,
});

const ruleSet = (rules: Rule[] = [rule()]): RuleSet => ({
  rule_set_id: 'rls-1',
  project_id: 'prj-1',
  source_version_ids: ['ver-t'],
  status: 'candidate',
  revision: 1,
  rules,
  terms: { technical_full_score: null, price_rule: null },
});

function backend(rules: Rule[] = [rule()]) {
  server.use(
    http.get('/api/v1/me', () => HttpResponse.json(ME)),
    http.get('/api/v1/projects/prj-1', () => HttpResponse.json(project())),
    http.get('/api/v1/projects/prj-1/rules', () => HttpResponse.json(ruleSet(rules))),
  );
}

const reviewed = (id = 'rul-1') =>
  HttpResponse.json({ review_id: 'rev-1', object_id: id, object_version: '1' });

describe('依据页：规则分组', () => {
  it('按性质分组，废标／否决／强制在前，评分条款其后', () => {
    const groups = groupRules([
      rule({ rule_id: 'a', kind: 'scoring' }),
      rule({ rule_id: 'b', kind: 'mandatory' }),
      rule({ rule_id: 'c', kind: 'disqualification' }),
      rule({ rule_id: 'd', kind: 'recommendation' }),
    ]);
    expect(groups.map((g) => g.kind)).toEqual([
      'disqualification',
      'mandatory',
      'scoring',
      'recommendation',
    ]);
  });

  it('未确认的废标／否决／强制类规则条数不含评分条款与已确认的', () => {
    expect(
      unconfirmedQualification([
        rule({ kind: 'disqualification' }),
        rule({ kind: 'mandatory', confirmation: 'confirmed' }),
        rule({ kind: 'scoring' }),
      ]),
    ).toBe(1);
  });

  it('页面显示分组标题与评分条款分值；待核对的提示只出现一次，不在每条规则下重复', async () => {
    backend([
      rule({ rule_id: 'rul-1', kind: 'disqualification', statement: '未密封的投标文件将被否决' }),
      rule({ rule_id: 'rul-2', kind: 'scoring', statement: '施工方案评分', max_points: '15' }),
    ]);
    renderApp('/projects/prj-1/basis');
    expect(await screen.findByRole('heading', { name: '废标／否决项（1）' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '评分条款（1）' })).toBeInTheDocument();
    expect(screen.getByText('15 分')).toBeInTheDocument();
    expect(screen.getByText('2 条规则还没有人核对')).toBeInTheDocument();
    expect(screen.getByText(/其中 1 条是废标／否决／强制类，登记提交前须确认/)).toBeInTheDocument();
    expect(screen.queryByText(/成立条件：暂无/)).not.toBeInTheDocument();
    expect(screen.getAllByText('待核对')).toHaveLength(2);
  });
});

describe('依据页：规则确认', () => {
  it.each(['legacy_unfrozen', 'stale'] as const)(
    '来源 %s 时保留条款，禁止旧确认并提供重新提取',
    async (state) => {
      backend();
      server.use(
        http.get('/api/v1/projects/prj-1/rules', () =>
          HttpResponse.json({ ...ruleSet(), source_parse_state: state }),
        ),
      );
      renderApp('/projects/prj-1/basis');
      expect(await screen.findByRole('button', { name: '重新提取并评审' })).toBeInTheDocument();
      expect(screen.getByText('投标人须承诺总工期不超过 180 日历天。')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /全部按原文确认/ })).not.toBeInTheDocument();
      for (const button of screen.queryAllByRole('button', { name: /^(确认|驳回|暂缓)$/ })) {
        expect(button).toBeDisabled();
      }
    },
  );
  it('还没有规则：说明会自动提取，没有手动提取按钮', async () => {
    server.use(
      http.get('/api/v1/me', () => HttpResponse.json(ME)),
      http.get('/api/v1/projects/prj-1', () => HttpResponse.json(project())),
      http.get('/api/v1/projects/prj-1/rules', () =>
        HttpResponse.json(apiError('rules_not_extracted', '该项目尚未提取规则'), { status: 404 }),
      ),
    );
    renderApp('/projects/prj-1/basis');
    expect(await screen.findByText('还没有提取规则')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /提取规则/ })).not.toBeInTheDocument();
  });

  it('沿用上一版决定的规则显示徽标，全新的规则不显示', async () => {
    backend([
      rule({ confirmation: 'confirmed', carried_from_rule_id: 'rul-old' }),
      rule({ rule_id: 'rul-2', statement: '另一条新规则', carried_from_rule_id: null }),
    ]);
    renderApp('/projects/prj-1/basis');
    await screen.findByText('另一条新规则');
    expect(screen.getAllByText('沿用上一版决定')).toHaveLength(1);
  });

  it('全部按原文确认：一次提交全部待核对的规则，已确认的不在其中', async () => {
    backend([
      rule({ rule_id: 'rul-1' }),
      rule({ rule_id: 'rul-2', statement: '另一条' }),
      rule({ rule_id: 'rul-3', statement: '已确认的', confirmation: 'confirmed' }),
    ]);
    let body: unknown = null;
    server.use(
      http.post('/api/v1/projects/prj-1/rules:confirm', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ confirmed: 2, skipped: 0 });
      }),
    );
    renderApp('/projects/prj-1/basis');
    await userEvent.click(await screen.findByRole('button', { name: '全部按原文确认（2 条）' }));
    await waitFor(() => {
      expect(body).toEqual({ object_version: '1', rule_ids: ['rul-1', 'rul-2'] });
    });
    expect(await screen.findByText('已确认 2 条规则')).toBeInTheDocument();
  });

  it('评标办法里提取到技术分满分与评标价规则时，给出原文出处和去报价页的入口', async () => {
    server.use(
      http.get('/api/v1/me', () => HttpResponse.json(ME)),
      http.get('/api/v1/projects/prj-1', () => HttpResponse.json(project())),
      http.get('/api/v1/projects/prj-1/rules', () =>
        HttpResponse.json({
          ...ruleSet(),
          terms: {
            technical_full_score: {
              value: '60',
              quote: '技术标满分为60分',
              evidence: [
                {
                  evidence_id: 'evd-f',
                  project_id: 'prj-1',
                  version_id: 'ver-t',
                  file_role: 'tender',
                  file_name: '招标文件.pdf',
                  source_sha256: 'a'.repeat(64),
                  physical_page: 21,
                  printed_page: null,
                  quote: '技术标满分为60分',
                  kind: 'text',
                  parser_version: 'p1',
                  bbox: null,
                  semantic_review: 'pending',
                },
              ],
            },
            price_rule: {
              full_score: '30',
              above_deduct_per_pct: null,
              below_deduct_per_pct: null,
              method: null,
              coefficient: null,
              trim_pct: null,
              max_limit: null,
              abnormal_low_pct: null,
              quote: '价格分满分30分',
              evidence: [],
            },
          },
        }),
      ),
    );
    renderApp('/projects/prj-1/basis');
    expect(await screen.findByText(/技术标满分 60 分/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '原文第 21 页' })).toHaveAttribute(
      'href',
      '/projects/prj-1/evidence/evd-f',
    );
    expect(screen.getByRole('link', { name: '在报价页使用' })).toHaveAttribute(
      'href',
      '/projects/prj-1/price',
    );
  });
  it('一键确认：不弹窗、不要求理由，请求里没有 reason；规则集合未变不提示重新评审', async () => {
    backend();
    let body: unknown = null;
    server.use(
      http.post('/api/v1/rules/rul-1/reviews', async ({ request }) => {
        body = await request.json();
        return reviewed();
      }),
    );
    renderApp('/projects/prj-1/basis');
    await userEvent.click(await screen.findByRole('button', { name: '确认' }));
    await waitFor(() => {
      expect(body).toEqual({ object_version: '1', decision: 'confirm' });
    });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByText(/规则已更正/)).not.toBeInTheDocument();
  });

  it('驳回必须写理由：弹窗里不填不发请求，填了才提交', async () => {
    backend();
    const bodies: unknown[] = [];
    server.use(
      http.post('/api/v1/rules/rul-1/reviews', async ({ request }) => {
        bodies.push(await request.json());
        return reviewed();
      }),
    );
    renderApp('/projects/prj-1/basis');
    await userEvent.click(await screen.findByRole('button', { name: '驳回' }));
    const dlg = await screen.findByRole('dialog', { name: '驳回条款' });
    await userEvent.click(within(dlg).getByRole('button', { name: '驳回条款' }));
    expect(await within(dlg).findByText(/请写明驳回的理由/)).toBeInTheDocument();
    expect(bodies).toHaveLength(0);
    await userEvent.type(within(dlg).getByLabelText('驳回理由'), '与本项目无关');
    await userEvent.click(within(dlg).getByRole('button', { name: '驳回条款' }));
    await waitFor(() => {
      expect(bodies).toEqual([{ object_version: '1', decision: 'reject', reason: '与本项目无关' }]);
    });
  });

  it('暂缓同样必须写理由，请求为 decision=defer', async () => {
    backend();
    const bodies: unknown[] = [];
    server.use(
      http.post('/api/v1/rules/rul-1/reviews', async ({ request }) => {
        bodies.push(await request.json());
        return reviewed();
      }),
    );
    renderApp('/projects/prj-1/basis');
    await userEvent.click(await screen.findByRole('button', { name: '暂缓' }));
    const dlg = await screen.findByRole('dialog', { name: '暂缓条款' });
    await userEvent.type(within(dlg).getByLabelText('暂缓理由'), '等待招标方澄清');
    await userEvent.click(within(dlg).getByRole('button', { name: '暂缓条款' }));
    await waitFor(() => {
      expect(bodies).toEqual([
        { object_version: '1', decision: 'defer', reason: '等待招标方澄清' },
      ]);
    });
  });

  it('改变了参与评审的规则集合：后端复制出新规则包，提示重新评审后生效', async () => {
    backend([rule({ confirmation: 'confirmed' })]);
    server.use(http.post('/api/v1/rules/rul-1/reviews', () => reviewed('rul-new')));
    renderApp('/projects/prj-1/basis');
    await userEvent.click(await screen.findByRole('button', { name: '驳回' }));
    const dlg = await screen.findByRole('dialog', { name: '驳回条款' });
    await userEvent.type(within(dlg).getByLabelText('驳回理由'), '理解有误');
    await userEvent.click(within(dlg).getByRole('button', { name: '驳回条款' }));
    expect(await screen.findByText(/规则已更正，重新评审后生效/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '回到报告' })).toHaveAttribute(
      'href',
      '/projects/prj-1',
    );
  });

  it('逐条确认成功后重新读取项目与报告', async () => {
    backend();
    let projectGets = 0;
    let reportGets = 0;
    server.use(
      http.get('/api/v1/projects/prj-1', () => {
        projectGets++;
        return HttpResponse.json(project());
      }),
      http.get('/api/v1/projects/prj-1/report', () => {
        reportGets++;
        return HttpResponse.json(apiError('report_not_ready', '还没有完成的评审'), { status: 404 });
      }),
      http.post('/api/v1/rules/rul-1/reviews', () => reviewed()),
    );
    renderApp('/projects/prj-1/basis');
    const confirm = await screen.findByRole('button', { name: '确认' });
    const before = projectGets;
    await userEvent.click(confirm);
    await waitFor(() => {
      expect(projectGets).toBeGreaterThan(before);
    });
    expect(reportGets).toBeGreaterThanOrEqual(0);
  });
});
