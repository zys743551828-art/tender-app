import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const getPage = vi.fn(() =>
  Promise.resolve({
    getViewport: ({ scale }: { scale: number }) => ({ width: 600 * scale, height: 800 * scale }),
    render: () => ({ promise: Promise.resolve(), cancel: vi.fn() }),
  }),
);
type OpenArgs = Record<string, unknown>;
const getDocument = vi.fn<(o: OpenArgs) => { promise: Promise<unknown> }>(() => ({
  promise: Promise.resolve({ numPages: 5, getPage, destroy: vi.fn(() => Promise.resolve()) }),
}));
vi.mock('./pdfjs', () => ({ loadPdfjs: () => Promise.resolve({ getDocument }) }));

import { PdfViewer } from './PdfViewer';

beforeEach(() => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
  getDocument.mockClear();
});

describe('PdfViewer 证据定位', () => {
  it('合法 bbox：在证据页画高亮，位置为百分比，随缩放自动对齐', async () => {
    render(
      <PdfViewer
        versionId="ver-1"
        page={3}
        bbox={[0.1, 0.2, 0.6, 0.4]}
        quote="本工程拟用 160 天"
      />,
    );
    const hl = await screen.findByTestId('evidence-highlight');
    expect(hl).toHaveStyle({ left: '10%', top: '20%', width: '50%' });
    expect(Number.parseFloat(hl.style.height)).toBeCloseTo(20, 5);
    expect(screen.getByText(/物理第 3 页 \/ 共 5 页/)).toBeInTheDocument();
    expect(screen.getByText('本工程拟用 160 天')).toBeInTheDocument();
  });

  it('bbox 为 null：只显示整页，不画高亮，并说明原因', async () => {
    render(<PdfViewer versionId="ver-1" page={2} bbox={null} />);
    expect(await screen.findByText(/暂无可靠坐标，只显示整页/)).toBeInTheDocument();
    expect(screen.queryByTestId('evidence-highlight')).not.toBeInTheDocument();
  });

  it('bbox 越界（不可信）同样不画高亮', async () => {
    render(<PdfViewer versionId="ver-1" page={2} bbox={[72, 100, 300, 140]} />);
    expect(await screen.findByText(/暂无可靠坐标/)).toBeInTheDocument();
    expect(screen.queryByTestId('evidence-highlight')).not.toBeInTheDocument();
  });

  it('翻到别的页时高亮消失，可一键回到证据页', async () => {
    render(<PdfViewer versionId="ver-1" page={3} bbox={[0.1, 0.2, 0.6, 0.4]} />);
    await screen.findByTestId('evidence-highlight');
    await userEvent.click(screen.getByRole('button', { name: '下一页' }));
    expect(screen.queryByTestId('evidence-highlight')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '回到证据页' }));
    expect(await screen.findByTestId('evidence-highlight')).toBeInTheDocument();
  });

  it('证据页码超出文档页数时夹到最后一页，不崩溃', async () => {
    render(<PdfViewer versionId="ver-1" page={99} bbox={null} />);
    expect(await screen.findByText(/物理第 5 页 \/ 共 5 页/)).toBeInTheDocument();
  });

  it('使用同源 cookie 授权与 Range 读取原件地址', async () => {
    render(<PdfViewer versionId="ver-9" page={1} bbox={null} />);
    await waitFor(() => {
      expect(getDocument).toHaveBeenCalled();
    });
    expect(getDocument.mock.calls[0]?.[0]).toMatchObject({
      url: '/api/v1/files/ver-9/content',
      withCredentials: true,
      disableAutoFetch: true,
    });
  });

  it('原件打不开：提示“不代表没有问题”，可重新载入', async () => {
    getDocument.mockImplementationOnce(() => ({
      promise: Promise.reject(Object.assign(new Error('x'), { status: 503 })),
    }));
    render(<PdfViewer versionId="ver-1" page={1} bbox={null} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('不代表该处没有问题');
    await userEvent.click(screen.getByRole('button', { name: '重新载入' }));
    expect(await screen.findByText(/共 5 页/)).toBeInTheDocument();
  });
});
