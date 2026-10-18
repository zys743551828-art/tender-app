import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import type { AssistantReply } from '../../api/types';
import { pipeline, report } from '../../test/fixtures';
import { ME, apiError, overview, project, renderApp } from '../../test/helpers';
import { server } from '../../test/server';

function backend() {
  server.use(
    http.get('/api/v1/projects', () => HttpResponse.json([overview()])),
    http.get('/api/v1/me', () => HttpResponse.json(ME)),
    http.get('/api/v1/projects/prj-1', () => HttpResponse.json(project())),
    http.get('/api/v1/projects/prj-1/pipeline', () => HttpResponse.json(pipeline())),
    http.get('/api/v1/projects/prj-1/report', () => HttpResponse.json(report())),
  );
}
const reply: AssistantReply = {
  project_id: 'prj-1',
  project_title: '城市支路',
  lot: '一标段',
  round: 1,
  snapshot_id: 'snp-old',
  body_version_id: 'ver-old',
  answer: '请先核对工期。',
  mode: 'model',
  materials: [{ version_id: 'ver-old', filename: '当前正文.pdf' }],
  links: ['basis', 'materials'],
  cards: [
    {
      kind: 'analysis',
      title: '检查当前资料',
      detail: '确认后启动评审。',
      expected_context: 'a'.repeat(64),
      object_version: null,
      rule_ids: [],
      rule_statements: [],
    },
  ],
};

describe('项目 AI 确认卡', () => {
  it('回答只生成草稿；点击确认后调用现有接口，保留本卡输入并显示实际结果', async () => {
    backend();
    let writes = 0;
    let payload: unknown;
    server.use(
      http.post('/api/v1/projects/prj-1/assistant', () => HttpResponse.json(reply)),
      http.post('/api/v1/projects/prj-1/analysis', async ({ request }) => {
        writes += 1;
        payload = await request.json();
        expect(request.headers.get('Idempotency-Key')).toBeTruthy();
        return HttpResponse.json(pipeline());
      }),
    );
    const user = userEvent.setup();
    renderApp('/projects/prj-1');
    const panel = await screen.findByRole('region', { name: '项目 AI 助手' });
    await user.click(within(panel).getByRole('button', { name: '检查新版' }));
    expect(await within(panel).findByText('请先核对工期。')).toBeInTheDocument();
    expect(writes).toBe(0);
    expect(within(panel).getByText('正文：ver-old')).toBeInTheDocument();
    const confirm = within(panel).getByRole('button', { name: '确认执行' });
    expect(confirm).toBeDisabled();
    await user.click(within(panel).getByRole('checkbox'));
    await user.click(confirm);
    expect(
      await within(panel).findByText('评审请求已受理，请查看流水线进度。'),
    ).toBeInTheDocument();
    expect(writes).toBe(1);
    expect(payload).toEqual({ expected_context: 'a'.repeat(64) });
    expect(within(panel).queryByRole('button', { name: '确认执行' })).not.toBeInTheDocument();
  });

  it('过期卡显示失效原因，不自动生成新输入或重发确认', async () => {
    backend();
    let writes = 0;
    server.use(
      http.post('/api/v1/projects/prj-1/assistant', () => HttpResponse.json(reply)),
      http.post('/api/v1/projects/prj-1/analysis', () => {
        writes += 1;
        return HttpResponse.json(apiError('assistant_card_stale', '资料已有变化，请重新提问'), {
          status: 409,
        });
      }),
    );
    const user = userEvent.setup();
    renderApp('/projects/prj-1');
    const panel = await screen.findByRole('region', { name: '项目 AI 助手' });
    await user.click(within(panel).getByRole('button', { name: '检查新版' }));
    await within(panel).findByText('请先核对工期。');
    await user.click(within(panel).getByRole('checkbox'));
    await user.click(within(panel).getByRole('button', { name: '确认执行' }));
    expect(await within(panel).findByText('资料已有变化，请重新提问')).toBeInTheDocument();
    await waitFor(() => expect(writes).toBe(1));
    expect(within(panel).getByRole('button', { name: '确认执行' })).toBeDisabled();
    expect(within(panel).queryByRole('button', { name: '重试同一卡片' })).not.toBeInTheDocument();
  });
});
