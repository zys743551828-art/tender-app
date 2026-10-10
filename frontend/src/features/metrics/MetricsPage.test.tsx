import { screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { formatRate } from '../../lib/format';
import { metrics } from '../../test/fixtures';
import { ME, apiError, renderApp } from '../../test/helpers';
import { server } from '../../test/server';

function backend(m = metrics()) {
  server.use(
    http.get('/api/v1/me', () => HttpResponse.json(ME)),
    http.get('/api/v1/projects', () => HttpResponse.json([])),
    http.get('/api/v1/metrics', () => HttpResponse.json(m)),
  );
}

describe('度量页', () => {
  it('结果：提交数、已出结果数、入围率与中标率，条形图有文字描述', async () => {
    backend();
    renderApp('/metrics');
    const section = within(
      (await screen.findByRole('heading', { name: '结果' })).closest('section')!,
    );
    expect(section.getByText('已提交').nextSibling).toHaveTextContent('4');
    expect(section.getByText('入围率').nextSibling).toHaveTextContent('66.7%');
    expect(section.getByText('中标率').nextSibling).toHaveTextContent('50%');
    expect(
      section.getByRole('img', { name: /入围 2，不入围 1，被否决 0，中标 1，未中标 1/ }),
    ).toBeInTheDocument();
  });

  it('还没有登记过提交：说明数字从哪里来，不画空图表', async () => {
    backend(
      metrics({
        outcomes: {
          submissions: 0,
          decided: 0,
          shortlisted: 0,
          not_shortlisted: 0,
          rejected: 0,
          awarded: 0,
          not_awarded: 0,
          shortlist_rate: null,
          award_rate: null,
        },
        trends: [],
      }),
    );
    renderApp('/metrics');
    expect(await screen.findByText('登记过提交和开标结果后，这里才有数字')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '结果' })).not.toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('已提交但还没出结果时比率显示“暂无”，不用 0 代替', async () => {
    backend(
      metrics({
        outcomes: {
          submissions: 2,
          decided: 0,
          shortlisted: 0,
          not_shortlisted: 0,
          rejected: 0,
          awarded: 0,
          not_awarded: 0,
          shortlist_rate: null,
          award_rate: null,
        },
      }),
    );
    renderApp('/metrics');
    const section = within(
      (await screen.findByRole('heading', { name: '结果' })).closest('section')!,
    );
    expect(section.getByText('入围率').nextSibling).toHaveTextContent('暂无');
    expect(section.getByText('中标率').nextSibling).toHaveTextContent('暂无');
  });

  it('废标／否决风险闭环：发现、提交前处理、提交时未处理、招标方实际否决', async () => {
    backend();
    renderApp('/metrics');
    expect(
      await screen.findByRole('img', {
        name: '废标风险闭环：评审发现 6，提交前已解决或驳回 5，提交时仍未处理 1，招标方实际否决 0',
      }),
    ).toBeInTheDocument();
  });

  it('预测校准：样本不足时说明不给误差并显示进度', async () => {
    backend();
    renderApp('/metrics');
    const section = within(
      (await screen.findByRole('heading', { name: '预测校准' })).closest('section')!,
    );
    expect(section.getByText(/攒到 20 组才能给出误差/)).toBeInTheDocument();
    expect(section.getByRole('progressbar', { name: '对照样本 3 / 20' })).toHaveAttribute(
      'aria-valuenow',
      '15',
    );
  });

  it('逐轮趋势：折线图与同样内容的数据表；没有评审的项目不出现', async () => {
    backend();
    renderApp('/metrics');
    const section = within(
      (await screen.findByRole('heading', { name: '逐轮整改与预测得分' })).closest('section')!,
    );
    expect(
      section.getByRole('img', { name: /逐轮预测得分估计，满分 100，实际技术分 78/ }),
    ).toBeInTheDocument();
    const table = section.getByRole('table', { name: /逐轮数据/ });
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows.map((r) => r.textContent)).toEqual(['第 1 轮65602', '第 2 轮74240']);
    expect(section.getByText(/实际技术分 78/, { selector: 'p' })).toBeInTheDocument();
  });

  it('没有趋势数据：不出现趋势区', async () => {
    backend(metrics({ trends: [] }));
    renderApp('/metrics');
    await screen.findByRole('heading', { name: '结果' });
    expect(screen.queryByRole('heading', { name: '逐轮整改与预测得分' })).not.toBeInTheDocument();
  });

  it('不展示耗时、工时之类的过程指标', async () => {
    backend();
    renderApp('/metrics');
    await screen.findByRole('heading', { name: '度量' });
    expect(screen.queryByText(/耗时|工时|人效/)).not.toBeInTheDocument();
  });

  it('读取失败：显示后端消息', async () => {
    server.use(
      http.get('/api/v1/me', () => HttpResponse.json(ME)),
      http.get('/api/v1/metrics', () =>
        HttpResponse.json(apiError('internal', '度量暂时不可用'), { status: 500 }),
      ),
    );
    renderApp('/metrics');
    expect(await screen.findByText('度量暂时不可用')).toBeInTheDocument();
  });

  it('入口：全局导航有“度量”', async () => {
    backend();
    renderApp('/projects');
    expect(await screen.findByRole('link', { name: '度量' })).toHaveAttribute('href', '/metrics');
  });
});

describe('formatRate', () => {
  it('0–1 比例 → 百分数', () => {
    expect(formatRate('0.5')).toBe('50%');
    expect(formatRate('0.6667')).toBe('66.7%');
    expect(formatRate('1')).toBe('100%');
    expect(formatRate(null)).toBe('暂无');
    expect(formatRate('x')).toBe('暂无');
  });
});
