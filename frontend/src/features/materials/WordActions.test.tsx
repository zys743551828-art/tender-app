import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { apiClient } from '../../api/client';
import type { FileVersion } from '../../api/types';
import { fileVersion } from '../../test/fixtures';
import { server } from '../../test/server';
import { WordActions } from './WordActions';

function mount(current = true) {
  const file: FileVersion = {
    ...fileVersion('word-1', 'body', '施组.docx'),
    word: {
      current,
      state: 'needs_review',
      error_code: null,
      adopted_pdf_version_id: null,
      candidates: [
        {
          link_id: 'link-1',
          pdf_version_id: 'pdf-1',
          method: 'controlled_render',
          gaps: ['complex_layout_requires_review'],
        },
      ],
    },
  };
  const onUpload = vi.fn();
  apiClient.setCsrfToken('csrf-test');
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <WordActions file={file} onUpload={onUpload} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { onUpload, file };
}

describe('Word 原稿与实际 PDF', () => {
  it('复杂转换 PDF 要查看、明确核对并填写依据才可采用，提交固定原稿与链接', async () => {
    const user = userEvent.setup();
    const requests: unknown[] = [];
    server.use(
      http.post(/\/api\/v1\/files\/word-1\/word:adopt$/, async ({ request }) => {
        requests.push(await request.json());
        return HttpResponse.json({});
      }),
    );
    mount();
    expect(screen.getByRole('link', { name: '查看转换生成的 PDF' })).toHaveAttribute(
      'href',
      '/projects/prj-1/files/pdf-1',
    );
    await user.click(screen.getByRole('button', { name: '核对后采用此 PDF' }));
    const submit = screen.getByRole('button', { name: '采用此 PDF' });
    expect(submit).toBeDisabled();
    await user.type(screen.getByRole('textbox', { name: '采用依据' }), '已核对表格与字体');
    expect(submit).toBeDisabled();
    await user.click(screen.getByRole('checkbox'));
    await user.click(submit);
    await waitFor(() =>
      expect(requests).toEqual([
        { link_id: 'link-1', reason: '已核对表格与字体', reviewed_pdf: true },
      ]),
    );
  });

  it('仅补交这份稿的 PDF，需要声明对应关系，不要求重传整批', async () => {
    const user = userEvent.setup();
    const { onUpload } = mount();
    await user.click(screen.getByRole('button', { name: '上传此稿的 PDF' }));
    const submit = screen.getByRole('button', { name: '上传并用于评审' });
    const pdf = new File(['%PDF-1.7'], '当前稿.pdf', { type: 'application/pdf' });
    await user.upload(screen.getByLabelText('选择此稿的 PDF'), pdf);
    expect(submit).toBeDisabled();
    await user.click(screen.getByRole('checkbox'));
    await user.click(submit);
    expect(onUpload).toHaveBeenCalledExactlyOnceWith(pdf);
  });

  it('历史原稿保留 PDF 链接，不再提供采用、重试或补交操作', () => {
    mount(false);
    expect(screen.getByText('历史 Word 原稿')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '查看转换生成的 PDF' })).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
