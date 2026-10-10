import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { server } from '../../test/server';
import { ME, apiError, overview, project, renderApp } from '../../test/helpers';
import { validateProject } from './ProjectsPage';

const soon = new Date(Date.now() + 2 * 86_400_000).toISOString();

function auth() {
  server.use(http.get('/api/v1/me', () => HttpResponse.json(ME)));
}

const REVIEWED = overview(
  { deadline: soon },
  {
    reviewed: true,
    qualification_open: 2,
    prediction: {
      status: 'candidate',
      estimated_value: '6',
      low: '4',
      high: '8',
      maximum: '8',
      technical_full_score: '60',
      validation_status: 'not_validated',
      reason: '尚未校准',
    },
    next_action: {
      key: 'handle_disqualification',
      title: '处理 2 个可能被否决或不满足强制要求的问题',
      detail: '这类问题处理完之前不能登记提交。',
      target: 'findings',
      count: 2,
    },
  },
);

describe('项目总览', () => {
  it('每行给出否决风险、预计技术分（含覆盖程度）和与报告同源的下一步', async () => {
    auth();
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json([
          overview({
            project_id: 'prj-2',
            title: '老旧雨水管网更新',
            state: 'materials_pending',
            lot: null,
            region: null,
            engineering_type: null,
          }),
          REVIEWED,
          overview({ project_id: 'prj-3', title: '已归档项目', state: 'archived' }),
        ]),
      ),
    );
    renderApp('/projects');
    const list = await screen.findByRole('list', { name: '项目清单' });
    const rows = within(list).getAllByRole('listitem');
    // 有否决风险的排最前，已结束的排最后
    expect(rows[0]).toHaveTextContent('城市支路及排水改造');
    expect(rows[2]).toHaveTextContent('已归档项目');
    const first = within(rows[0]!);
    expect(first.getByText('2 个未处理')).toBeInTheDocument();
    expect(first.getByText(/4–8/)).toBeInTheDocument();
    expect(first.getByText('只覆盖 8 / 60 分')).toBeInTheDocument();
    expect(first.getByText(/还剩 2 天/)).toBeInTheDocument();
    expect(first.getByRole('link', { name: '处理否决风险' })).toHaveAttribute(
      'href',
      '/projects/prj-1/findings?category=disqualification',
    );
    const second = within(rows[1]!);
    expect(second.getAllByText('尚未评审')).toHaveLength(2);
    expect(second.getByText('未设截止时间')).toBeInTheDocument();
    expect(second.getByRole('link', { name: '上传资料' })).toHaveAttribute(
      'href',
      '/projects/prj-2/materials',
    );
    // 已结束的项目不派下一步
    expect(within(rows[2]!).getByRole('link', { name: '查看报告' })).toBeInTheDocument();
    expect(screen.getByText('2 个进行中，1 个有未处理的否决风险')).toBeInTheDocument();
  });

  it('项目设置为不显示分数时，总览也不显示分数', async () => {
    auth();
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json([
          {
            ...REVIEWED,
            settings: { ...REVIEWED.settings, show_score: false },
          },
        ]),
      ),
    );
    renderApp('/projects');
    const list = await screen.findByRole('list', { name: '项目清单' });
    expect(within(list).queryByText(/4–8/)).not.toBeInTheDocument();
  });

  it('只有一个实心主按钮：新建项目', async () => {
    auth();
    server.use(http.get('/api/v1/projects', () => HttpResponse.json([REVIEWED])));
    renderApp('/projects');
    await screen.findByRole('list', { name: '项目清单' });
    const primaries = document.querySelectorAll('[data-variant="primary"]');
    expect(primaries).toHaveLength(1);
    expect(primaries[0]).toHaveTextContent('新建项目');
  });

  it('无项目时说明能做什么，不展示示例数据', async () => {
    auth();
    server.use(http.get('/api/v1/projects', () => HttpResponse.json([])));
    renderApp('/projects');
    expect(await screen.findByText('建一个项目，上传招标文件和施组正文')).toBeInTheDocument();
  });

  it('503 可重试：显示中文说明与请求编号，点击重试后恢复', async () => {
    auth();
    let n = 0;
    server.use(
      http.get('/api/v1/projects', () => {
        n++;
        return n === 1
          ? HttpResponse.json(
              apiError('STORAGE_UNAVAILABLE', '依赖服务暂不可用，请稍后重试', {
                retryable: true,
                request_id: 'req-503',
              }),
              { status: 503 },
            )
          : HttpResponse.json([REVIEWED]);
      }),
    );
    renderApp('/projects');
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('依赖服务暂不可用');
    expect(alert).toHaveTextContent('req-503');
    await userEvent.click(within(alert).getByRole('button', { name: '重试' }));
    expect(await screen.findByRole('list', { name: '项目清单' })).toBeInTheDocument();
  });

  it('新建项目只要求名称；更多信息按需展开，空的选填项为 null', async () => {
    auth();
    let body: unknown = null;
    server.use(
      http.get('/api/v1/projects', () => HttpResponse.json([REVIEWED])),
      http.post('/api/v1/projects', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(project({ project_id: 'prj-new' }), { status: 201 });
      }),
      http.get('/api/v1/projects/prj-new', () =>
        HttpResponse.json(project({ project_id: 'prj-new' })),
      ),
    );
    renderApp('/projects');
    await userEvent.click(await screen.findByRole('button', { name: '新建项目' }));
    const dlg = screen.getByRole('dialog', { name: '新建项目' });
    await userEvent.click(within(dlg).getByRole('button', { name: '建立并上传资料' }));
    expect(within(dlg).getByText('请填写项目名称')).toBeInTheDocument();
    expect(within(dlg).queryByLabelText('标段（选填）')).not.toBeInTheDocument();
    await userEvent.type(within(dlg).getByLabelText('项目名称'), '滨江大道');
    await userEvent.click(within(dlg).getByRole('button', { name: /更多信息/ }));
    await userEvent.type(within(dlg).getByLabelText('标段（选填）'), '二标段');
    await userEvent.click(within(dlg).getByRole('button', { name: '建立并上传资料' }));
    expect(await screen.findByRole('heading', { name: '资料' })).toBeInTheDocument();
    expect(body).toEqual({
      title: '滨江大道',
      tender_number: null,
      lot: '二标段',
      region: null,
      engineering_type: null,
      deadline: null,
    });
  });

  it('Esc 关闭对话框，焦点回到触发按钮', async () => {
    auth();
    server.use(http.get('/api/v1/projects', () => HttpResponse.json([REVIEWED])));
    renderApp('/projects');
    const btn = await screen.findByRole('button', { name: '新建项目' });
    await userEvent.click(btn);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(btn).toHaveFocus();
  });
});

describe('validateProject', () => {
  it('只有名称必填；截止时间填了就要合法', () => {
    const empty = {
      title: '',
      tender_number: '',
      lot: '',
      region: '',
      engineering_type: '',
      deadline: '',
    };
    expect(Object.keys(validateProject({ ...empty, title: ' ' }))).toEqual(['title']);
    expect(validateProject({ ...empty, title: 'a' })).toEqual({});
  });
});
