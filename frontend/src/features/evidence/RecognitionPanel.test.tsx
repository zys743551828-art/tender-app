import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { apiClient } from '../../api/client';
import type { RecognitionCandidates, RecognitionReviewRequest } from '../../api/types';
import { evidence } from '../../test/fixtures';
import { server } from '../../test/server';
import { apiError } from '../../test/helpers';
import { RecognitionPanel } from './RecognitionPanel';

function data(over: Partial<RecognitionCandidates> = {}): RecognitionCandidates {
  return {
    version_id: 'ver-1',
    parse_id: 'prs-1',
    can_review: true,
    coverage_gaps: ['page_1:no_text_layer'],
    total: 1,
    pending_count: 1,
    offset: 0,
    next_offset: null,
    items: [
      evidence({
        evidence_id: 'evd-1',
        version_id: 'ver-1',
        physical_page: 1,
        quote: '费用15.12万元',
        kind: 'visual_observation',
        semantic_review: 'pending',
      }),
    ],
    history: [],
    ...over,
  };
}

function show() {
  apiClient.setCsrfToken('csrf-test');
  render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
        })
      }
    >
      <MemoryRouter>
        <RecognitionPanel projectId="prj-1" versionId="ver-1" initiallyOpen />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('候选核验', () => {
  it('原页、数字和说明均核对后才提交，提交固定解析与证据身份', async () => {
    let sent: RecognitionReviewRequest | null = null;
    server.use(
      http.get('/api/v1/files/ver-1/recognition', () => HttpResponse.json(data())),
      http.post('/api/v1/files/ver-1/recognition:review', async ({ request }) => {
        sent = (await request.json()) as RecognitionReviewRequest;
        return HttpResponse.json(
          apiError('recognition_parse_stale', '识别依据已有变化，请刷新候选后重新核对'),
          { status: 409 },
        );
      }),
    );
    show();
    const submit = await screen.findByRole('button', { name: '保存此条核验' });
    expect(submit).toBeDisabled();
    expect(screen.getByRole('link', { name: '查看原页第 1 页' })).toHaveAttribute(
      'href',
      '/projects/prj-1/files/ver-1?page=1&verify=1',
    );
    await userEvent.type(screen.getByLabelText('核验说明'), '逐字核验并核对金额');
    await userEvent.click(screen.getByLabelText('已对照原页核对该候选'));
    expect(submit).toBeDisabled();
    await userEvent.click(screen.getByLabelText('已单独核对数字、符号与单位'));
    await userEvent.click(submit);
    await waitFor(() =>
      expect(sent).toMatchObject({
        expected_parse_id: 'prs-1',
        evidence_id: 'evd-1',
        decision: 'accept',
        reviewed_original: true,
        reviewed_numbers: true,
      }),
    );
    expect(await screen.findByText('识别依据已有变化，请刷新候选后重新核对')).toBeInTheDocument();
  });

  it('修改订正文字后清除原页和数字确认，排除候选仍须说明', async () => {
    server.use(http.get('/api/v1/files/ver-1/recognition', () => HttpResponse.json(data())));
    show();
    await screen.findByText('费用15.12万元');
    await userEvent.selectOptions(screen.getByLabelText('处理方式'), 'correct');
    await userEvent.click(screen.getByLabelText('已对照原页核对该候选'));
    await userEvent.click(screen.getByLabelText('已单独核对数字、符号与单位'));
    await userEvent.type(screen.getByLabelText('对照原页订正'), '。');
    expect(screen.getByLabelText('已对照原页核对该候选')).not.toBeChecked();
    expect(screen.getByLabelText('已单独核对数字、符号与单位')).not.toBeChecked();
    await userEvent.selectOptions(screen.getByLabelText('处理方式'), 'reject');
    expect(screen.queryByLabelText('已单独核对数字、符号与单位')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '保存此条核验' })).toBeDisabled();
  });

  it('旧稿或解析进行中仅展示候选，不允许保存', async () => {
    server.use(
      http.get('/api/v1/files/ver-1/recognition', () =>
        HttpResponse.json(data({ can_review: false })),
      ),
    );
    show();
    expect(await screen.findByRole('button', { name: '保存此条核验' })).toBeDisabled();
    expect(screen.getByLabelText('已对照原页核对该候选')).toBeDisabled();
  });
});
