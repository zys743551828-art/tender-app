import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import type { TableStructurePreview } from '../../api/types';
import { server } from '../../test/server';
import { TableStructures } from './TableStructures';

function show() {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <TableStructures projectId="prj-1" versionId="ver-1" parseId="prs-1" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function data(over: Partial<TableStructurePreview> = {}): TableStructurePreview {
  return {
    version_id: 'ver-1',
    parse_id: 'prs-1',
    state: 'candidate_preview',
    table_count: 2,
    table_index: 0,
    table_id: 'table_1_0',
    physical_page: 1,
    source: 'raster_grid',
    bbox: [0.1, 0.1, 0.9, 0.9],
    row_count: 21,
    row_offset: 0,
    next_row_offset: 20,
    rows: [
      ['项目', null],
      ['工期', '180'],
    ],
    cell_line_indices: [
      [[0], []],
      [[1], [2]],
    ],
    unassigned_line_indices: [3],
    column_boundaries: [0.1, 0.5, 0.9],
    row_boundaries: [0.1, 0.5, 0.9],
    issues: [],
    continuations: [
      {
        from_table_id: 'table_1_0',
        to_table_id: 'table_2_0',
        from_page: 1,
        to_page: 2,
        reason: 'adjacent_pages_repeated_header_aligned_columns',
        review: 'pending',
      },
    ],
    ...over,
  };
}

describe('表格结构候选', () => {
  it('按需读取、明确空格与跨格缺口，并展示可能续表和原页链接', async () => {
    let calls = 0;
    server.use(
      http.get('/api/v1/files/ver-1/table-structures', ({ request }) => {
        calls++;
        const url = new URL(request.url);
        expect(url.searchParams.get('expected_parse_id')).toBe('prs-1');
        return HttpResponse.json(
          url.searchParams.get('row_offset') === '20'
            ? data({ row_offset: 20, next_row_offset: null, rows: [['最后一行', '15.12']] })
            : data(),
        );
      }),
    );
    show();
    expect(calls).toBe(0);
    await userEvent.click(screen.getByRole('button', { name: '查看表格结构候选' }));
    expect(await screen.findByRole('table', { name: '原始表格结构候选' })).toBeInTheDocument();
    expect(screen.getByText('未识别')).toBeInTheDocument();
    expect(screen.getByText(/有 1 行 OCR 跨格或归属不明/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '对照第 2 页' })).toHaveAttribute(
      'href',
      '/projects/prj-1/files/ver-1?page=2&verify=1',
    );
    expect(screen.getByText(/可能续表：/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '下一组表格行' }));
    expect(await screen.findByText('最后一行')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '下一组表格行' })).toBeDisabled();
  });

  it('旧解析显示未执行，不能冒充新结构候选', async () => {
    server.use(
      http.get('/api/v1/files/ver-1/table-structures', () =>
        HttpResponse.json(data({ state: 'not_evaluated', table_count: 0 })),
      ),
    );
    show();
    await userEvent.click(screen.getByRole('button', { name: '查看表格结构候选' }));
    expect(await screen.findByText(/此解析未执行结构候选检查/)).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
});
