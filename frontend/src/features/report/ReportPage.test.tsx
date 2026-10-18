import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import type { Report } from '../../api/types';
import { compliance, pipeline, prediction, report, ruleSet, verdictRow } from '../../test/fixtures';
import { ME, apiError, project, renderApp, renderAppWithClient } from '../../test/helpers';
import { server } from '../../test/server';
import { needsAttention, needsReview, sortVerdictRows } from './ComplianceTable';

function backend(rep: Report | null) {
  server.use(
    http.get('/api/v1/me', () => HttpResponse.json(ME)),
    http.get('/api/v1/projects/prj-1', () => HttpResponse.json(project())),
    http.get('/api/v1/projects/prj-1/pipeline', () =>
      HttpResponse.json(rep ? rep.pipeline : pipeline()),
    ),
    http.get('/api/v1/projects/prj-1/report', () =>
      rep
        ? HttpResponse.json(rep)
        : HttpResponse.json(apiError('report_not_ready', '还没有完成的评审'), { status: 404 }),
    ),
  );
}

describe('报告页：没有完成的评审', () => {
  it('历史报告明确提示未冻结解析身份，仍可读取原结论', async () => {
    const original = report();
    backend({ ...original, basis: { ...original.basis, parse_identity: 'legacy_unfrozen' } });
    renderApp('/projects/prj-1');
    expect(await screen.findByRole('note')).toHaveTextContent('该轮未冻结解析与证据身份');
    expect(screen.getByRole('link', { name: '下载评审报告（Word）' })).toBeInTheDocument();
  });
  it('生效关系待核实时引导核实依据，不显示无效的重试按钮', async () => {
    backend(null);
    server.use(
      http.get('/api/v1/projects/prj-1/pipeline', () =>
        HttpResponse.json(pipeline({ stage: 'failed', input_verification_required: true })),
      ),
    );
    renderApp('/projects/prj-1');
    expect(await screen.findByText('先核实补遗或投标条件，再继续评审')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '核实补遗依据' })).toHaveAttribute(
      'href',
      '/projects/prj-1/basis',
    );
    expect(screen.queryByRole('button', { name: '重新评审' })).not.toBeInTheDocument();
  });
  it('资料不齐：说明还缺什么，给出上传入口，没有“下一步”按钮', async () => {
    backend(null);
    server.use(
      http.get('/api/v1/projects/prj-1/pipeline', () =>
        HttpResponse.json(
          pipeline({ stage: 'waiting_materials', missing: ['tender', 'body'], snapshot_id: null }),
        ),
      ),
    );
    renderApp('/projects/prj-1');
    expect(await screen.findByText('还缺招标文件、施组正文，暂时不能评审')).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /上传资料/ })[0]).toHaveAttribute(
      'href',
      '/projects/prj-1/materials',
    );
    expect(screen.queryByRole('button', { name: /下一步/ })).not.toBeInTheDocument();
  });

  it('评审进行中：显示四个环节的状态（文字，不只靠颜色）', async () => {
    backend(null);
    server.use(
      http.get('/api/v1/projects/prj-1/pipeline', () =>
        HttpResponse.json(
          pipeline({
            stage: 'running',
            snapshot_id: null,
            steps: [
              { key: 'materials', state: 'done', task_id: null, message: null },
              { key: 'rules', state: 'running', task_id: 't1', message: null },
              { key: 'review', state: 'waiting', task_id: null, message: null },
              { key: 'prediction', state: 'waiting', task_id: null, message: null },
            ],
          }),
        ),
      ),
    );
    renderApp('/projects/prj-1');
    const steps = within(await screen.findByRole('list', { name: '评审进度' }));
    expect(steps.getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      expect.stringContaining('资料解析已完成'),
      expect.stringContaining('提取规则进行中'),
      expect.stringContaining('逐条核对等待中'),
      expect.stringContaining('评分预测等待中'),
    ]);
    expect(screen.getByText('正在评审')).toBeInTheDocument();
  });

  it('评审中断：显示失败环节与原因，点“重新评审”发起 POST /analysis', async () => {
    backend(null);
    let posted = 0;
    server.use(
      http.get('/api/v1/projects/prj-1/pipeline', () =>
        HttpResponse.json(
          pipeline({
            stage: 'failed',
            snapshot_id: null,
            steps: [
              { key: 'materials', state: 'done', task_id: null, message: null },
              { key: 'rules', state: 'failed', task_id: 't1', message: '模型服务超时' },
              { key: 'review', state: 'waiting', task_id: null, message: null },
              { key: 'prediction', state: 'waiting', task_id: null, message: null },
            ],
          }),
        ),
      ),
      http.post('/api/v1/projects/prj-1/analysis', ({ request }) => {
        posted++;
        expect(request.headers.get('Idempotency-Key')).toBeTruthy();
        return HttpResponse.json(pipeline({ stage: 'running' }), { status: 202 });
      }),
    );
    renderApp('/projects/prj-1');
    expect(await screen.findByText('评审中断')).toBeInTheDocument();
    expect(screen.getByText(/提取规则失败：模型服务超时/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '重新评审' }));
    await waitFor(() => {
      expect(posted).toBe(1);
    });
  });
});

describe('报告页：评审报告', () => {
  it('关键核对覆盖不完整时，主动作交给重试横幅并调用正式评审接口', async () => {
    backend(
      report({
        next_actions: [
          {
            key: 'retry_analysis',
            title: '关键核对覆盖未完成，重新评审',
            detail: '有要求尚未核对',
            target: 'report',
            count: null,
            priority: 2,
          },
        ],
      }),
    );
    let writes = 0;
    server.use(
      http.post('/api/v1/projects/prj-1/analysis', () => {
        writes += 1;
        return HttpResponse.json(pipeline({ stage: 'running' }));
      }),
    );
    const user = userEvent.setup();
    renderApp('/projects/prj-1');
    expect(await screen.findByText('关键核对覆盖未完成，重新评审')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '重新评审' }));
    await waitFor(() => expect(writes).toBe(1));
  });

  it('折叠数量采用服务端等级，待核实事实计入关键项，普通建议留在其他建议', async () => {
    backend(
      report({
        next_actions: [
          {
            key: 'handle_critical',
            title: '处理其他关键风险',
            detail: '',
            target: 'findings',
            count: 1,
            priority: 3,
          },
          {
            key: 'verify_facts',
            title: '核实事实',
            detail: '',
            target: 'rules',
            count: 2,
            priority: 4,
          },
          {
            key: 'handle_suggestions',
            title: '查看普通建议',
            detail: '',
            target: 'findings',
            count: 3,
            priority: 6,
          },
        ],
      }),
    );
    renderApp('/projects/prj-1');
    const toggle = await screen.findByText('剩余关键问题 2 项／其他建议 3 项');
    await userEvent.click(toggle);
    expect(screen.getByRole('link', { name: '核实事实' })).toHaveAttribute(
      'href',
      '/projects/prj-1/basis?tab=facts',
    );
  });
  it('结论：一句话说清有没有否决风险，下面是强制要求满足数、预计技术分（未校准、覆盖程度）和报价', async () => {
    backend(
      report({
        categories: report().categories.map((c) =>
          c.category === 'response' ? { ...c, open: 0 } : c,
        ),
        qualification: compliance([
          verdictRow({ rule_id: 'a', kind: 'mandatory', verdict: 'satisfied' }),
          verdictRow({ rule_id: 'b', kind: 'mandatory', verdict: 'unclear', evidence: [] }),
        ]),
        prediction: prediction({ maximum: '8', technical_full_score: '60' }),
      }),
    );
    renderApp('/projects/prj-1');
    const verdict = within(await screen.findByRole('region', { name: '结论' }));
    expect(
      verdict.getByText('没有发现明确的否决风险，但有 1 条要求在正文里找不到明确响应'),
    ).toBeInTheDocument();
    expect(verdict.getByText(/有 1 条还没核对，暂按原文判断/)).toBeInTheDocument();
    expect(verdict.getByText('满足 1 / 2')).toBeInTheDocument();
    expect(verdict.getByText('预计技术分（未校准）')).toBeInTheDocument();
    expect(verdict.getByText(/65–80/)).toBeInTheDocument();
    expect(verdict.getByText('只覆盖 8 / 60 分')).toBeInTheDocument();
    expect(verdict.getByRole('link', { name: '还没填报价' })).toHaveAttribute(
      'href',
      '/projects/prj-1/price',
    );
  });
  it('有未处理的否决风险：结论直接说出数量', async () => {
    backend(
      report({
        categories: report().categories.map((c) =>
          c.category === 'disqualification' ? { ...c, total: 2, open: 2 } : c,
        ),
      }),
    );
    renderApp('/projects/prj-1');
    const verdict = await screen.findByRole('region', { name: '结论' });
    expect(verdict).toHaveClass('is-risk');
    expect(
      within(verdict).getByText('有 3 个可能导致否决或不满足强制要求的问题还没处理'),
    ).toBeInTheDocument();
  });
  it('报价最优候选：已保存方案时显示报价与价格分', async () => {
    backend(
      report({
        price: {
          plan_id: 'prp-1',
          exchange_rate: { points_per_pct_above: '1', pct_per_point_above: '1' },
          best: { price: '980', deviation_pct: '-2', score: '29', flags: [] },
          candidates: [],
          created_at: '2026-10-03T03:00:00Z',
        },
      }),
    );
    renderApp('/projects/prj-1');
    const verdict = within(await screen.findByRole('region', { name: '结论' }));
    expect(verdict.getByText('980')).toBeInTheDocument();
    expect(verdict.getByText('价格分 29')).toBeInTheDocument();
  });

  it('下一步保留主要动作，其余关键问题有数量且可展开；评审动作交给横幅', async () => {
    backend(
      report({
        next_actions: [
          { key: 'confirm_rules', title: '确认 2 条规则', detail: 'd1', target: 'rules', count: 2 },
          {
            key: 'record_outcome',
            title: '登记开标结果',
            detail: 'd2',
            target: 'outcomes',
            count: null,
          },
          {
            key: 'review_unclear',
            title: '3 条规则正文没有明确响应',
            detail: 'd3',
            target: 'report',
            count: 3,
          },
          { key: 'reanalyze', title: '重新评审', detail: 'd4', target: 'report', count: null },
        ],
      }),
    );
    renderApp('/projects/prj-1');
    const section = (await screen.findByRole('heading', { name: '下一步' })).closest('section')!;
    expect(within(section.querySelector('ol')!).getAllByRole('link')).toHaveLength(1);
    const remaining = within(section).getByText('剩余关键问题 3 项／其他建议 1 项');
    expect(remaining.closest('details')).not.toHaveAttribute('open');
    await userEvent.click(remaining);
    const items = within(section).getAllByRole('listitem');
    expect(items.map((li) => li.querySelector('strong')?.textContent)).toEqual([
      '确认 2 条规则',
      '登记开标结果',
      '3 条规则正文没有明确响应',
    ]);
    const links = within(section).getAllByRole('link');
    expect(links.map((a) => [a.textContent, a.getAttribute('href')])).toEqual([
      ['确认规则', '/projects/prj-1/basis'],
      ['登记结果', '/projects/prj-1/submit?tab=outcomes'],
      ['逐条核对', '/projects/prj-1#matrix'],
    ]);
    expect(links[0]).toHaveAttribute('data-variant', 'primary');
    expect(links[1]).not.toHaveAttribute('data-variant', 'primary');
  });
  it('逐条响应：只展开需要处理的行，违反与无法判断排前；满足的收起，可以展开', async () => {
    const rows = [
      verdictRow({ rule_id: 'r-ok', statement: '满足的条款', verdict: 'satisfied' }),
      verdictRow({ rule_id: 'r-un', statement: '不明确的条款', verdict: 'unclear', evidence: [] }),
      verdictRow({ rule_id: 'r-bad', statement: '违反的条款', verdict: 'violated' }),
      verdictRow({ rule_id: 'r-fail', statement: '失败的条款', verdict: 'failed', evidence: [] }),
    ];
    backend(report({ qualification: compliance(rows) }));
    renderApp('/projects/prj-1');
    const table = await screen.findByRole('table', { name: '规则逐条判定' });
    const body = within(table).getAllByRole('row').slice(1);
    const names = body.map((r) => within(r).getAllByRole('rowheader')[0]?.textContent ?? '');
    expect(names).toHaveLength(3);
    expect(names[0]).toContain('违反的条款');
    expect(names[1]).toContain('失败的条款');
    expect(names[2]).toContain('不明确的条款');
    const unclearRow = body.find((r) => r.textContent.includes('不明确的条款'))!;
    expect(unclearRow).toHaveClass('row-alert');
    expect(within(unclearRow).getByText('正文没有写到')).toBeInTheDocument();
    expect(screen.queryByText('满足的条款')).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole('button', { name: '显示其余 1 条（已满足或评分条款）' }),
    );
    const okRow = screen.getByText('满足的条款').closest('tr')!;
    expect(okRow).not.toHaveClass('row-alert');
    expect(within(okRow).getByText('总工期 175 日历天')).toBeInTheDocument();
  });

  it('未核对的规则可以在逐条响应里直接按原文确认', async () => {
    const rows = [
      verdictRow({
        rule_id: 'rul-1',
        statement: '未核对的条款',
        verdict: 'unclear',
        evidence: [],
        rule_basis: 'unconfirmed',
      }),
    ];
    backend(report({ qualification: compliance(rows) }));
    let body: unknown = null;
    server.use(
      http.get('/api/v1/projects/prj-1/rules', () =>
        HttpResponse.json(
          ruleSet({
            revision: 5,
            rules: [{ ...ruleSet().rules[0]!, rule_id: 'rul-1', confirmation: 'pending' }],
          }),
        ),
      ),
      http.post('/api/v1/rules/rul-1/reviews', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({
          review_id: 'rev-1',
          project_id: 'prj-1',
          object_id: 'rul-1',
          object_version: '5',
          decision: 'confirm',
          reason: '',
          actor_id: 'mem-1',
          reviewed_at: '2026-10-02T03:20:00Z',
        });
      }),
    );
    renderApp('/projects/prj-1');
    const row = (await screen.findByText('未核对的条款')).closest('tr')!;
    expect(within(row).getByText(/规则未核对/)).toBeInTheDocument();
    await userEvent.click(await within(row).findByRole('button', { name: '按原文确认' }));
    await waitFor(() => {
      expect(body).toEqual({ object_version: '5', decision: 'confirm' });
    });
    expect(await screen.findByText('已确认')).toBeInTheDocument();
  });
  it('核对覆盖不完整时在矩阵上方提示', async () => {
    const c = compliance();
    backend(
      report({
        qualification: {
          ...c,
          coverage: {
            status: 'partial',
            rules_total: 4,
            rules_checked: 3,
            rules_failed: 1,
            candidates_dropped: 0,
          },
        },
      }),
    );
    renderApp('/projects/prj-1');
    expect(await screen.findByText(/这一轮只核对了 3 \/ 4 条规则，结果不完整/)).toBeInTheDocument();
  });

  it('全部问题：一行汇总，每类链接到带 category 的问题页', async () => {
    backend(report());
    renderApp('/projects/prj-1');
    const section = (await screen.findByRole('heading', { name: '全部问题' })).closest('section')!;
    const links = within(section).getAllByRole('link');
    expect(links.map((a) => a.getAttribute('href'))).toEqual([
      '/projects/prj-1/findings?category=disqualification',
      '/projects/prj-1/findings?category=response',
      '/projects/prj-1/findings?category=consistency',
      '/projects/prj-1/findings?category=scope',
      '/projects/prj-1/findings?category=improvement',
    ]);
    expect(links[4]).toHaveTextContent('待处理 · 共 3');
  });
  it('技术分预测：估计与区间、“未校准”与一句原因同时出现，失分点带原文，覆盖不全时写明', async () => {
    backend(report({ prediction: prediction({ maximum: '40', technical_full_score: '60' }) }));
    renderApp('/projects/prj-1');
    const panel = within(
      (await screen.findByRole('heading', { name: '技术分预测' })).closest('section')!,
    );
    expect(panel.getByText('未校准')).toBeInTheDocument();
    expect(panel.getAllByText('72.5').length).toBeGreaterThan(0);
    expect(
      panel.getByRole('img', { name: /得分估计 72.5，区间 65 至 80，评分条款合计 40 分/ }),
    ).toBeInTheDocument();
    expect(
      panel.getByText(/技术标满分 60 分，能识别出分值的评分条款 只覆盖 40 \/ 60 分/),
    ).toBeInTheDocument();
    expect(panel.getByText('施工组织设计的针对性（满分 10 分）')).toBeInTheDocument();
    expect(panel.getByText('估计失 4.5 分')).toBeInTheDocument();
    expect(panel.getByText('交通导改按常规处理')).toBeInTheDocument();
    expect(panel.getByRole('link', { name: '第 3 页' })).toHaveAttribute(
      'href',
      '/projects/prj-1/evidence/evd-7',
    );
    expect(panel.getByText(/还没有官方成绩可以对照/)).toBeInTheDocument();
  });
  it('打分模型已校准：标“已校准”，区间写明把握，给出模型的样本数、误差与适用范围，不写覆盖程度', async () => {
    backend(
      report({
        prediction: prediction({
          validation_status: 'validated_in_scope',
          estimated_value: '51.3',
          low: '48.1',
          high: '54.4',
          maximum: '60',
          technical_full_score: '60',
          reason: '已用 286 组官方成绩校准。',
          scoring_model: {
            model_id: 'm-1',
            pairs: 286,
            mae: '3.4',
            scope: '安徽省 · 市政道路、排水管网',
          },
        }),
      }),
    );
    renderApp('/projects/prj-1');
    const panel = within(
      (await screen.findByRole('heading', { name: '技术分预测' })).closest('section')!,
    );
    expect(panel.getByText('已校准')).toBeInTheDocument();
    expect(panel.queryByText('未校准')).not.toBeInTheDocument();
    expect(
      panel.getByText(/约 80% 把握在 48.1–54.4 分之间 · 技术标满分 60 分/),
    ).toBeInTheDocument();
    expect(
      panel.getByText(
        /用 286 组官方成绩训练与评估，平均绝对误差 3.4 分（满分百分制）；适用：安徽省 · 市政道路、排水管网/,
      ),
    ).toBeInTheDocument();
    expect(panel.queryByText(/只覆盖/)).not.toBeInTheDocument();
    expect(screen.getByText('预计技术分（已校准）')).toBeInTheDocument();
  });
  it('样本不足时不给误差；已校准时给出平均绝对误差与偏差', async () => {
    backend(
      report({
        prediction: prediction({
          calibration: { state: 'insufficient', pairs: 5, needed_pairs: 20, mae: null, bias: null },
        }),
      }),
    );
    const first = renderApp('/projects/prj-1');
    expect(
      await screen.findByText(/已有 5 组官方成绩对照，攒到 20 组才能给出误差/),
    ).toBeInTheDocument();
    first.unmount();
    backend(
      report({
        prediction: prediction({
          calibration: {
            state: 'calibrated',
            pairs: 21,
            needed_pairs: 20,
            mae: '4.2',
            bias: '-1.5',
          },
        }),
      }),
    );
    renderApp('/projects/prj-1');
    expect(
      await screen.findByText(/平均绝对误差 4.2 分（百分制），平均偏差 -1.5 分/),
    ).toBeInTheDocument();
  });

  it('预测弃权时显示原因，不画区间条', async () => {
    backend(
      report({
        prediction: prediction({
          status: 'abstained',
          estimated_value: null,
          low: null,
          high: null,
          reason: '评分条款没有提取到分值，不给估计。',
          topics: [],
        }),
      }),
    );
    renderApp('/projects/prj-1');
    expect(await screen.findByText('评分条款没有提取到分值，不给估计。')).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: /得分估计/ })).not.toBeInTheDocument();
  });

  it('导出：Word 评审报告与批注版 PDF 是直接下载链接', async () => {
    backend(report());
    renderApp('/projects/prj-1');
    expect(await screen.findByRole('link', { name: '下载评审报告（Word）' })).toHaveAttribute(
      'href',
      '/api/v1/projects/prj-1/report.docx',
    );
    expect(screen.getByRole('link', { name: '下载批注审阅稿（PDF）' })).toHaveAttribute(
      'href',
      '/api/v1/projects/prj-1/body.annotated.pdf',
    );
  });

  it('资料、规则或事实有更新：提示原因并可重新评审', async () => {
    backend(report({ pipeline: pipeline({ stale_reasons: ['facts_changed', 'rules_changed'] }) }));
    renderApp('/projects/prj-1');
    expect(await screen.findByText('资料或规则有更新，报告还是基于更早的版本')).toBeInTheDocument();
    expect(screen.getByText('事实库有更新')).toBeInTheDocument();
    expect(screen.getByText('规则已更正')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重新评审' })).toBeEnabled();
  });

  it('评审由进行中变为完成后，报告自动重新读取', async () => {
    let stage: 'running' | 'done' = 'running';
    let reportGets = 0;
    backend(null);
    server.use(
      http.get('/api/v1/projects/prj-1/pipeline', () =>
        HttpResponse.json(
          stage === 'running' ? pipeline({ stage: 'running', snapshot_id: null }) : pipeline(),
        ),
      ),
      http.get('/api/v1/projects/prj-1/report', () => {
        reportGets++;
        return stage === 'running'
          ? HttpResponse.json(apiError('report_not_ready', '还没有完成的评审'), { status: 404 })
          : HttpResponse.json(report());
      }),
    );
    const { qc } = renderAppWithClient('/projects/prj-1');
    await screen.findByText('正在评审');
    stage = 'done';
    await qc.invalidateQueries({ queryKey: ['projects', 'prj-1', 'pipeline'] });
    expect(await screen.findByRole('heading', { name: '逐条响应' })).toBeInTheDocument();
    expect(reportGets).toBeGreaterThan(1);
  });
});

describe('响应矩阵辅助函数', () => {
  it('排序：违反、检查失败、无法判断、满足', () => {
    const rows = ['satisfied', 'unclear', 'failed', 'violated'].map((v) =>
      verdictRow({ rule_id: v, verdict: v as 'satisfied' }),
    );
    expect(sortVerdictRows(rows).map((r) => r.verdict)).toEqual([
      'violated',
      'failed',
      'unclear',
      'satisfied',
    ]);
  });
  it('默认展开：违反的条款，以及废标／强制类里没有明确响应或检查失败的；评分条款不展开', () => {
    expect(needsReview({ verdict: 'violated', kind: 'scoring' })).toBe(true);
    expect(needsReview({ verdict: 'unclear', kind: 'mandatory' })).toBe(true);
    expect(needsReview({ verdict: 'unclear', kind: 'scoring' })).toBe(false);
    expect(needsReview({ verdict: 'satisfied', kind: 'mandatory' })).toBe(false);
  });
  it('只有无法判断与检查失败需要醒目', () => {
    expect(needsAttention({ verdict: 'unclear', kind: 'disqualification' })).toBe(true);
    expect(needsAttention({ verdict: 'failed', kind: 'mandatory' })).toBe(true);
    expect(needsAttention({ verdict: 'violated', kind: 'mandatory' })).toBe(false);
    expect(needsAttention({ verdict: 'satisfied', kind: 'mandatory' })).toBe(false);
    // 评分条款的得分由预测评估，“无法判断”不算待核对
    expect(needsAttention({ verdict: 'unclear', kind: 'scoring' })).toBe(false);
  });
});

describe('报告页：项目功能开关', () => {
  it('手动开始评审：资料就绪时给出“开始评审”，点击发起 POST /analysis', async () => {
    backend(null);
    let posted = 0;
    server.use(
      http.get('/api/v1/projects/prj-1/pipeline', () =>
        HttpResponse.json(
          pipeline({
            stage: 'waiting_start',
            snapshot_id: null,
            round_no: null,
            steps: [
              { key: 'materials', state: 'done', task_id: null, message: null },
              { key: 'rules', state: 'waiting', task_id: null, message: null },
              { key: 'review', state: 'waiting', task_id: null, message: null },
              { key: 'prediction', state: 'waiting', task_id: null, message: null },
            ],
          }),
        ),
      ),
      http.post('/api/v1/projects/prj-1/analysis', () => {
        posted++;
        return HttpResponse.json(pipeline({ stage: 'running' }), { status: 202 });
      }),
    );
    renderApp('/projects/prj-1');
    expect(await screen.findByText('资料已就绪，等待开始评审')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '开始评审' }));
    await waitFor(() => {
      expect(posted).toBe(1);
    });
  });

  it('不显示分数、关闭报价与检测：只列失分点，不出现分数、报价卡片和对应分类', async () => {
    const settings = {
      ...project().settings,
      show_score: false,
      price: false,
      consistency_check: false,
      scope_check: false,
    };
    backend(report());
    server.use(http.get('/api/v1/projects/prj-1', () => HttpResponse.json(project({ settings }))));
    renderApp('/projects/prj-1');
    const panel = within(await screen.findByRole('region', { name: '可能的失分点' }));
    expect(panel.getByText('施工组织设计的针对性（满分 10 分）')).toBeInTheDocument();
    expect(panel.queryByText(/估计失/)).not.toBeInTheDocument();
    expect(screen.queryByText('预计技术分（未校准）')).not.toBeInTheDocument();
    expect(screen.queryByText('报价最优候选')).not.toBeInTheDocument();
    const cats = within(screen.getByRole('region', { name: '全部问题' }));
    expect(cats.queryByText('前后矛盾')).not.toBeInTheDocument();
    expect(cats.queryByText('范围残留')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '报价' })).not.toBeInTheDocument();
  });
});
