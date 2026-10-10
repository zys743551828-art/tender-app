import { describe, expect, it, vi } from 'vitest';
import { ApiClient } from './client';
import { createEndpoints } from './endpoints';

interface Call {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: string | undefined;
}

function setup(body: unknown, status = 200) {
  const calls: Call[] = [];
  const fn = vi.fn((url: string, init?: RequestInit) => {
    calls.push({
      url,
      method: init?.method ?? 'GET',
      headers: { ...(init?.headers as Record<string, string>) },
      body: init?.body as string | undefined,
    });
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
  });
  const c = new ApiClient({ fetchImpl: fn as unknown as typeof fetch });
  c.setCsrfToken('tok');
  return { api: createEndpoints(c), calls };
}

describe('列表接口：后端直接返回数组', () => {
  it.each([
    [
      'tasks.list',
      '/api/v1/projects/p1/tasks',
      (a: ReturnType<typeof createEndpoints>) => a.tasks.list('p1'),
    ],
    [
      'submissions.list',
      '/api/v1/projects/p1/submissions',
      (a: ReturnType<typeof createEndpoints>) => a.submissions.list('p1'),
    ],
    [
      'outcomes.list',
      '/api/v1/projects/p1/outcomes',
      (a: ReturnType<typeof createEndpoints>) => a.outcomes.list('p1'),
    ],
    [
      'revisions.list',
      '/api/v1/projects/p1/revisions',
      (a: ReturnType<typeof createEndpoints>) => a.revisions.list('p1'),
    ],
    [
      'files.list',
      '/api/v1/projects/p1/files',
      (a: ReturnType<typeof createEndpoints>) => a.files.list('p1'),
    ],
    [
      'projects.list',
      '/api/v1/projects',
      (a: ReturnType<typeof createEndpoints>) => a.projects.list(),
    ],
  ])('%s 请求 GET %s 并原样返回数组', async (_n, url, call) => {
    const rows = [{ id: 1 }, { id: 2 }];
    const { api, calls } = setup(rows);
    await expect(call(api)).resolves.toEqual(rows);
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({ method: 'GET', url });
  });

  it('问题列表是 {items, next_cursor} 信封，转成 Page', async () => {
    const { api, calls } = setup({ items: [{ finding_id: 'f1' }], next_cursor: 'c2' });
    const page = await api.findings.list('p1', { cursor: 'c1', limit: 10 });
    expect(page).toEqual({ items: [{ finding_id: 'f1' }], nextCursor: 'c2' });
    expect(calls[0]?.url).toBe('/api/v1/projects/p1/findings?cursor=c1&limit=10');
  });
});

describe('任务发起接口', () => {
  it('pipeline.restart：POST /analysis，无请求体，带幂等键与 CSRF', async () => {
    const { api, calls } = setup({ stage: 'running' }, 202);
    await api.pipeline.restart('p1', { idempotencyKey: 'k-2' });
    expect(calls[0]).toMatchObject({
      method: 'POST',
      url: '/api/v1/projects/p1/analysis',
      body: undefined,
    });
    expect(calls[0]?.headers['Idempotency-Key']).toBe('k-2');
    expect(calls[0]?.headers['X-CSRF-Token']).toBe('tok');
  });

  it('revisions.propose 返回任务，请求体为 RevisionRequest', async () => {
    const { api, calls } = setup({ task_id: 't2', kind: 'revision' }, 202);
    const t = await api.revisions.propose('p1', {
      base_version_id: 'v1',
      snapshot_id: 's1',
      finding_ids: ['f1'],
      allowed_fact_ids: [],
      scope: '第 5 章',
    });
    expect(t.task_id).toBe('t2');
    expect(calls[0]).toMatchObject({ method: 'POST', url: '/api/v1/projects/p1/revisions' });
    expect(JSON.parse(calls[0]?.body ?? '')).toEqual({
      base_version_id: 'v1',
      snapshot_id: 's1',
      finding_ids: ['f1'],
      allowed_fact_ids: [],
      scope: '第 5 章',
    });
  });
});

describe('改稿建议的采纳与驳回', () => {
  it('adopt：不带 If-Match，edited_diff_artifact_id 为 null', async () => {
    const { api, calls } = setup({ revision_id: 'r1' });
    await api.revisions.adopt('r1', { base_version_id: 'v1', edited_diff_artifact_id: null });
    expect(calls[0]).toMatchObject({ method: 'POST', url: '/api/v1/revisions/r1/adopt' });
    expect(calls[0]?.headers['If-Match']).toBeUndefined();
    expect(JSON.parse(calls[0]?.body ?? '')).toEqual({
      base_version_id: 'v1',
      edited_diff_artifact_id: null,
    });
  });

  it('reject：请求体为 base_version_id 与 reason', async () => {
    const { api, calls } = setup({ revision_id: 'r1' });
    await api.revisions.reject('r1', { base_version_id: 'v1', reason: '范围不对' });
    expect(calls[0]).toMatchObject({ method: 'POST', url: '/api/v1/revisions/r1/reject' });
    expect(calls[0]?.headers['If-Match']).toBeUndefined();
    expect(JSON.parse(calls[0]?.body ?? '')).toEqual({
      base_version_id: 'v1',
      reason: '范围不对',
    });
  });
});

describe('改稿差异', () => {
  it('revisions.diff：GET /revisions/{id}/diff', async () => {
    const diff = { edits: [], dropped: [] };
    const { api, calls } = setup(diff);
    await expect(api.revisions.diff('r1')).resolves.toEqual(diff);
    expect(calls[0]).toMatchObject({ method: 'GET', url: '/api/v1/revisions/r1/diff' });
  });
});

describe('任务取消与重试', () => {
  it('POST /tasks/{id}/cancel 与 /retry 无请求体', async () => {
    const { api, calls } = setup({ task_id: 't1' }, 202);
    await api.tasks.cancel('t1');
    await api.tasks.retry('t1');
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      'POST /api/v1/tasks/t1/cancel',
      'POST /api/v1/tasks/t1/retry',
    ]);
    expect(calls.every((c) => c.body === undefined)).toBe(true);
  });
});

describe('事实', () => {
  it('facts.list 为 GET；facts.add 为带幂等键与 CSRF 的 POST', async () => {
    const { api, calls } = setup({ fact_set_id: null, items: [] });
    await api.facts.list('p1');
    await api.facts.add(
      'p1',
      {
        name: 'n',
        subject: 's',
        scope: 'c',
        value_decimal: null,
        unit: null,
        statement: 't',
        evidence_ids: ['evd-1'],
      },
      { idempotencyKey: 'k1' },
    );
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      'GET /api/v1/projects/p1/facts',
      'POST /api/v1/projects/p1/facts',
    ]);
    const post = calls[1];
    expect(post?.headers['Idempotency-Key']).toBe('k1');
    expect(post?.headers['X-CSRF-Token']).toBe('tok');
    expect(JSON.parse(post?.body ?? '{}')).toMatchObject({ evidence_ids: ['evd-1'] });
  });

  it('facts.withdraw：POST /facts/{id}/withdraw，body 为 {reason}，带幂等键与 CSRF', async () => {
    const { api, calls } = setup({ fact_set_id: 'fct-3', fact_id: 'fai-1', item_count: 0 });
    await api.facts.withdraw('p1', 'fai-1', { reason: '录错了' }, { idempotencyKey: 'k2' });
    expect(`${calls[0]?.method} ${calls[0]?.url}`).toBe(
      'POST /api/v1/projects/p1/facts/fai-1/withdraw',
    );
    expect(calls[0]?.headers['Idempotency-Key']).toBe('k2');
    expect(calls[0]?.headers['X-CSRF-Token']).toBe('tok');
    expect(JSON.parse(calls[0]?.body ?? '{}')).toEqual({ reason: '录错了' });
  });
});

describe('项目编辑、规则确认与证据检索', () => {
  it('projects.update：PATCH 带 If-Match 与只含改动字段的请求体', async () => {
    const { api, calls } = setup({ project_id: 'p1' });
    await api.projects.update('p1', 3, { title: '新名称' }, { idempotencyKey: 'k-1' });
    expect(calls[0]).toMatchObject({ method: 'PATCH', url: '/api/v1/projects/p1' });
    expect(calls[0]?.headers['If-Match']).toBe('3');
    expect(calls[0]?.headers['Idempotency-Key']).toBe('k-1');
    expect(JSON.parse(calls[0]?.body ?? '')).toEqual({ title: '新名称' });
  });

  it('rules.confirmPending：POST /projects/{id}/rules:confirm，请求体含规则包版本与规则 ID', async () => {
    const { api, calls } = setup({ confirmed: 2, skipped: 0 });
    await api.rules.confirmPending('p1', { object_version: '3', rule_ids: ['r1', 'r2'] });
    expect(calls[0]).toMatchObject({ method: 'POST', url: '/api/v1/projects/p1/rules:confirm' });
    expect(JSON.parse(calls[0]?.body ?? '')).toEqual({
      object_version: '3',
      rule_ids: ['r1', 'r2'],
    });
  });

  it('evidence.search 走 POST /projects/{id}/search；evidence.get 走 GET /evidence/{id}', async () => {
    const { api, calls } = setup({ hits: [] });
    await api.evidence.search('p1', {
      snapshot_id: 's1',
      query: '工期',
      top_k: 5,
      mode: 'keyword',
    });
    await api.evidence.get('e1');
    expect(calls[0]).toMatchObject({ method: 'POST', url: '/api/v1/projects/p1/search' });
    expect(JSON.parse(calls[0]?.body ?? '')).toEqual({
      snapshot_id: 's1',
      query: '工期',
      top_k: 5,
      mode: 'keyword',
    });
    expect(calls[1]).toMatchObject({ method: 'GET', url: '/api/v1/evidence/e1' });
  });
});

describe('评审报告、报价与度量接口', () => {
  it('findings.list 带 category、snapshot_id、status 与游标参数', async () => {
    const { api, calls } = setup({ items: [], next_cursor: null });
    await api.findings.list('p1', { snapshotId: 's1', status: 'candidate', category: 'scope' });
    const url = new URL(calls[0]?.url ?? '', 'http://x');
    expect(url.pathname).toBe('/api/v1/projects/p1/findings');
    expect(Object.fromEntries(url.searchParams)).toEqual({
      limit: '25',
      snapshot_id: 's1',
      status: 'candidate',
      category: 'scope',
    });
  });

  it('report.get / pipeline.get / metrics.get 都是 GET', async () => {
    const { api, calls } = setup({});
    await api.report.get('p1');
    await api.pipeline.get('p1');
    await api.metrics.get();
    expect(calls.map((c) => [c.method, c.url])).toEqual([
      ['GET', '/api/v1/projects/p1/report'],
      ['GET', '/api/v1/projects/p1/pipeline'],
      ['GET', '/api/v1/metrics'],
    ]);
  });

  it('导出地址是同源的直接下载链接', () => {
    const { api } = setup({});
    expect(api.report.docxUrl('p1')).toBe('/api/v1/projects/p1/report.docx');
    expect(api.report.annotatedPdfUrl('p1')).toBe('/api/v1/projects/p1/body.annotated.pdf');
  });

  it('price.save 用 PUT，price.simulate 用 POST price:simulate，请求体相同', async () => {
    const { api, calls } = setup({});
    const body = {
      params: {
        full_score: '30',
        above_deduct_per_pct: '1',
        below_deduct_per_pct: '0.5',
        benchmark: {
          method: 'fixed' as const,
          fixed_value: '1000',
          coefficient: '1',
          trim_pct: '0',
          include_own: false,
        },
      },
      competitor_prices: [],
      candidate_prices: ['990'],
      note: '',
    };
    await api.price.save('p1', body, { idempotencyKey: 'k-3' });
    await api.price.simulate('p1', body);
    expect(calls[0]).toMatchObject({ method: 'PUT', url: '/api/v1/projects/p1/price' });
    expect(calls[0]?.headers['Idempotency-Key']).toBe('k-3');
    expect(calls[1]).toMatchObject({ method: 'POST', url: '/api/v1/projects/p1/price:simulate' });
    expect(JSON.parse(calls[1]?.body ?? '')).toEqual(body);
  });
});
