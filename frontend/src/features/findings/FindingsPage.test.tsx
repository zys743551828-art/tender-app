import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import type { Finding, PipelineStatus, Revision } from '../../api/types';
import { ME, apiError, project, renderApp } from '../../test/helpers';
import {
  fact,
  fileVersion,
  finding,
  pipeline,
  report,
  revision,
  revisionDiff,
  snapshot,
  task,
} from '../../test/fixtures';
import { server } from '../../test/server';

interface Backend {
  revisions?: Revision[];
  pipelineOver?: Partial<PipelineStatus>;
}

function backend(findings: Finding[], o: Backend = {}) {
  server.use(
    http.get('/api/v1/projects/prj-1/pipeline', () => HttpResponse.json(pipeline(o.pipelineOver))),
    http.get('/api/v1/projects/prj-1/files', () =>
      HttpResponse.json([
        fileVersion('ver-t', 'tender', '招标文件.pdf'),
        fileVersion('ver-b', 'body', '技术标.pdf'),
      ]),
    ),
    http.get('/api/v1/projects/prj-1/revisions', () => HttpResponse.json(o.revisions ?? [])),
    http.get('/api/v1/snapshots/snp-1', () => HttpResponse.json(snapshot())),
    http.get('/api/v1/revisions/rvs-1/diff', () => HttpResponse.json(revisionDiff())),
    http.get('/api/v1/me', () => HttpResponse.json(ME)),
    http.get('/api/v1/projects/prj-1', () => HttpResponse.json(project())),
    http.get('/api/v1/projects/prj-1/findings', () =>
      HttpResponse.json({ items: findings, next_cursor: null }),
    ),
  );
}

describe('问题审核页', () => {
  it.each([
    { disqualification: 0, response: 1, expected: 'response', tab: '强制性要求（1）' },
    { disqualification: 1, response: 1, expected: 'disqualification', tab: '废标／否决风险（1）' },
  ] as const)(
    '优先处理资格风险：否决 $disqualification、强制 $response 时进入 $expected',
    async (c) => {
      backend([]);
      const requests: (string | null)[] = [];
      const summary = report({
        categories: report().categories.map((row) => ({
          ...row,
          open:
            row.category === 'disqualification'
              ? c.disqualification
              : row.category === 'response'
                ? c.response
                : 0,
        })),
      });
      server.use(
        http.get('/api/v1/projects/prj-1/report', () => HttpResponse.json(summary)),
        http.get('/api/v1/projects/prj-1/findings', ({ request }) => {
          requests.push(new URL(request.url).searchParams.get('category'));
          return HttpResponse.json({
            items: [finding({ category: c.expected })],
            next_cursor: null,
          });
        }),
      );
      renderApp('/projects/prj-1/findings?priority=qualification');
      expect(await screen.findByRole('complementary', { name: '问题列表' })).toBeInTheDocument();
      expect(screen.getByRole('tab', { name: c.tab })).toHaveAttribute('aria-selected', 'true');
      expect(requests.length).toBeGreaterThan(0);
      expect(requests.every((category) => category === c.expected)).toBe(true);
      await userEvent.click(screen.getByRole('tab', { name: '改进建议（0）' }));
      await waitFor(() => {
        expect(requests.at(-1)).toBe('improvement');
      });
      expect(screen.getByRole('tab', { name: '改进建议（0）' })).toHaveAttribute(
        'aria-selected',
        'true',
      );
    },
  );

  it('显式分类链接保持用户选择，即使同时带优先参数', async () => {
    backend([]);
    server.use(http.get('/api/v1/projects/prj-1/report', () => HttpResponse.json(report())));
    renderApp('/projects/prj-1/findings?priority=qualification&category=scope');
    expect(await screen.findByRole('tab', { name: '范围残留（0）' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });

  it('列出发现，待核实的标“待核实”；招标要求与正文写法并排对照', async () => {
    backend([
      finding(),
      finding({
        finding_id: 'fnd-2',
        statement: '交通导改的响应仍需补充',
        status: 'confirmed',
        evidence: [],
      }),
    ]);
    renderApp('/projects/prj-1/findings');
    const list = await screen.findByRole('complementary', { name: '问题列表' });
    expect(within(list).getByText('工期表述与招标要求不一致')).toBeInTheDocument();
    expect(within(list).getAllByText('待核实')).toHaveLength(1); // 已确认的不再标待核实
    expect(screen.getByText('与否决或废标条款冲突，整份投标可能作废。')).toBeInTheDocument();
    const detail = screen.getByRole('region', { name: /详情/ });
    expect(within(detail).getByRole('heading', { name: '招标文件要求' })).toBeInTheDocument();
    expect(within(detail).getByRole('heading', { name: '施组正文写法' })).toBeInTheDocument();
    expect(within(detail).getByText('工期 180 日历天')).toBeInTheDocument();
    expect(within(detail).getByText('本工程拟用 160 天完成')).toBeInTheDocument();
    expect(within(detail).getByText(/施工组织设计\.pdf · 第 17 页/)).toBeInTheDocument();
  });
  it('驳回理由为空时不能提交；确认可以不写理由', async () => {
    let posted = 0;
    backend([finding()]);
    server.use(
      http.post('/api/v1/findings/fnd-1/reviews', () => {
        posted++;
        return HttpResponse.json({});
      }),
    );
    renderApp('/projects/prj-1/findings');
    await userEvent.click(await screen.findByRole('button', { name: '驳回' }));
    expect(screen.getByText(/请填写理由/)).toBeInTheDocument();
    expect(posted).toBe(0);
    await userEvent.click(screen.getByRole('button', { name: '确认问题' }));
    await waitFor(() => {
      expect(posted).toBe(1);
    });
  });

  it('确认问题：提交 object_version / decision / reason，带 CSRF 与幂等键；成功后清空理由并提示', async () => {
    backend([finding()]);
    let req: { body: unknown; csrf: string | null; idem: string | null } | null = null;
    server.use(
      http.post('/api/v1/findings/fnd-1/reviews', async ({ request }) => {
        req = {
          body: await request.json(),
          csrf: request.headers.get('X-CSRF-Token'),
          idem: request.headers.get('Idempotency-Key'),
        };
        return HttpResponse.json({ review_id: 'rev-1' });
      }),
    );
    renderApp('/projects/prj-1/findings');
    await userEvent.type(await screen.findByLabelText('理由'), '  两处均指整体施工工期  ');
    await userEvent.click(screen.getByRole('button', { name: '确认问题' }));
    expect(await screen.findByText('已记录：确认问题')).toBeInTheDocument();
    expect(req).toEqual({
      body: { object_version: '4', decision: 'confirm', reason: '两处均指整体施工工期' },
      csrf: 'csrf-abc',
      idem: expect.any(String),
    });
    expect(screen.getByLabelText('理由')).toHaveValue('');
  });

  it('412 版本已变化：提示刷新、保留已输入的理由；再次提交仍用同一个幂等键', async () => {
    backend([finding()]);
    const keys: (string | null)[] = [];
    server.use(
      http.post('/api/v1/findings/fnd-1/reviews', ({ request }) => {
        keys.push(request.headers.get('Idempotency-Key'));
        return HttpResponse.json(
          apiError('STALE_VERSION', '对象已被他人修改，请刷新后重试', { request_id: 'req-412' }),
          { status: 412 },
        );
      }),
    );
    renderApp('/projects/prj-1/findings');
    await userEvent.type(await screen.findByLabelText('理由'), '不成立');
    await userEvent.click(screen.getByRole('button', { name: '驳回' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('版本已变化');
    expect(alert).toHaveTextContent('你输入的内容已保留');
    expect(alert).toHaveTextContent('req-412');
    expect(screen.getByLabelText('理由')).toHaveValue('不成立');
    await userEvent.click(screen.getByRole('button', { name: '驳回' }));
    await screen.findByRole('alert');
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  it('缺少事实时展示所需事实，改稿建议说明要先补事实', async () => {
    backend([finding({ status: 'confirmed', required_facts: ['沟槽支护设计条件'] })]);
    renderApp('/projects/prj-1/findings');
    expect(await screen.findByText('沟槽支护设计条件')).toBeInTheDocument();
    const revise = screen.getByRole('region', { name: '改稿建议' });
    expect(within(revise).getByText(/还缺事实，不能生成建议/)).toBeInTheDocument();
    expect(within(revise).getByRole('link', { name: '事实库' })).toHaveAttribute(
      'href',
      '/projects/prj-1/basis?tab=facts',
    );
    expect(screen.queryByRole('button', { name: '生成改稿建议' })).not.toBeInTheDocument();
  });
  it('状态与分类筛选交给服务端：默认最近一轮评审，切换后带参数重新请求', async () => {
    const all = [
      finding(),
      finding({ finding_id: 'fnd-2', statement: '已处理的问题', status: 'resolved', evidence: [] }),
    ];
    const urls: URLSearchParams[] = [];
    backend([]);
    server.use(
      http.get('/api/v1/projects/prj-1/findings', ({ request }) => {
        const q = new URL(request.url).searchParams;
        urls.push(q);
        const items = all.filter((f) => !q.get('status') || f.status === q.get('status'));
        return HttpResponse.json({ items, next_cursor: null });
      }),
    );
    renderApp('/projects/prj-1/findings?category=response');
    const list = await screen.findByRole('complementary', { name: '问题列表' });
    expect(urls[0]?.get('snapshot_id')).toBe('snp-1');
    expect(urls[0]?.get('category')).toBe('response');
    expect(within(list).getByText('工期表述与招标要求不一致')).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText('按状态筛选'), 'resolved');
    await waitFor(() => {
      expect(urls.at(-1)?.get('status')).toBe('resolved');
    });
    expect(urls.at(-1)?.get('category')).toBe('response');
    expect(await within(list).findByText('已处理的问题')).toBeInTheDocument();
    expect(within(list).queryByText('工期表述与招标要求不一致')).not.toBeInTheDocument();
  });

  it('列表用稳定短码标注问题，而不是随筛选变化的序号', async () => {
    backend([
      finding({ finding_id: 'fnd_3f9a1c0b7d2e4a56' }),
      finding({ finding_id: 'fnd_77aa00bb11cc22dd', statement: '另一条' }),
    ]);
    renderApp('/projects/prj-1/findings');
    const list = await screen.findByRole('complementary', { name: '问题列表' });
    expect(within(list).getByText(/#3F9A1C/)).toBeInTheDocument();
    expect(within(list).getByText(/#77AA00/)).toBeInTheDocument();
    expect(screen.getByRole('region', { name: '问题 #3F9A1C 详情' })).toBeInTheDocument();
  });

  it('各状态下的审核动作与后端状态转换表一致', async () => {
    const { ALLOWED_DECISIONS } = await import('./shared');
    expect(ALLOWED_DECISIONS).toEqual({
      candidate: ['confirm', 'reject', 'defer', 'request_facts'],
      deferred: ['confirm', 'reject'],
      confirmed: ['resolve'],
      recheck_pending: ['resolve', 'confirm'],
      revision_pending: ['reject', 'resolve'],
      rejected: ['reopen'],
      resolved: ['reopen'],
    });
  });

  it('审核成功后重新读取项目（状态与 revision 可能已变）', async () => {
    backend([finding()]);
    let projectGets = 0;
    server.use(
      http.get('/api/v1/projects/prj-1', () => {
        projectGets++;
        return HttpResponse.json(project());
      }),
      http.post('/api/v1/findings/fnd-1/reviews', () => HttpResponse.json({ review_id: 'rev-1' })),
    );
    renderApp('/projects/prj-1/findings');
    await userEvent.type(await screen.findByLabelText('理由'), '同意');
    const before = projectGets;
    await userEvent.click(screen.getByRole('button', { name: '确认问题' }));
    await screen.findByText('已记录：确认问题');
    await waitFor(() => {
      expect(projectGets).toBeGreaterThan(before);
    });
  });

  it('已驳回、已解决的问题可以“重新打开”，提交 decision=reopen 与理由', async () => {
    backend([finding({ status: 'rejected' })]);
    let body: unknown = null;
    server.use(
      http.post('/api/v1/findings/fnd-1/reviews', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ review_id: 'rev-2' });
      }),
    );
    renderApp('/projects/prj-1/findings');
    await userEvent.type(await screen.findByLabelText('理由'), '证据补齐后需要重新判断');
    await userEvent.click(screen.getByRole('button', { name: '重新打开' }));
    expect(await screen.findByText('已记录：重新打开')).toBeInTheDocument();
    expect(body).toMatchObject({ decision: 'reopen', object_version: '4' });
  });

  it('已确认的问题直接“标记已解决”是次要按钮，并写明尚未采纳建议／未复检', async () => {
    backend([finding({ status: 'confirmed' })]);
    renderApp('/projects/prj-1/findings');
    const btn = await screen.findByRole('button', { name: '标记已解决' });
    expect(btn).not.toHaveAttribute('data-variant', 'primary');
    expect(screen.getByText(/尚未采纳修改建议，也未复检/)).toBeInTheDocument();
  });

  it('待修改的问题也可以人工“标记已解决”（次要按钮，提示未复检）', async () => {
    backend([finding({ status: 'revision_pending' })]);
    renderApp('/projects/prj-1/findings');
    const btn = await screen.findByRole('button', { name: '标记已解决' });
    expect(btn).not.toHaveAttribute('data-variant', 'primary');
    expect(screen.getByText(/新正文尚未复检/)).toBeInTheDocument();
  });

  it('暂缓且缺事实的问题：说明先录入事实再重新评审，给出事实库链接', async () => {
    backend([finding({ status: 'deferred', required_facts: ['沟槽支护设计条件'] })]);
    renderApp('/projects/prj-1/findings');
    expect(await screen.findByText(/已暂缓，等待补充事实/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '录入事实' })).toHaveAttribute(
      'href',
      '/projects/prj-1/basis?tab=facts',
    );
  });
  it('暂缓的问题只能确认或驳回；request_facts 显示为“暂缓，待补事实”', async () => {
    backend([finding({ status: 'deferred' })]);
    renderApp('/projects/prj-1/findings');
    expect(await screen.findByRole('button', { name: '确认问题' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '驳回' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '暂缓' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '暂缓，待补事实' })).not.toBeInTheDocument();
    const { decisionLabel } = await import('../../lib/labels');
    expect(decisionLabel('request_facts')).toBe('暂缓，待补事实');
  });

  it('待修改：说明上传新正文会自动开新一轮评审、不会自动结案；上传链接带正文用途', async () => {
    backend([finding({ status: 'revision_pending' })]);
    renderApp('/projects/prj-1/findings');
    expect(await screen.findByText(/上传新正文后自动开始新一轮评审/)).toBeInTheDocument();
    expect(screen.getByText(/在新一轮报告里看这条问题还在不在/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '上传修改后的正文' })).toHaveAttribute(
      'href',
      '/projects/prj-1/materials?role=body',
    );
    expect(screen.getByRole('button', { name: '驳回' })).toBeInTheDocument();
  });
  it('确认过的问题：被标为“已解决”前不会出现不存在的动作', async () => {
    backend([finding({ status: 'confirmed' })]);
    renderApp('/projects/prj-1/findings');
    expect(await screen.findByRole('button', { name: '标记已解决' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '确认问题' })).not.toBeInTheDocument();
  });

  it('没有发现：空状态', async () => {
    backend([]);
    renderApp('/projects/prj-1/findings');
    expect(await screen.findByText('这一轮没有发现“废标／否决风险”问题')).toBeInTheDocument();
    expect(screen.getByText(/图纸、示意图里的内容仍需要人看/)).toBeInTheDocument();
  });
  it('项目 404：不区分“不存在”与“无权”，不泄漏信息', async () => {
    server.use(
      http.get('/api/v1/me', () => HttpResponse.json(ME)),
      http.get('/api/v1/projects/prj-x', () =>
        HttpResponse.json(apiError('NOT_FOUND', '对象不存在，或你无权访问'), { status: 404 }),
      ),
    );
    renderApp('/projects/prj-x/findings');
    expect(await screen.findByText('找不到这个项目')).toBeInTheDocument();
    expect(screen.getByText(/地址可能有误，或项目已被删除/)).toBeInTheDocument();
  });
});

describe('分类与评审状态', () => {
  it('分类页签带未处理数（取自报告），点击切换分类并带入地址', async () => {
    backend([finding()]);
    server.use(http.get('/api/v1/projects/prj-1/report', () => HttpResponse.json(report())));
    renderApp('/projects/prj-1/findings');
    const tabs = within(await screen.findByRole('tablist', { name: '问题分类' }));
    expect(tabs.getAllByRole('tab').map((t) => t.textContent)).toEqual([
      '废标／否决风险（0）',
      '强制性要求（1）',
      '前后矛盾（1）',
      '范围残留（0）',
      '改进建议（3）',
    ]);
    expect(tabs.getByRole('tab', { name: /废标／否决风险/ })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await userEvent.click(tabs.getByRole('tab', { name: /范围残留/ }));
    expect(tabs.getByRole('tab', { name: /范围残留/ })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByText(/正文出现招标文件及补遗没有的工程对象/)).toBeInTheDocument();
  });

  it('依据的规则还没核对时，详情里说明暂按原文判断', async () => {
    backend([finding({ rule_basis: 'unconfirmed' })]);
    renderApp('/projects/prj-1/findings');
    expect(await screen.findByText(/依据的规则还没核对，暂按原文判断/)).toBeInTheDocument();
  });
  it('还没有完成的评审：说明没有评审不等于没有问题，且不请求问题列表', async () => {
    let listed = 0;
    server.use(
      http.get('/api/v1/projects/prj-1', () => HttpResponse.json(project())),
      http.get('/api/v1/me', () => HttpResponse.json(ME)),
      http.get('/api/v1/projects/prj-1/findings', () => {
        listed++;
        return HttpResponse.json({ items: [], next_cursor: null });
      }),
    );
    renderApp('/projects/prj-1/findings');
    expect(await screen.findByRole('heading', { name: '还没有完成的评审' })).toBeInTheDocument();
    expect(listed).toBe(0);
  });

  it('资料有更新时顶部提示原因并给出“重新评审”', async () => {
    backend([finding()], { pipelineOver: { stale_reasons: ['body_updated'] } });
    let restarted = 0;
    server.use(
      http.post('/api/v1/projects/prj-1/analysis', () => {
        restarted++;
        return HttpResponse.json(pipeline({ stage: 'running' }), { status: 202 });
      }),
    );
    renderApp('/projects/prj-1/findings');
    expect(await screen.findByText('技术标正文有了新版本')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '重新评审' }));
    await waitFor(() => {
      expect(restarted).toBe(1);
    });
  });

  it('问题处理完、可以登记提交时，页头给出去登记的入口', async () => {
    backend([finding({ status: 'resolved' })]);
    server.use(
      http.get('/api/v1/projects/prj-1', () =>
        HttpResponse.json(project({ state: 'ready_to_submit' })),
      ),
    );
    renderApp('/projects/prj-1/findings');
    expect(await screen.findByRole('link', { name: '问题已处理完，去登记提交' })).toHaveAttribute(
      'href',
      '/projects/prj-1/submit',
    );
  });

  it('还有问题没处理时，页头不催着去提交', async () => {
    backend([finding()]);
    renderApp('/projects/prj-1/findings');
    await screen.findByRole('complementary', { name: '问题列表' });
    expect(screen.queryByRole('link', { name: /去登记提交/ })).not.toBeInTheDocument();
  });
});

describe('逐条处理', () => {
  const three = () => [
    finding({ finding_id: 'fnd-1', statement: '第一条问题', evidence: [] }),
    finding({ finding_id: 'fnd-2', statement: '第二条问题', status: 'resolved', evidence: [] }),
    finding({ finding_id: 'fnd-3', statement: '第三条问题', evidence: [] }),
  ];

  it('显示“第 i / n 条”，上一条／下一条与 J／K 键切换；在输入框里打字不触发', async () => {
    backend(three());
    renderApp('/projects/prj-1/findings');
    expect(await screen.findByText('第 1 / 3 条')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '‹ 上一条' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: '下一条 ›' }));
    expect(screen.getByText('第 2 / 3 条')).toBeInTheDocument();
    await userEvent.keyboard('j');
    expect(screen.getByText('第 3 / 3 条')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '下一条 ›' })).toBeDisabled();
    await userEvent.keyboard('k');
    expect(screen.getByText('第 2 / 3 条')).toBeInTheDocument();
  });

  it('确认一条后自动跳到后面下一条未处理的问题（跳过已解决的）', async () => {
    backend(three());
    server.use(
      http.post('/api/v1/findings/fnd-1/reviews', () => HttpResponse.json({ review_id: 'rev-1' })),
    );
    renderApp('/projects/prj-1/findings');
    await screen.findByText('第 1 / 3 条');
    await userEvent.type(await screen.findByLabelText('理由'), '证据充分');
    await userEvent.click(screen.getByRole('button', { name: '确认问题' }));
    expect(await screen.findByText('第 3 / 3 条')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /详情/ })).toHaveTextContent('第三条问题');
  });

  it('详情头部显示处理进度条，驳回的问题单独说明', async () => {
    backend([finding({ status: 'confirmed', evidence: [] })]);
    const { unmount } = renderApp('/projects/prj-1/findings');
    const steps = await screen.findByRole('list', { name: '处理进度' });
    expect(within(steps).getByText('已确认').closest('li')).toHaveAttribute('aria-current', 'step');
    unmount();
    backend([finding({ status: 'rejected', evidence: [] })]);
    renderApp('/projects/prj-1/findings');
    expect(await screen.findByText(/已驳回：不再处理/)).toBeInTheDocument();
  });
});

describe('改稿建议', () => {
  const confirmed = () => finding({ status: 'confirmed' });

  /** 已确认的问题直接展开改稿建议。 */
  async function openRevisionTab() {
    await screen.findByRole('region', { name: '改稿建议' });
  }

  it('范围必填；提交 RevisionRequest（底稿取快照正文版本、allowed_fact_ids 为空）；返回任务并跟踪，完成后列出建议', async () => {
    let revisions: Revision[] = [];
    backend([confirmed()]);
    server.use(http.get('/api/v1/projects/prj-1/revisions', () => HttpResponse.json(revisions)));
    let req: { body: unknown; idem: string | null } | null = null;
    server.use(
      http.post('/api/v1/projects/prj-1/revisions', async ({ request }) => {
        req = { body: await request.json(), idem: request.headers.get('Idempotency-Key') };
        return HttpResponse.json(
          task({ task_id: 'tsk-rv', kind: 'revision', snapshot_id: 'snp-1' }),
          { status: 202 },
        );
      }),
      http.get('/api/v1/tasks/tsk-rv', () => {
        revisions = [revision()];
        return HttpResponse.json(
          task({ task_id: 'tsk-rv', kind: 'revision', snapshot_id: 'snp-1', state: 'succeeded' }),
        );
      }),
    );
    renderApp('/projects/prj-1/findings');
    await openRevisionTab();
    expect(screen.getByText(/事实库是空的/)).toBeInTheDocument();
    const submit = screen.getByRole('button', { name: '生成改稿建议' });
    await waitFor(() => {
      expect(submit).toBeEnabled();
    });
    await userEvent.click(submit);
    expect(screen.getByText('请写明允许修改的范围，例如章节名')).toBeInTheDocument();
    expect(req).toBeNull();

    await userEvent.type(screen.getByLabelText('允许修改的范围'), ' 第 5 章 施工进度 ');
    await userEvent.click(submit);
    const revise = screen.getByRole('region', { name: '改稿建议' });
    expect(await within(revise).findByText('AI 建议 · 待人工确认')).toBeInTheDocument();
    expect(req).toEqual({
      body: {
        base_version_id: 'ver-b',
        snapshot_id: 'snp-1',
        finding_ids: ['fnd-1'],
        allowed_fact_ids: [],
        scope: '第 5 章 施工进度',
      },
      idem: expect.any(String),
    });
    expect(screen.queryByText('art-diff-1')).not.toBeInTheDocument(); // 不显示内部编号
    expect(screen.getByRole('button', { name: '查看修改内容' })).toBeInTheDocument();
  });

  it('允许使用的事实：从当前事实集勾选，未确认的不可选；请求体带所选 fact_id', async () => {
    backend([confirmed()]);
    let body: { allowed_fact_ids: string[] } | null = null;
    server.use(
      http.get('/api/v1/projects/prj-1/facts', () =>
        HttpResponse.json({
          fact_set_id: 'fct-3',
          items: [
            fact({ fact_id: 'fai-a', name: '总工期' }),
            fact({ fact_id: 'fai-b', name: '质保期', statement: '质保 2 年' }),
            fact({
              fact_id: 'fai-c',
              name: '待核事实',
              statement: '待核',
              confirmation: 'pending',
            }),
          ],
        }),
      ),
      http.post('/api/v1/projects/prj-1/revisions', async ({ request }) => {
        body = (await request.json()) as { allowed_fact_ids: string[] };
        return HttpResponse.json(task({ task_id: 'tsk-rv', kind: 'revision' }), { status: 202 });
      }),
      http.get('/api/v1/tasks/tsk-rv', () =>
        HttpResponse.json(task({ task_id: 'tsk-rv', kind: 'revision', state: 'running' })),
      ),
    );
    renderApp('/projects/prj-1/findings');
    await openRevisionTab();
    const a = await screen.findByRole('checkbox', { name: /总工期/ });
    expect(screen.getByRole('checkbox', { name: /待核事实/ })).toBeDisabled();
    await userEvent.click(a);
    await userEvent.type(screen.getByLabelText('允许修改的范围'), '第 5 章');
    await userEvent.click(screen.getByRole('button', { name: '生成改稿建议' }));
    await waitFor(() => {
      expect(body).not.toBeNull();
    });
    expect(body).toMatchObject({ allowed_fact_ids: ['fai-a'] });
  });

  it('采纳：请求体为 base_version_id 与 null，不带 If-Match；成功后问题刷新为“待修改”', async () => {
    let adopted = false;
    let status: Finding['status'] = 'confirmed';
    backend([]);
    server.use(
      http.get('/api/v1/projects/prj-1/findings', () =>
        HttpResponse.json({ items: [finding({ status })], next_cursor: null }),
      ),
      http.get('/api/v1/projects/prj-1/revisions', () =>
        HttpResponse.json([revision({ status: adopted ? 'adopted' : 'proposed' })]),
      ),
    );
    let req: { body: unknown; ifMatch: string | null; csrf: string | null } | null = null;
    server.use(
      http.post('/api/v1/revisions/rvs-1/adopt', async ({ request }) => {
        req = {
          body: await request.json(),
          ifMatch: request.headers.get('If-Match'),
          csrf: request.headers.get('X-CSRF-Token'),
        };
        adopted = true;
        status = 'revision_pending';
        return HttpResponse.json(revision({ status: 'adopted' }));
      }),
    );
    renderApp('/projects/prj-1/findings');
    await openRevisionTab();
    await userEvent.click(await screen.findByRole('button', { name: '采纳' }));
    const dialog = await screen.findByRole('dialog', { name: '采纳改稿建议' });
    await userEvent.click(within(dialog).getByRole('button', { name: '确认采纳' }));
    expect(await screen.findByText('已采纳改稿建议')).toBeInTheDocument();
    expect(req).toEqual({
      body: { base_version_id: 'ver-b', edited_diff_artifact_id: null },
      ifMatch: null,
      csrf: 'csrf-abc',
    });
    expect(await screen.findByText('已采纳')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '采纳' })).not.toBeInTheDocument();
    const list = screen.getByRole('complementary', { name: '问题列表' });
    await waitFor(() => {
      expect(list.querySelector('[data-tone="blue"]')).toHaveTextContent('待修改');
    });
  });

  it('展开建议显示“原文 → 改为”，并汇总被丢弃的候选及原因；采纳对话框里直接可见', async () => {
    backend([confirmed()], { revisions: [revision()] });
    server.use(
      http.get('/api/v1/revisions/rvs-1/diff', () =>
        HttpResponse.json(
          revisionDiff({
            dropped: [
              { finding_id: 'fnd-1', reason: 'invented_number' },
              { finding_id: 'fnd-1', reason: 'invented_number' },
              { finding_id: 'fnd-1', reason: 'original_not_verbatim' },
            ],
          }),
        ),
      ),
    );
    renderApp('/projects/prj-1/findings');
    await openRevisionTab();
    const revise = within(screen.getByRole('region', { name: '改稿建议' }));
    expect(revise.queryByText('本工程拟用 160 天完成')).not.toBeInTheDocument();
    await userEvent.click(await revise.findByRole('button', { name: '查看修改内容' }));
    expect(await revise.findByText('本工程拟用 160 天完成')).toBeInTheDocument();
    expect(revise.getByText('本工程总工期 180 日历天')).toBeInTheDocument();
    expect(revise.getByText('说明：对齐招标工期')).toBeInTheDocument();
    expect(
      revise.getByText(
        /另有 3 条候选修改被系统丢弃：出现了没有依据的数字 2 条；“原文”与正文不一致 1 条/,
      ),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '采纳' }));
    const dialog = await screen.findByRole('dialog', { name: '采纳改稿建议' });
    expect(await within(dialog).findByText('本工程总工期 180 日历天')).toBeInTheDocument();
  });

  it('base_version_stale：提示建议已过期，不能再次提交', async () => {
    backend([confirmed()], { revisions: [revision()] });
    server.use(
      http.post('/api/v1/revisions/rvs-1/adopt', () =>
        HttpResponse.json(apiError('base_version_stale', '正文已有更新版本，这份建议已过期'), {
          status: 409,
        }),
      ),
    );
    renderApp('/projects/prj-1/findings');
    await openRevisionTab();
    await userEvent.click(await screen.findByRole('button', { name: '采纳' }));
    const dialog = await screen.findByRole('dialog', { name: '采纳改稿建议' });
    await userEvent.click(within(dialog).getByRole('button', { name: '确认采纳' }));
    const alert = await within(dialog).findByRole('alert');
    expect(alert).toHaveTextContent('底稿已有新版本，这份建议已过期');
    expect(within(dialog).getByRole('button', { name: '确认采纳' })).toBeDisabled();
  });

  it('revision_already_reviewed：提示已被处理', async () => {
    backend([confirmed()], { revisions: [revision()] });
    server.use(
      http.post('/api/v1/revisions/rvs-1/adopt', () =>
        HttpResponse.json(apiError('revision_already_reviewed', '该建议已处理'), { status: 409 }),
      ),
    );
    renderApp('/projects/prj-1/findings');
    await openRevisionTab();
    await userEvent.click(await screen.findByRole('button', { name: '采纳' }));
    const dialog = await screen.findByRole('dialog', { name: '采纳改稿建议' });
    await userEvent.click(within(dialog).getByRole('button', { name: '确认采纳' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('这份建议已被处理');
  });

  it('驳回：理由必填，请求体为 base_version_id 与 reason', async () => {
    backend([confirmed()], { revisions: [revision()] });
    let body: unknown = null;
    server.use(
      http.post('/api/v1/revisions/rvs-1/reject', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(revision({ status: 'rejected' }));
      }),
    );
    renderApp('/projects/prj-1/findings');
    await openRevisionTab();
    await userEvent.click(await screen.findByRole('button', { name: '驳回' }));
    const dialog = await screen.findByRole('dialog', { name: '驳回改稿建议' });
    await userEvent.click(within(dialog).getByRole('button', { name: '确认驳回' }));
    expect(within(dialog).getByText('请填写驳回理由')).toBeInTheDocument();
    expect(body).toBeNull();
    await userEvent.type(within(dialog).getByLabelText('理由'), '范围不对');
    await userEvent.click(within(dialog).getByRole('button', { name: '确认驳回' }));
    expect(await screen.findByText('已驳回改稿建议')).toBeInTheDocument();
    expect(body).toEqual({ base_version_id: 'ver-b', reason: '范围不对' });
  });
});
