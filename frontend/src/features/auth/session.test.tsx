import { screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { ME, apiError, project, renderAppWithClient } from '../../test/helpers';
import { server } from '../../test/server';

describe('会话失效', () => {
  it('任意接口 401：清空整个查询缓存（不留上一位用户的项目数据），回到登录页', async () => {
    let expired = false;
    server.use(
      http.get('/api/v1/me', () =>
        expired
          ? HttpResponse.json(apiError('AUTH_REQUIRED', '请先登录'), { status: 401 })
          : HttpResponse.json(ME),
      ),
      http.get('/api/v1/projects/prj-1', () =>
        expired
          ? HttpResponse.json(apiError('AUTH_REQUIRED', '请先登录'), { status: 401 })
          : HttpResponse.json(project()),
      ),
      http.get('/api/v1/projects/prj-1/files', () => HttpResponse.json([])),
      http.get('/api/v1/projects/prj-1/tasks', () => HttpResponse.json([])),
    );
    const { qc } = renderAppWithClient('/projects/prj-1/materials');
    await screen.findByRole('heading', { name: '资料' });
    expect(qc.getQueryData(['projects', 'prj-1'])).toBeDefined();

    // 另一个项目里缓存着的数据（例如上一位用户看过的问题列表）
    qc.setQueryData(['projects', 'prj-9', 'findings'], { pages: [] });
    expired = true;
    await qc.invalidateQueries({ queryKey: ['projects', 'prj-1'], exact: true });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /登录/ })).toBeInTheDocument();
    });
    expect(qc.getQueryData(['projects', 'prj-1'])).toBeUndefined();
    expect(qc.getQueryData(['projects', 'prj-9', 'findings'])).toBeUndefined();
  });
});
