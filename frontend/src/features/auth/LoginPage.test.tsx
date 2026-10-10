import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { server } from '../../test/server';
import { ME, apiError, overview, renderApp } from '../../test/helpers';

describe('登录页', () => {
  it('未登录访问受保护页面时跳到登录页，并带回原路径', async () => {
    server.use(
      http.get('/api/v1/me', () =>
        HttpResponse.json(apiError('AUTH_REQUIRED', '请先登录'), { status: 401 }),
      ),
    );
    renderApp('/projects/prj-1/findings');
    expect(await screen.findByRole('heading', { name: '登录' })).toBeInTheDocument();
    expect(screen.getByLabelText('账号')).toBeInTheDocument();
  });

  it('空表单提交显示字段错误，不发请求', async () => {
    let posted = false;
    server.use(
      http.get('/api/v1/me', () =>
        HttpResponse.json(apiError('AUTH_REQUIRED', '请先登录'), { status: 401 }),
      ),
      http.post('/api/v1/auth/login', () => {
        posted = true;
        return HttpResponse.json(ME);
      }),
    );
    renderApp('/login');
    await userEvent.click(await screen.findByRole('button', { name: '登录' }));
    expect(await screen.findByText('请输入账号')).toBeInTheDocument();
    expect(screen.getByText('请输入密码')).toBeInTheDocument();
    expect(screen.getByLabelText('账号')).toHaveAttribute('aria-invalid', 'true');
    expect(posted).toBe(false);
  });

  it('登录失败显示后端中文说明与请求编号，且不清空账号', async () => {
    server.use(
      http.get('/api/v1/me', () =>
        HttpResponse.json(apiError('AUTH_REQUIRED', '请先登录'), { status: 401 }),
      ),
      http.post('/api/v1/auth/login', () =>
        HttpResponse.json(
          apiError('AUTH_REQUIRED', '账号或密码不正确', { request_id: 'req-login-9' }),
          { status: 401 },
        ),
      ),
    );
    renderApp('/login');
    await userEvent.type(await screen.findByLabelText('账号'), 'zhang');
    await userEvent.type(screen.getByLabelText('密码'), 'wrong');
    await userEvent.click(screen.getByRole('button', { name: '登录' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('账号或密码不正确');
    expect(screen.getByRole('alert')).toHaveTextContent('请求编号 req-login-9');
    expect(screen.getByLabelText('账号')).toHaveValue('zhang');
  });

  it('登录成功：请求体为 {username,password}，带幂等键、不带 CSRF，随后进入项目列表', async () => {
    let loggedIn = false;
    let seen: { body: unknown; idem: string | null; csrf: string | null } | null = null;
    server.use(
      http.get('/api/v1/me', () =>
        loggedIn
          ? HttpResponse.json(ME)
          : HttpResponse.json(apiError('AUTH_REQUIRED', '请先登录'), { status: 401 }),
      ),
      http.post('/api/v1/auth/login', async ({ request }) => {
        seen = {
          body: await request.json(),
          idem: request.headers.get('Idempotency-Key'),
          csrf: request.headers.get('X-CSRF-Token'),
        };
        loggedIn = true;
        return HttpResponse.json(ME);
      }),
      http.get('/api/v1/projects', () => HttpResponse.json([overview()])),
    );
    renderApp('/login');
    await userEvent.type(await screen.findByLabelText('账号'), ' zhang ');
    await userEvent.type(screen.getByLabelText('密码'), 'secret');
    await userEvent.click(screen.getByRole('button', { name: '登录' }));
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: '项目' })).toBeInTheDocument();
    });
    expect(seen).toEqual({
      body: { username: 'zhang', password: 'secret' },
      idem: expect.any(String),
      csrf: null,
    });
    expect(screen.getByText('张工')).toBeInTheDocument();
  });
});
