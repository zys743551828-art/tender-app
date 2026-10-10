import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { ME, overview, project, renderApp } from '../test/helpers';
import { server } from '../test/server';

function backend() {
  server.use(
    http.get('/api/v1/me', () => HttpResponse.json(ME)),
    http.get('/api/v1/projects', () => HttpResponse.json([overview()])),
    http.get('/api/v1/projects/prj-1', () => HttpResponse.json(project())),
  );
}

describe('导航与路由', () => {
  it('项目内导航：报告、问题、依据、报价、提交与结果、资料；工具：检索、设置', async () => {
    backend();
    renderApp('/projects/prj-1');
    const nav = within(await screen.findByRole('navigation', { name: '项目导航' }));
    expect(nav.getAllByRole('link').map((a) => a.textContent)).toEqual([
      '报告',
      '问题',
      '依据',
      '报价',
      '提交与结果',
      '资料',
    ]);
    const tools = within(screen.getByRole('navigation', { name: '项目工具' }));
    expect(tools.getAllByRole('link').map((a) => a.textContent)).toEqual(['检索', '设置']);
    // 报告是落地页：只有它高亮
    expect(nav.getByRole('link', { name: '报告' })).toHaveAttribute('aria-current', 'page');
    expect(nav.getByRole('link', { name: '问题' })).not.toHaveAttribute('aria-current');
  });

  it('未知地址落到“页面不存在”', async () => {
    backend();
    renderApp('/projects/prj-1/no-such-page');
    expect(await screen.findByRole('heading', { name: '页面不存在' })).toBeInTheDocument();
  });

  it('依据页的标签可用键盘切换，地址带 tab 参数时直接打开事实库', async () => {
    backend();
    server.use(
      http.get('/api/v1/projects/prj-1/rules', () =>
        HttpResponse.json({
          rule_set_id: 'rls-1',
          project_id: 'prj-1',
          source_version_ids: [],
          status: 'candidate',
          revision: 1,
          rules: [],
          terms: { technical_full_score: null, price_rule: null },
        }),
      ),
    );
    renderApp('/projects/prj-1/basis');
    const rulesTab = await screen.findByRole('tab', { name: '规则' });
    rulesTab.focus();
    await userEvent.keyboard('{ArrowRight}');
    // Radix 的方向键在下一拍移动焦点并激活
    await waitFor(() => {
      expect(screen.getByRole('tab', { name: '事实库' })).toHaveAttribute('aria-selected', 'true');
    });
    expect(await screen.findByText('还没有录入事实')).toBeInTheDocument();
  });

  it('提交与结果页有“提交登记”“开标结果”两个标签', async () => {
    backend();
    renderApp('/projects/prj-1/submit?tab=outcomes');
    expect(await screen.findByRole('tab', { name: '开标结果' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(screen.getByRole('tab', { name: '提交登记' })).toBeInTheDocument();
  });
});
