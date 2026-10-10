import { useCallback, useEffect, useRef, useState } from 'react';
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist';
import { api } from '../../api/endpoints';
import { bboxToPercent, clampPage, fitWidthScale, parseBbox } from '../../lib/evidence';
import { loadPdfjs } from './pdfjs';
import { Icon } from '../../components/Icon';
import { Alert } from '../../components/ui';
import { Button } from '../../components/ui/button';
import { Tooltip } from '../../components/ui/tooltip';

export interface PdfViewerProps {
  versionId: string;
  /** 物理页码（从 1 开始），来自 EvidenceRef.physical_page。 */
  page: number;
  printedPage?: string | null;
  /** 归一化 bbox；null 时只显示整页，不画高亮。 */
  bbox: readonly number[] | null;
  /** 解析摘录，展示在页面下方，帮助核对而不是替代原页。 */
  quote?: string;
}

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; doc: PDFDocumentProxy };

function friendlyError(e: unknown): string {
  const status = typeof e === 'object' && e !== null && 'status' in e ? Number(e.status) : 0;
  if (status === 401) return '登录已过期，请重新登录后再查看原件。';
  if (status === 403 || status === 404) return '没有权限查看这份原件，或原件不存在。';
  return '原件暂时无法打开。无法打开原件不代表该处没有问题：审核草稿已保留，请恢复后核对原页。';
}

/** 授权加载原件（同源 cookie + Range）并渲染指定物理页；带 bbox 时叠加高亮。 */
export function PdfViewer({ versionId, page, printedPage, bbox, quote }: PdfViewerProps) {
  const [state, setState] = useState<LoadState>({ kind: 'loading' });
  const [current, setCurrent] = useState(page);
  const [zoom, setZoom] = useState(1);
  const [reload, setReload] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [box, setBox] = useState<{ w: number; h: number } | null>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    setCurrent(page);
  }, [page, versionId]);

  useEffect(() => {
    const flag = { cancelled: false };
    let doc: PDFDocumentProxy | null = null;
    setState({ kind: 'loading' });
    void (async () => {
      try {
        const pdfjs = await loadPdfjs();
        const task = pdfjs.getDocument({
          url: api.files.contentUrl(versionId),
          withCredentials: true,
          // 中文原件需要 CMap 与标准字体；随构建输出到 /pdfjs/，不依赖外部 CDN。
          cMapUrl: `${import.meta.env.BASE_URL}pdfjs/cmaps/`,
          cMapPacked: true,
          standardFontDataUrl: `${import.meta.env.BASE_URL}pdfjs/standard_fonts/`,
          // 按需 Range 读取：大图纸不整体下载。
          disableAutoFetch: true,
          rangeChunkSize: 256 * 1024,
        });
        doc = await task.promise;
        if (flag.cancelled) {
          void doc.destroy();
          return;
        }
        setState({ kind: 'ready', doc });
      } catch (e) {
        if (!flag.cancelled) setState({ kind: 'error', message: friendlyError(e) });
      }
    })();
    return () => {
      flag.cancelled = true;
      if (doc) void doc.destroy();
    };
  }, [versionId, reload]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    setWidth(el.clientWidth);
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => {
      setWidth(el.clientWidth);
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
    };
  }, []);

  const pageCount = state.kind === 'ready' ? state.doc.numPages : 0;
  const shown = state.kind === 'ready' ? clampPage(current, pageCount) : current;

  useEffect(() => {
    if (state.kind !== 'ready' || width === 0) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    let task: RenderTask | null = null;
    const flag = { cancelled: false };
    (async () => {
      const pg = await state.doc.getPage(shown);
      if (flag.cancelled) return;
      const base = pg.getViewport({ scale: 1 });
      const scale = fitWidthScale(width, base.width) * zoom;
      const viewport = pg.getViewport({ scale });
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.floor(viewport.width * dpr);
      canvas.height = Math.floor(viewport.height * dpr);
      canvas.style.width = `${String(Math.floor(viewport.width))}px`;
      canvas.style.height = `${String(Math.floor(viewport.height))}px`;
      setBox({ w: viewport.width, h: viewport.height });
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      task = pg.render({
        canvasContext: ctx,
        viewport,
        transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined,
      });
      try {
        await task.promise;
      } catch (e) {
        if (!(e instanceof Error && e.name === 'RenderingCancelledException')) throw e;
      }
    })().catch(() => {
      if (!flag.cancelled) setState({ kind: 'error', message: friendlyError(null) });
    });
    return () => {
      flag.cancelled = true;
      task?.cancel();
    };
  }, [state, shown, width, zoom]);

  const go = useCallback(
    (delta: number) => {
      setCurrent((c) => clampPage(c + delta, pageCount));
    },
    [pageCount],
  );

  const parsed = parseBbox(bbox);
  const highlightHere = parsed !== null && shown === page;
  const pct = parsed ? bboxToPercent(parsed) : null;

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
        <span className="text-xs text-muted-foreground tabular">
          物理第 {shown} 页{pageCount ? ` / 共 ${String(pageCount)} 页` : ''}
          {printedPage ? `（印刷页 ${printedPage}）` : ''}
        </span>
        <span className="flex flex-wrap items-center gap-1">
          {shown !== page ? (
            <Button
              size="sm"
              variant="link"
              onClick={() => {
                setCurrent(page);
              }}
            >
              回到证据页
            </Button>
          ) : null}
          <Tooltip content="上一页">
            <Button
              size="icon"
              variant="ghost"
              aria-label="上一页"
              onClick={() => {
                go(-1);
              }}
              disabled={state.kind !== 'ready' || shown <= 1}
            >
              <Icon name="ArrowLeft" />
            </Button>
          </Tooltip>
          <Tooltip content="下一页">
            <Button
              size="icon"
              variant="ghost"
              aria-label="下一页"
              onClick={() => {
                go(1);
              }}
              disabled={state.kind !== 'ready' || shown >= pageCount}
            >
              <Icon name="ArrowRight" />
            </Button>
          </Tooltip>
          <span aria-hidden="true" className="mx-1 h-4 w-px bg-border" />
          <Tooltip content="缩小">
            <Button
              size="icon"
              variant="ghost"
              aria-label="缩小"
              onClick={() => {
                setZoom((z) => Math.max(0.6, +(z - 0.2).toFixed(1)));
              }}
              disabled={state.kind !== 'ready'}
            >
              <Icon name="ZoomOut" />
            </Button>
          </Tooltip>
          <span className="w-10 text-center text-xs text-muted-foreground tabular">
            {Math.round(zoom * 100)}%
          </span>
          <Tooltip content="放大">
            <Button
              size="icon"
              variant="ghost"
              aria-label="放大"
              onClick={() => {
                setZoom((z) => Math.min(2.4, +(z + 0.2).toFixed(1)));
              }}
              disabled={state.kind !== 'ready'}
            >
              <Icon name="ZoomIn" />
            </Button>
          </Tooltip>
        </span>
      </div>
      <div
        className="max-h-[78vh] overflow-auto bg-muted p-3 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring"
        ref={wrapRef}
        {...(state.kind === 'ready'
          ? { tabIndex: 0, role: 'region', 'aria-label': `原件第 ${String(shown)} 页，可滚动查看` }
          : {})}
      >
        {state.kind === 'loading' ? (
          <p
            className="m-0 flex items-center justify-center gap-2 py-24 text-[13px] text-muted-foreground"
            role="status"
          >
            <Icon name="LoaderCircle" className="animate-spin" />
            正在载入原件…
          </p>
        ) : null}
        {state.kind === 'error' ? (
          <Alert
            tone="danger"
            role="alert"
            action={
              <Button
                size="sm"
                onClick={() => {
                  setReload((n) => n + 1);
                }}
              >
                重新载入
              </Button>
            }
          >
            {state.message}
          </Alert>
        ) : null}
        {state.kind === 'ready' ? (
          <div
            className="relative mx-auto bg-white shadow-sm"
            style={box ? { width: box.w, height: box.h } : undefined}
          >
            <canvas ref={canvasRef} className="block" />
            {highlightHere && pct ? (
              <div
                className="pointer-events-none absolute rounded-[2px] bg-highlight outline-2 outline-highlight-border mix-blend-multiply"
                data-testid="evidence-highlight"
                style={{
                  left: `${String(pct.left)}%`,
                  top: `${String(pct.top)}%`,
                  width: `${String(pct.width)}%`,
                  height: `${String(pct.height)}%`,
                }}
              />
            ) : null}
          </div>
        ) : null}
      </div>
      {state.kind === 'ready' && parsed === null ? (
        <p className="m-0 border-t border-border px-3 py-2 text-xs text-muted-foreground">
          该证据暂无可靠坐标，只显示整页，不标注具体位置。
        </p>
      ) : null}
      {quote ? (
        <blockquote className="m-0 border-t border-border px-4 py-3 text-[13px] leading-relaxed">
          <small className="mb-1 block font-sans text-xs text-muted-foreground">
            解析摘录（可能与原页排版有差异，以原页为准）
          </small>
          {quote}
        </blockquote>
      ) : null}
    </div>
  );
}
