import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import type { PricePlanRequest } from '../../api/types';
import { evidence, priceWithSimulation, pricePlan, ruleSet, simulation } from '../../test/fixtures';
import { ME, apiError, project, renderApp } from '../../test/helpers';
import { server } from '../../test/server';
import { exchangeSentence } from './PricePage';

function backend(saved = true) {
  server.use(
    http.get('/api/v1/me', () => HttpResponse.json(ME)),
    http.get('/api/v1/projects/prj-1', () => HttpResponse.json(project())),
    http.get('/api/v1/projects/prj-1/price', () =>
      HttpResponse.json(saved ? priceWithSimulation() : null),
    ),
    http.get('/api/v1/projects/prj-1/price/history', () =>
      HttpResponse.json(
        saved ? [pricePlan(), pricePlan({ plan_id: 'prp-0', note: '早期方案' })] : [],
      ),
    ),
  );
}

describe('报价页：试算', () => {
  it('载入已保存的方案并试算：结果表、换算句、最优候选、风险提示、价格分曲线', async () => {
    backend();
    const bodies: PricePlanRequest[] = [];
    server.use(
      http.post('/api/v1/projects/prj-1/price:simulate', async ({ request }) => {
        bodies.push((await request.json()) as PricePlanRequest);
        return HttpResponse.json(simulation({ notes: ['平均值法的基准价取决于其他投标人的报价'] }));
      }),
    );
    renderApp('/projects/prj-1/price');
    expect(await screen.findByLabelText('价格分满分')).toHaveValue('30');
    const table = await screen.findByRole('table', { name: '候选报价的价格分' }, { timeout: 3000 });
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByText('最优')).toBeInTheDocument();
    expect(within(rows[1]!).getByText(/超过最高限价，将被否决/)).toBeInTheDocument();
    expect(rows[1]).toHaveClass('row-alert');
    expect(screen.getByText(/1 个技术分约相当于 1% 的报价/)).toBeInTheDocument();
    expect(screen.getByText(/最优候选：/)).toHaveTextContent('最优候选：980，价格分 29');
    expect(screen.getByText('平均值法的基准价取决于其他投标人的报价')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /价格分曲线/ })).toBeInTheDocument();
    expect(bodies[0]?.params.full_score).toBe('30');
    expect(bodies[0]?.candidate_prices).toEqual(['980', '1100']);
  });

  it('改参数后防抖试算：连续输入只发出最后一次请求', async () => {
    backend();
    const bodies: PricePlanRequest[] = [];
    server.use(
      http.post('/api/v1/projects/prj-1/price:simulate', async ({ request }) => {
        bodies.push((await request.json()) as PricePlanRequest);
        return HttpResponse.json(simulation());
      }),
    );
    renderApp('/projects/prj-1/price');
    const input = await screen.findByLabelText(/候选报价（最多 20 个）/);
    await waitFor(() => {
      expect(bodies).toHaveLength(1);
    });
    await userEvent.clear(input);
    await userEvent.type(input, '970');
    await waitFor(() => {
      expect(bodies.at(-1)?.candidate_prices).toEqual(['970']);
    });
    // 逐字输入的中间状态（空、9、97）都没有被发出
    expect(bodies.some((b) => b.candidate_prices.join() === '9')).toBe(false);
    expect(bodies.some((b) => b.candidate_prices.join() === '97')).toBe(false);
  });

  it('输入不合法：给出友好错误、不发试算请求', async () => {
    backend();
    let calls = 0;
    server.use(
      http.post('/api/v1/projects/prj-1/price:simulate', () => {
        calls++;
        return HttpResponse.json(simulation());
      }),
    );
    renderApp('/projects/prj-1/price');
    const input = await screen.findByLabelText(/候选报价（最多 20 个）/);
    await waitFor(() => {
      expect(calls).toBe(1);
    });
    await userEvent.type(input, '\n1e3');
    expect(await screen.findByText(/第 3 个“1e3”不是有效的正数/)).toBeInTheDocument();
    expect(input).toHaveAttribute('aria-invalid', 'true');
    await new Promise((r) => setTimeout(r, 600));
    expect(calls).toBe(1);
  });

  it('后端试算 422：显示后端中文消息', async () => {
    backend();
    server.use(
      http.post('/api/v1/projects/prj-1/price:simulate', () =>
        HttpResponse.json(apiError('validation_error', '固定基准价必须给出 fixed_value'), {
          status: 422,
        }),
      ),
    );
    renderApp('/projects/prj-1/price');
    expect(
      await screen.findByText('固定基准价必须给出 fixed_value', {}, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it('平均值法：说明竞争对手报价只是估计；固定值法不显示该说明和“计入己方报价”', async () => {
    backend();
    server.use(
      http.post('/api/v1/projects/prj-1/price:simulate', () => HttpResponse.json(simulation())),
    );
    renderApp('/projects/prj-1/price');
    const method = await screen.findByLabelText('取法');
    expect(screen.queryByText(/下面填的只是估计/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText('把己方报价计入平均')).not.toBeInTheDocument();
    await userEvent.selectOptions(method, 'average');
    expect(screen.getByText(/下面填的只是估计/)).toBeInTheDocument();
    expect(screen.getByLabelText('把己方报价计入平均')).toBeInTheDocument();
    expect(screen.queryByLabelText('固定基准价')).not.toBeInTheDocument();
  });
  it('换算句：不扣分时无法换算', () => {
    expect(
      exchangeSentence(
        simulation({ exchange_rate: { points_per_pct_above: '0', pct_per_point_above: null } }),
      ),
    ).toContain('无法把 1 个技术分换算成报价');
  });
});

describe('报价页：保存与历史', () => {
  it('保存：PUT 带整份方案与幂等键，保存的是新版本', async () => {
    backend();
    let req: { body: PricePlanRequest; idem: string | null } | null = null;
    server.use(
      http.post('/api/v1/projects/prj-1/price:simulate', () => HttpResponse.json(simulation())),
      http.put('/api/v1/projects/prj-1/price', async ({ request }) => {
        req = {
          body: (await request.json()) as PricePlanRequest,
          idem: request.headers.get('Idempotency-Key'),
        };
        return HttpResponse.json(priceWithSimulation());
      }),
    );
    renderApp('/projects/prj-1/price');
    const note = await screen.findByLabelText(/备注/);
    await userEvent.type(note, '含税');
    await userEvent.click(screen.getByRole('button', { name: '保存方案' }));
    await waitFor(() => {
      expect(req).not.toBeNull();
    });
    expect(req!.body.note).toBe('含税');
    expect(req!.body.params.benchmark.method).toBe('fixed');
    expect(req!.idem).toBeTruthy();
  });

  it('保存时表单不合法：不发请求并显示错误', async () => {
    backend(false);
    let puts = 0;
    server.use(
      http.put('/api/v1/projects/prj-1/price', () => {
        puts++;
        return HttpResponse.json(priceWithSimulation());
      }),
    );
    renderApp('/projects/prj-1/price');
    await userEvent.click(await screen.findByRole('button', { name: '保存方案' }));
    expect(await screen.findByText(/请填写大于 0 的价格分满分/)).toBeInTheDocument();
    expect(puts).toBe(0);
  });

  it('后端拒绝保存：显示后端消息', async () => {
    backend();
    server.use(
      http.post('/api/v1/projects/prj-1/price:simulate', () => HttpResponse.json(simulation())),
      http.put('/api/v1/projects/prj-1/price', () =>
        HttpResponse.json(apiError('price_out_of_range', '报价超出可以计算的范围'), {
          status: 422,
        }),
      ),
    );
    renderApp('/projects/prj-1/price');
    await userEvent.click(await screen.findByRole('button', { name: '保存方案' }));
    expect(await screen.findByText('报价超出可以计算的范围')).toBeInTheDocument();
  });

  it('保存过的方案：列出全部版本，可载入到表单', async () => {
    backend();
    server.use(
      http.get('/api/v1/projects/prj-1/price/history', () =>
        HttpResponse.json([
          pricePlan(),
          pricePlan({
            plan_id: 'prp-0',
            note: '早期方案',
            candidate_prices: ['900'],
            params: { ...pricePlan().params, full_score: '25' },
          }),
        ]),
      ),
      http.post('/api/v1/projects/prj-1/price:simulate', () => HttpResponse.json(simulation())),
    );
    renderApp('/projects/prj-1/price');
    const history = (await screen.findByRole('heading', { name: '保存过的方案' })).closest(
      'section',
    )!;
    const items = await within(history).findAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(within(items[0]!).getByText('当前')).toBeInTheDocument();
    await userEvent.click(within(items[1]!).getByRole('button', { name: '载入' }));
    expect(screen.getByLabelText('价格分满分')).toHaveValue('25');
    expect(screen.getByLabelText(/候选报价（最多 20 个）/)).toHaveValue('900');
  });

  it('还没有方案、招标文件也没写评标价办法：默认平均值法，可从常见办法开始，不发试算请求', async () => {
    backend(false);
    let calls = 0;
    server.use(
      http.post('/api/v1/projects/prj-1/price:simulate', () => {
        calls++;
        return HttpResponse.json(simulation());
      }),
    );
    renderApp('/projects/prj-1/price');
    expect(await screen.findByLabelText('价格分满分')).toHaveValue('');
    expect(screen.getByLabelText('取法')).toHaveValue('average');
    expect(
      screen.getByText('填好评标价规则和至少一个候选报价，这里自动试算。'),
    ).toBeInTheDocument();
    expect(await screen.findByText('还没有保存过。')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '去掉最高最低各 10% 后平均' }));
    expect(screen.getByLabelText('取法')).toHaveValue('trimmed_average');
    expect(screen.getByLabelText('去极值比例 %')).toHaveValue('10');
    expect(screen.getByLabelText('高于基准价每 1% 扣分')).toHaveValue('1');
    await new Promise((r) => setTimeout(r, 600));
    expect(calls).toBe(0);
  });

  it('招标文件写明了评标价办法：第一次打开就按原文填好，显示原文出处，可重新填入', async () => {
    backend(false);
    server.use(
      http.get('/api/v1/projects/prj-1/rules', () =>
        HttpResponse.json(
          ruleSet({
            terms: {
              technical_full_score: null,
              price_rule: {
                full_score: '30',
                above_deduct_per_pct: '1',
                below_deduct_per_pct: '0.5',
                method: 'average',
                coefficient: null,
                trim_pct: null,
                max_limit: null,
                abnormal_low_pct: null,
                quote: '价格分满分30分，高于基准价每1%扣1分，低于基准价每1%扣0.5分',
                evidence: [evidence({ evidence_id: 'evd-p', physical_page: 12 })],
              },
            },
          }),
        ),
      ),
    );
    renderApp('/projects/prj-1/price');
    expect(await screen.findByLabelText('价格分满分')).toHaveValue('30');
    expect(screen.getByLabelText('低于基准价每 1% 扣分')).toHaveValue('0.5');
    expect(screen.getByText(/已按招标文件填好评标价规则/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '第 12 页' })).toHaveAttribute(
      'href',
      '/projects/prj-1/evidence/evd-p',
    );
    const full = screen.getByLabelText('价格分满分');
    await userEvent.clear(full);
    await userEvent.type(full, '20');
    await userEvent.click(screen.getByRole('button', { name: '按招标文件重新填入' }));
    expect(full).toHaveValue('30');
  });
});
