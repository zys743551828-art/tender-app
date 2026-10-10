import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import type { SearchResult } from '../../api/types';
import { evidence, fileVersion, snapshot } from '../../test/fixtures';
import { ME, apiError, project, renderApp } from '../../test/helpers';
import { server } from '../../test/server';
import { gapText, validateSearch } from './search';

function backend(snapshots = [snapshot()]) {
  server.use(
    http.get('/api/v1/me', () => HttpResponse.json(ME)),
    http.get('/api/v1/projects/prj-1', () => HttpResponse.json(project())),
    http.get('/api/v1/projects/prj-1/snapshots', () => HttpResponse.json(snapshots)),
    http.get('/api/v1/projects/prj-1/files', () =>
      HttpResponse.json([fileVersion('ver-t', 'tender', '招标文件.pdf')]),
    ),
  );
}

const RESULT: SearchResult = {
  snapshot_id: 'snp-1',
  mode_used: 'keyword',
  index_state: 'unavailable',
  hits: [
    { evidence: evidence(), score: 0.5, channel: 'keyword' },
    {
      evidence: evidence({ evidence_id: 'evd-2', quote: '质保期 2 年', physical_page: 7 }),
      score: 0.25,
      channel: 'keyword',
    },
  ],
  gaps: ['hybrid_index_unavailable:使用关键词通道'],
};

describe('校验与文案', () => {
  it('validateSearch', () => {
    const ok = { query: '工期', topK: '10', mode: 'hybrid' as const };
    expect(validateSearch(ok)).toEqual({});
    expect(validateSearch({ ...ok, query: '  ' }).query).toBeDefined();
    expect(validateSearch({ ...ok, topK: '51' }).topK).toBeDefined();
    expect(validateSearch({ ...ok, topK: '0' }).topK).toBeDefined();
  });
  it('gapText 只留说明', () => {
    expect(gapText('hybrid_index_unavailable:使用关键词通道')).toBe('使用关键词通道');
    expect(gapText('无冒号')).toBe('无冒号');
  });
});

describe('证据检索页', () => {
  it('还没有任何一轮评审也能检索：默认范围是当前资料，请求体不带 snapshot_id', async () => {
    backend([]);
    let body: unknown = null;
    server.use(
      http.post('/api/v1/projects/prj-1/search', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ ...RESULT, snapshot_id: null });
      }),
    );
    renderApp('/projects/prj-1/search');
    expect(await screen.findByLabelText('检索范围')).toHaveValue('');
    await userEvent.type(screen.getByLabelText('检索内容'), '工期{Enter}');
    await screen.findByRole('list', { name: '检索结果' });
    expect(body).toEqual({ query: '工期', top_k: 10, mode: 'hybrid' });
  });

  it('可以把范围限定在某一轮评审用到的资料：请求体带该轮的 snapshot_id', async () => {
    backend();
    let body: unknown = null;
    server.use(
      http.post('/api/v1/projects/prj-1/search', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(RESULT);
      }),
    );
    renderApp('/projects/prj-1/search');
    await screen.findByRole('option', { name: /第 1 轮评审用到的资料/ });
    await userEvent.selectOptions(screen.getByLabelText('检索范围'), 'snp-1');
    await userEvent.type(screen.getByLabelText('检索内容'), '工期{Enter}');
    await screen.findByRole('list', { name: '检索结果' });
    expect(body).toEqual({ snapshot_id: 'snp-1', query: '工期', top_k: 10, mode: 'hybrid' });
  });

  it('空检索内容不发请求', async () => {
    backend();
    let called = false;
    server.use(
      http.post('/api/v1/projects/prj-1/search', () => {
        called = true;
        return HttpResponse.json(RESULT);
      }),
    );
    renderApp('/projects/prj-1/search');
    await userEvent.click(await screen.findByRole('button', { name: '检索' }));
    expect(screen.getByText('请输入要检索的内容')).toBeInTheDocument();
    expect(called).toBe(false);
  });

  it('检索：请求体符合 SearchRequest；显示原文、页码、文件名、降级说明与原页链接', async () => {
    backend();
    let body: unknown = null;
    server.use(
      http.post('/api/v1/projects/prj-1/search', async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(RESULT);
      }),
    );
    renderApp('/projects/prj-1/search');
    await userEvent.type(await screen.findByLabelText('检索内容'), '工期{Enter}');
    const list = await screen.findByRole('list', { name: '检索结果' });
    expect(body).toEqual({ query: '工期', top_k: 10, mode: 'hybrid' });
    expect(within(list).getByText('总工期为 180 日历天')).toBeInTheDocument();
    expect(within(list).getByText(/招标文件\.pdf · 第 3 页（原件页码 2）/)).toBeInTheDocument();
    expect(screen.getByText('使用关键词通道')).toBeInTheDocument();
    const links = within(list).getAllByRole('link', { name: '查看原页' });
    expect(links[0]).toHaveAttribute('href', '/projects/prj-1/evidence/evd-1');
  });

  it('无结果与后端错误', async () => {
    backend();
    server.use(
      http.post('/api/v1/projects/prj-1/search', () =>
        HttpResponse.json({ ...RESULT, hits: [], gaps: [] }),
      ),
    );
    renderApp('/projects/prj-1/search');
    await userEvent.type(await screen.findByLabelText('检索内容'), 'x');
    await userEvent.click(screen.getByRole('button', { name: '检索' }));
    expect(await screen.findByText(/没有找到相关证据/)).toBeInTheDocument();

    server.use(
      http.post('/api/v1/projects/prj-1/search', () =>
        HttpResponse.json(apiError('not_found', '检索范围不存在'), { status: 404 }),
      ),
    );
    await userEvent.click(screen.getByRole('button', { name: '检索' }));
    expect(await screen.findByText('检索范围不存在')).toBeInTheDocument();
  });
});
