import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import type { FactList } from '../../api/types';
import { evidence, fact, snapshot } from '../../test/fixtures';
import { ME, apiError, project, renderApp } from '../../test/helpers';
import { server } from '../../test/server';

function backend(list: () => FactList) {
  server.use(
    http.get('/api/v1/me', () => HttpResponse.json(ME)),
    http.get('/api/v1/projects/prj-1', () => HttpResponse.json(project())),
    http.get('/api/v1/projects/prj-1/facts', () => HttpResponse.json(list())),
  );
}

describe('依据页：事实库', () => {
  it('列出当前事实集的条目', async () => {
    backend(() => ({
      fact_set_id: 'fct-2',
      items: [
        fact(),
        fact({
          fact_id: 'fai-2',
          name: '质保期',
          value_decimal: null,
          unit: null,
          statement: '质保 2 年',
        }),
      ],
    }));
    renderApp('/projects/prj-1/basis?tab=facts');
    const table = await screen.findByRole('table', { name: '当前事实' });
    expect(within(table).getByText('180 日历天')).toBeInTheDocument();
    expect(within(table).getByText('质保期')).toBeInTheDocument();
    expect(screen.queryByText('fct-2')).not.toBeInTheDocument(); // 不显示内部编号
  });

  it('没有事实：空状态', async () => {
    backend(() => ({ fact_set_id: null, items: [] }));
    renderApp('/projects/prj-1/basis?tab=facts');
    expect(await screen.findByText('还没有录入事实')).toBeInTheDocument();
  });

  it('说明录入的事实要重新评审后才生效', async () => {
    backend(() => ({ fact_set_id: null, items: [] }));
    renderApp('/projects/prj-1/basis?tab=facts');
    expect(await screen.findByText(/录入后重新评审才会用上/)).toBeInTheDocument();
  });

  it('撤回：填写理由后提交，请求体为 {reason}，成功后刷新列表', async () => {
    let list: FactList = { fact_set_id: 'fct-1', items: [fact()] };
    backend(() => list);
    let body: unknown = null;
    server.use(
      http.post('/api/v1/projects/prj-1/facts/fai-1/withdraw', async ({ request }) => {
        body = await request.json();
        list = { fact_set_id: 'fct-2', items: [] };
        return HttpResponse.json({ fact_set_id: 'fct-2', fact_id: 'fai-1', item_count: 0 });
      }),
    );
    renderApp('/projects/prj-1/basis?tab=facts');
    await userEvent.click(await screen.findByRole('button', { name: '撤回' }));
    const dlg = await screen.findByRole('dialog', { name: '撤回事实' });
    await userEvent.click(within(dlg).getByRole('button', { name: '确认撤回' }));
    expect(within(dlg).getByText('请填写撤回理由')).toBeInTheDocument();
    expect(body).toBeNull();
    await userEvent.type(within(dlg).getByLabelText('撤回理由'), '录入有误');
    await userEvent.click(within(dlg).getByRole('button', { name: '确认撤回' }));
    expect(await screen.findByText('还没有录入事实')).toBeInTheDocument();
    expect(body).toEqual({ reason: '录入有误' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('撤回 409 fact_not_current：显示友好提示并刷新列表', async () => {
    let gets = 0;
    backend(() => {
      gets++;
      return { fact_set_id: gets > 1 ? 'fct-2' : 'fct-1', items: [fact()] };
    });
    server.use(
      http.post('/api/v1/projects/prj-1/facts/fai-1/withdraw', () =>
        HttpResponse.json(apiError('fact_not_current', '事实不在当前事实集'), { status: 409 }),
      ),
    );
    renderApp('/projects/prj-1/basis?tab=facts');
    await userEvent.click(await screen.findByRole('button', { name: '撤回' }));
    const dlg = await screen.findByRole('dialog', { name: '撤回事实' });
    await userEvent.type(within(dlg).getByLabelText('撤回理由'), '录入有误');
    await userEvent.click(within(dlg).getByRole('button', { name: '确认撤回' }));
    expect(await within(dlg).findByText('该事实已不在当前事实集，已刷新')).toBeInTheDocument();
    await waitFor(() => {
      expect(gets).toBeGreaterThan(1);
    });
  });

  it('说明录入后不能修改，录错了撤回再录', async () => {
    backend(() => ({ fact_set_id: null, items: [] }));
    renderApp('/projects/prj-1/basis?tab=facts');
    expect(await screen.findByText('录入后不能修改，录错了可以撤回再录。')).toBeInTheDocument();
  });

  it('录入：校验必填；请求体符合 FactRequest；成功后刷新列表', async () => {
    let list: FactList = { fact_set_id: null, items: [] };
    backend(() => list);
    let req: { body: unknown; idem: string | null; csrf: string | null } | null = null;
    server.use(
      http.post('/api/v1/projects/prj-1/facts', async ({ request }) => {
        req = {
          body: await request.json(),
          idem: request.headers.get('Idempotency-Key'),
          csrf: request.headers.get('X-CSRF-Token'),
        };
        list = { fact_set_id: 'fct-1', items: [fact()] };
        return HttpResponse.json({ fact_set_id: 'fct-1', fact_id: 'fai-1', item_count: 1 });
      }),
    );
    renderApp('/projects/prj-1/basis?tab=facts');
    await screen.findByText('还没有录入事实');
    const submit = screen.getByRole('button', { name: '录入事实' });
    await userEvent.click(submit);
    expect(screen.getByText('请填写事实名称')).toBeInTheDocument();
    expect(screen.getByText('至少填写一个证据 ID')).toBeInTheDocument();
    expect(req).toBeNull();

    await userEvent.type(screen.getByLabelText('事实名称'), '总工期');
    await userEvent.type(screen.getByLabelText('主体'), '本公司');
    await userEvent.type(screen.getByLabelText('适用范围'), '一标段');
    await userEvent.type(screen.getByLabelText('数值（选填）'), '180');
    await userEvent.type(screen.getByLabelText('单位（选填）'), '日历天');
    await userEvent.type(screen.getByLabelText('事实陈述'), '承诺总工期 180 日历天');
    await userEvent.type(screen.getByLabelText('证据 ID'), 'evd-1, evd-2');
    await userEvent.click(submit);
    expect(await screen.findByRole('table', { name: '当前事实' })).toBeInTheDocument();
    expect(req).toEqual({
      body: {
        name: '总工期',
        subject: '本公司',
        scope: '一标段',
        value_decimal: '180',
        unit: '日历天',
        statement: '承诺总工期 180 日历天',
        evidence_ids: ['evd-1', 'evd-2'],
      },
      idem: expect.any(String),
      csrf: 'csrf-abc',
    });
    expect(screen.getByLabelText('事实名称')).toHaveValue('');
  });

  it('后端拒绝（证据不属于本项目）：显示后端中文提示并保留输入', async () => {
    backend(() => ({ fact_set_id: null, items: [] }));
    server.use(
      http.post('/api/v1/projects/prj-1/facts', () =>
        HttpResponse.json(apiError('evidence_not_in_project', '引用了不属于本项目的证据'), {
          status: 422,
        }),
      ),
    );
    renderApp('/projects/prj-1/basis?tab=facts');
    await screen.findByText('还没有录入事实');
    await userEvent.type(screen.getByLabelText('事实名称'), '总工期');
    await userEvent.type(screen.getByLabelText('主体'), '本公司');
    await userEvent.type(screen.getByLabelText('适用范围'), '一标段');
    await userEvent.type(screen.getByLabelText('事实陈述'), '承诺');
    await userEvent.type(screen.getByLabelText('证据 ID'), 'evd-x');
    await userEvent.click(screen.getByRole('button', { name: '录入事实' }));
    expect(await screen.findByText(/引用了不属于本项目的证据/)).toBeInTheDocument();
    expect(screen.getByLabelText('事实名称')).toHaveValue('总工期');
  });
  it('证据选择器：检索并勾选，把证据 ID 写入文本框（保留手填内容），可取消勾选', async () => {
    backend(() => ({ fact_set_id: null, items: [] }));
    server.use(
      http.get('/api/v1/projects/prj-1/snapshots', () => HttpResponse.json([snapshot()])),
      http.get('/api/v1/projects/prj-1/files', () => HttpResponse.json([])),
      http.post('/api/v1/projects/prj-1/search', () =>
        HttpResponse.json({
          snapshot_id: 'snp-1',
          mode_used: 'keyword',
          index_state: 'ready',
          gaps: [],
          hits: [
            { evidence: evidence({ evidence_id: 'evd-a' }), score: 1, channel: 'keyword' },
            {
              evidence: evidence({ evidence_id: 'evd-b', quote: '质保 2 年' }),
              score: 0.5,
              channel: 'keyword',
            },
          ],
        }),
      ),
    );
    renderApp('/projects/prj-1/basis?tab=facts');
    await screen.findByText('还没有录入事实');
    const ids = screen.getByLabelText('证据 ID');
    await userEvent.type(ids, 'evd-manual');
    await userEvent.click(screen.getByRole('button', { name: '从检索结果中选择证据' }));
    await userEvent.type(await screen.findByLabelText('检索内容'), '工期{Enter}');
    const picks = await screen.findAllByRole('checkbox', { name: /选用这条证据/ });
    expect(picks).toHaveLength(2);
    await userEvent.click(picks[0]!);
    await userEvent.click(picks[1]!);
    expect(ids).toHaveValue('evd-manual, evd-a, evd-b');
    await userEvent.click(picks[0]!);
    expect(ids).toHaveValue('evd-manual, evd-b');
    // 在检索框里按回车不会提交事实表单
    expect(screen.queryByText('请填写事实名称')).not.toBeInTheDocument();
  });
});
