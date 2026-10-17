import { describe, expect, it, vi } from 'vitest';
import { ApiClient, toPage } from './client';
import { ApiError, describeError } from './errors';

interface Call {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: string | undefined;
}

function mockFetch(responses: (Response | Error)[]) {
  const calls: Call[] = [];
  const fn = vi.fn((url: string, init?: RequestInit) => {
    calls.push({
      url,
      method: init?.method ?? 'GET',
      headers: { ...(init?.headers as Record<string, string>) },
      body: init?.body as string | undefined,
    });
    const r = responses.shift();
    if (!r) throw new Error('no more mocked responses');
    return r instanceof Error ? Promise.reject(r) : Promise.resolve(r);
  });
  return { fn: fn as unknown as typeof fetch, calls };
}

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });

const ME = { member_id: 'm1', display_name: '张工', csrf_token: 'tok-1' };

describe('ApiClient 请求头', () => {
  it('二进制上传在 CSRF 刷新后重传相同 Blob 和幂等键', async () => {
    const { fn, calls } = mockFetch([
      json({ code: 'csrf_failed', message: 'CSRF 已失效' }, 403),
      json(ME),
      new Response(null, { headers: { ETag: 'part-etag' } }),
    ]);
    const c = new ApiClient({ fetchImpl: fn });
    c.setCsrfToken('expired-token');
    const body = new Blob(['binary']);
    const response = await c.putBytes('/uploads/upl-1/parts/1', body, new AbortController().signal);
    expect(response.headers.get('ETag')).toBe('part-etag');
    expect(calls[0]?.body).toBe(body);
    expect(calls[2]?.body).toBe(body);
    expect(calls[2]?.headers['X-CSRF-Token']).toBe('tok-1');
    expect(calls[2]?.headers['Idempotency-Key']).toBe(calls[0]?.headers['Idempotency-Key']);
  });

  it('写请求带 X-CSRF-Token 与 Idempotency-Key，GET 两者都不带', async () => {
    const { fn, calls } = mockFetch([json({ ok: 1 }), json({ ok: 2 })]);
    const c = new ApiClient({ fetchImpl: fn });
    c.setCsrfToken('tok-1');
    await c.get('/projects');
    await c.post('/projects/p1/tasks', { a: 1 });
    expect(calls[0]?.url).toBe('/api/v1/projects');
    expect(calls[0]?.headers['X-CSRF-Token']).toBeUndefined();
    expect(calls[0]?.headers['Idempotency-Key']).toBeUndefined();
    expect(calls[1]?.headers['X-CSRF-Token']).toBe('tok-1');
    expect(calls[1]?.headers['Idempotency-Key']).toMatch(/^[0-9a-f-]{36}$/);
    expect(calls[1]?.headers['Content-Type']).toBe('application/json');
    expect(calls[1]?.body).toBe('{"a":1}');
  });

  it('每次动作生成新的幂等键；显式传入同一个键则复用', async () => {
    const { fn, calls } = mockFetch([json({}), json({}), json({})]);
    const c = new ApiClient({ fetchImpl: fn });
    c.setCsrfToken('t');
    await c.post('/x', {});
    await c.post('/x', {});
    await c.post('/x', {}, { idempotencyKey: 'fixed-key' });
    const k = calls.map((x) => x.headers['Idempotency-Key']);
    expect(k[0]).not.toBe(k[1]);
    expect(k[2]).toBe('fixed-key');
  });

  it('If-Match 以字符串发送；查询参数忽略空值', async () => {
    const { fn, calls } = mockFetch([json({}), json({})]);
    const c = new ApiClient({ fetchImpl: fn });
    c.setCsrfToken('t');
    await c.patch('/projects/p1', { title: 'x' }, { ifMatch: 7 });
    await c.get('/projects/p1/findings', { query: { cursor: undefined, limit: 25, q: '' } });
    expect(calls[0]?.headers['If-Match']).toBe('7');
    expect(calls[0]?.method).toBe('PATCH');
    expect(calls[1]?.url).toBe('/api/v1/projects/p1/findings?limit=25');
  });

  it('没有 CSRF 令牌时先取 /me 再发写请求（只取一次）', async () => {
    const { fn, calls } = mockFetch([json(ME), json({ done: true }), json({ done: true })]);
    const c = new ApiClient({ fetchImpl: fn });
    await c.post('/x', {});
    await c.post('/y', {});
    expect(calls.map((x) => x.url)).toEqual(['/api/v1/me', '/api/v1/x', '/api/v1/y']);
    expect(calls[1]?.headers['X-CSRF-Token']).toBe('tok-1');
  });

  it('登录请求不预取 /me（noCsrf）', async () => {
    const { fn, calls } = mockFetch([json(ME)]);
    const c = new ApiClient({ fetchImpl: fn });
    await c.post(
      '/auth/login',
      { username: 'a', password: 'b' },
      { noCsrf: true, skipAuthRedirect: true },
    );
    expect(calls).toHaveLength(1);
    expect(calls[0]?.headers['X-CSRF-Token']).toBeUndefined();
    expect(calls[0]?.headers['Idempotency-Key']).toBeTruthy();
  });

  it('CSRF 失效（403 CSRF_*）时刷新令牌并用同一幂等键重发一次', async () => {
    const { fn, calls } = mockFetch([
      json(
        {
          code: 'CSRF_INVALID',
          message: '令牌失效',
          request_id: 'r1',
          retryable: false,
          details: {},
        },
        403,
      ),
      json({ ...ME, csrf_token: 'tok-2' }),
      json({ ok: true }),
    ]);
    const c = new ApiClient({ fetchImpl: fn });
    c.setCsrfToken('old');
    await expect(c.post('/x', {})).resolves.toEqual({ ok: true });
    expect(calls[2]?.headers['X-CSRF-Token']).toBe('tok-2');
    expect(calls[2]?.headers['Idempotency-Key']).toBe(calls[0]?.headers['Idempotency-Key']);
  });
});

describe('ApiClient 错误映射', () => {
  const err = (status: number, code: string, message: string, retryable = false) =>
    json({ code, message, request_id: 'req-9', retryable, details: { f: 1 } }, status);

  it('按契约 Error 结构生成 ApiError，保留 message / request_id / details', async () => {
    const { fn } = mockFetch([err(422, 'INVALID_CONTRACT', '分值不能大于满分')]);
    const c = new ApiClient({ fetchImpl: fn });
    const e = await c.get('/x').catch((x: unknown) => x);
    expect(e).toBeInstanceOf(ApiError);
    const a = e as ApiError;
    expect(a.kind).toBe('validation');
    expect(a.message).toBe('分值不能大于满分');
    expect(a.requestId).toBe('req-9');
    expect(a.details).toEqual({ f: 1 });
    expect(a.retryable).toBe(false);
  });

  it('412 STALE_VERSION 归为 stale（不区分大小写）并提示保留输入', async () => {
    const { fn } = mockFetch([err(412, 'stale_version', '对象已被他人修改')]);
    const c = new ApiClient({ fetchImpl: fn });
    c.setCsrfToken('t');
    const e = (await c
      .patch('/projects/p', {}, { ifMatch: 1 })
      .catch((x: unknown) => x)) as ApiError;
    expect(e.kind).toBe('stale');
    expect(e.is('STALE_VERSION')).toBe(true);
    expect(describeError(e).message).toContain('已保留');
  });

  it('503 retryable 提供重试；429 同样可重试；网络失败归为 unavailable', async () => {
    const { fn } = mockFetch([
      err(503, 'STORAGE_UNAVAILABLE', '存储暂不可用', true),
      err(429, 'BUDGET_LIMIT', '额度已满', true),
      new TypeError('Failed to fetch'),
    ]);
    const c = new ApiClient({ fetchImpl: fn });
    const a = (await c.get('/a').catch((x: unknown) => x)) as ApiError;
    const b = (await c.get('/b').catch((x: unknown) => x)) as ApiError;
    const n = (await c.get('/c').catch((x: unknown) => x)) as ApiError;
    expect([a.kind, a.retryable]).toEqual(['unavailable', true]);
    expect([b.kind, b.retryable]).toEqual(['rate_limit', true]);
    expect([n.kind, n.code, n.retryable]).toEqual(['unavailable', 'NETWORK_ERROR', true]);
  });

  it('响应体不是契约结构（如网关 HTML）时给中文兜底，不泄漏原文，并读取 X-Request-ID', async () => {
    const { fn } = mockFetch([
      new Response('<html>Bad Gateway</html>', {
        status: 502,
        headers: { 'Content-Type': 'text/html', 'X-Request-ID': 'gw-1' },
      }),
    ]);
    const c = new ApiClient({ fetchImpl: fn });
    const e = (await c.get('/x').catch((x: unknown) => x)) as ApiError;
    expect(e.message).toBe('服务暂时不可用，请稍后重试');
    expect(e.message).not.toContain('html');
    expect(e.requestId).toBe('gw-1');
    expect(e.retryable).toBe(true);
  });

  it('401 触发 onUnauthorized 并清空 CSRF；skipAuthRedirect 时不触发', async () => {
    const { fn } = mockFetch([
      err(401, 'AUTH_REQUIRED', '请先登录'),
      err(401, 'AUTH_REQUIRED', '账号或密码不正确'),
    ]);
    const onUnauthorized = vi.fn();
    const c = new ApiClient({ fetchImpl: fn, onUnauthorized });
    c.setCsrfToken('t');
    await c.get('/projects').catch(() => undefined);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    expect(c.hasCsrfToken).toBe(false);
    await c.get('/me', { skipAuthRedirect: true }).catch(() => undefined);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it('204 无响应体返回 undefined', async () => {
    const { fn } = mockFetch([new Response(null, { status: 204 })]);
    const c = new ApiClient({ fetchImpl: fn });
    c.setCsrfToken('t');
    await expect(c.post('/auth/logout')).resolves.toBeUndefined();
  });
});

describe('toPage', () => {
  it('把 {items,next_cursor} 转成分页结果', () => {
    expect(toPage({ items: [1], next_cursor: 'c2' })).toEqual({ items: [1], nextCursor: 'c2' });
    expect(toPage({ items: [1], next_cursor: null }).nextCursor).toBeNull();
  });
});
