import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { ME, apiError, project, renderApp } from '../../test/helpers';
import { server } from '../../test/server';
import { diffProject } from './SettingsPage';

function backend(get: () => ReturnType<typeof project>) {
  server.use(
    http.get('/api/v1/me', () => HttpResponse.json(ME)),
    http.get('/api/v1/projects/prj-1', () => HttpResponse.json(get())),
  );
}

describe('diffProject', () => {
  const base = {
    title: 'A',
    tender_number: '',
    lot: '一标段',
    region: '上海',
    engineering_type: '市政',
    deadline: '',
  };
  it('只返回改过的字段；清空可选字段为 null', () => {
    expect(diffProject(base, {})).toEqual({});
    expect(diffProject(base, { title: ' B ', lot: '' })).toEqual({ title: 'B', lot: null });
    expect(diffProject({ ...base, tender_number: 'X' }, { tender_number: '' })).toEqual({
      tender_number: null,
    });
  });
});

describe('进入设置页时重新读取项目', () => {
  it('挂载后再取一次项目，避免用过期 revision 提交', async () => {
    let gets = 0;
    backend(() => {
      gets++;
      return project({ revision: 3 + gets });
    });
    renderApp('/projects/prj-1/settings');
    await screen.findByRole('heading', { level: 1 });
    await waitFor(() => {
      expect(gets).toBeGreaterThanOrEqual(2);
    });
  });
});

describe('项目设置', () => {
  it('保存：If-Match 为当前 revision，只发改动字段，成功后刷新显示', async () => {
    let current = project({ revision: 3 });
    backend(() => current);
    let seen: { body: unknown; ifMatch: string | null } | null = null;
    server.use(
      http.patch('/api/v1/projects/prj-1', async ({ request }) => {
        seen = { body: await request.json(), ifMatch: request.headers.get('If-Match') };
        current = { ...current, title: '新名称', revision: 4 };
        return HttpResponse.json(current);
      }),
    );
    renderApp('/projects/prj-1/settings');
    const title = await screen.findByLabelText('项目名称');
    const save = screen.getByRole('button', { name: '保存修改' });
    expect(save).toBeDisabled();
    await userEvent.clear(title);
    await userEvent.type(title, '新名称');
    await userEvent.click(save);
    expect(await screen.findByText('没有修改。')).toBeInTheDocument();
    expect(seen).toEqual({ body: { title: '新名称' }, ifMatch: '3' });
    expect(screen.getByLabelText('项目名称')).toHaveValue('新名称');
  });

  it('必填项为空：不发请求并提示', async () => {
    backend(() => project());
    let called = false;
    server.use(
      http.patch('/api/v1/projects/prj-1', () => {
        called = true;
        return HttpResponse.json(project());
      }),
    );
    renderApp('/projects/prj-1/settings');
    await userEvent.clear(await screen.findByLabelText('项目名称'));
    await userEvent.click(screen.getByRole('button', { name: '保存修改' }));
    expect(await screen.findByText('请填写项目名称')).toBeInTheDocument();
    expect(called).toBe(false);
  });

  it('412：提示被他人修改并保留输入；载入最新版本后用新 revision 重新保存', async () => {
    let current = project({ revision: 3, region: '上海' });
    backend(() => current);
    const ifMatches: (string | null)[] = [];
    server.use(
      http.patch('/api/v1/projects/prj-1', ({ request }) => {
        const im = request.headers.get('If-Match');
        ifMatches.push(im);
        if (im !== String(current.revision))
          return HttpResponse.json(apiError('stale_version', '项目已被他人修改，请刷新后重试'), {
            status: 412,
          });
        current = { ...current, title: '我的名称', revision: current.revision + 1 };
        return HttpResponse.json(current);
      }),
    );
    renderApp('/projects/prj-1/settings');
    const title = await screen.findByLabelText('项目名称');
    await userEvent.clear(title);
    await userEvent.type(title, '我的名称');
    // 他人在此期间改了地区并抬高了 revision
    current = { ...current, region: '苏州', revision: 4 };
    await userEvent.click(screen.getByRole('button', { name: '保存修改' }));
    expect(await screen.findByText('项目已被他人修改')).toBeInTheDocument();
    expect(screen.getByLabelText('项目名称')).toHaveValue('我的名称');

    await userEvent.click(screen.getByRole('button', { name: '载入最新版本' }));
    // 未改动的字段更新为最新值，改过的保留
    expect(await screen.findByDisplayValue('苏州')).toBeInTheDocument();
    expect(screen.getByLabelText('项目名称')).toHaveValue('我的名称');
    await userEvent.click(screen.getByRole('button', { name: '保存修改' }));
    expect(await screen.findByText('没有修改。')).toBeInTheDocument();
    expect(ifMatches).toEqual(['3', '4']);
  });

  it('409 等其他后端错误：显示后端中文消息', async () => {
    backend(() => project());
    server.use(
      http.patch('/api/v1/projects/prj-1', () =>
        HttpResponse.json(apiError('empty_update', '没有可更新的字段'), { status: 409 }),
      ),
    );
    renderApp('/projects/prj-1/settings');
    const title = await screen.findByLabelText('项目名称');
    await userEvent.type(title, '2');
    await userEvent.click(screen.getByRole('button', { name: '保存修改' }));
    expect(await screen.findByText('没有可更新的字段')).toBeInTheDocument();
    expect(screen.getByText('项目信息未保存')).toBeInTheDocument();
  });
});

describe('功能开关', () => {
  it('默认全开（规则按原文接受除外）；改动后整体提交 settings，带当前 revision', async () => {
    let current = project({ revision: 5 });
    backend(() => current);
    let seen: { body: unknown; ifMatch: string | null } | null = null;
    server.use(
      http.patch('/api/v1/projects/prj-1', async ({ request }) => {
        const body = (await request.json()) as { settings: typeof current.settings };
        seen = { body, ifMatch: request.headers.get('If-Match') };
        current = { ...current, settings: body.settings, revision: 6 };
        return HttpResponse.json(current);
      }),
    );
    renderApp('/projects/prj-1/settings');
    const price = await screen.findByRole('checkbox', { name: /报价模块/ });
    expect(price).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /规则按原文接受/ })).not.toBeChecked();
    const save = screen.getByRole('button', { name: '保存开关' });
    expect(save).toBeDisabled();
    await userEvent.click(price);
    await userEvent.click(screen.getByRole('checkbox', { name: /显示预测分数/ }));
    expect(screen.getByText('将修改：显示预测分数、报价模块')).toBeInTheDocument();
    await userEvent.click(save);
    expect(await screen.findByText('开关没有改动。')).toBeInTheDocument();
    expect(seen).toEqual({
      body: { settings: { ...project().settings, price: false, show_score: false } },
      ifMatch: '5',
    });
    // 关闭报价后导航里不再出现“报价”
    expect(screen.queryByRole('link', { name: '报价' })).not.toBeInTheDocument();
  });

  it('报价模块关闭时报价页给出说明和去设置的入口', async () => {
    backend(() => project({ settings: { ...project().settings, price: false } }));
    renderApp('/projects/prj-1/price');
    expect(await screen.findByText('本项目关闭了报价模块')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '去项目设置' })).toHaveAttribute(
      'href',
      '/projects/prj-1/settings',
    );
  });
});
