import { useEffect, useRef, useState } from "react";
import type {
  PDFDocumentProxy,
  PDFDocumentLoadingTask,
  RenderTask,
} from "pdfjs-dist";
import workerUrl from "pdfjs-dist/legacy/build/pdf.worker.min.mjs?url";
import { objectFetch, sha256Hex, sizeLabel } from "./api";
import { ErrorNotice, Loading } from "./components";

type TransferProgress = { received: number; total?: number };
const fetching = "正在取回 PDF 原件…";

async function readPdfBytes(
  response: Response,
  size: number | undefined,
  signal: AbortSignal,
  report: (progress: TransferProgress) => void,
) {
  if (!response.body || typeof TransformStream === "undefined")
    return response.arrayBuffer();
  const encoding = response.headers.get("Content-Encoding");
  const length =
    size ??
    (!encoding || encoding === "identity"
      ? Number(response.headers.get("Content-Length"))
      : 0);
  const total = Number.isSafeInteger(length) && length > 0 ? length : undefined;
  if (total !== undefined && total <= 1024 * 1024)
    return response.arrayBuffer();
  let received = 0;
  report({ received, total });
  const stream = response.body.pipeThrough(
    new TransformStream<Uint8Array, Uint8Array>({
      transform(chunk, output) {
        received += chunk.byteLength;
        output.enqueue(chunk);
      },
    }),
    { signal },
  );
  let shown = 0;
  const timer = window.setInterval(() => {
    if (shown === received || signal.aborted) return;
    shown = received;
    report({
      received,
      total: total !== undefined && received <= total ? total : undefined,
    });
  }, 250);
  try {
    return await new Response(stream).arrayBuffer();
  } finally {
    window.clearInterval(timer);
  }
}

export function PdfPreview({
  url,
  filename,
  page,
  expectedSha256,
  byteSize,
  onPageCount,
  onRefresh,
}: {
  url: string;
  filename: string;
  page: number;
  expectedSha256?: string;
  byteSize?: number;
  onPageCount: (count: number) => void;
  onRefresh: () => void;
}) {
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [rendering, setRendering] = useState(true);
  const [loadLabel, setLoadLabel] = useState(fetching);
  const [progress, setProgress] = useState<TransferProgress | null>(null);
  const [width, setWidth] = useState(600);
  const canvas = useRef<HTMLCanvasElement>(null);
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let active = true;
    let loadingTask: PDFDocumentLoadingTask | undefined;
    const controller = new AbortController();
    setError(null);
    setPdf(null);
    setLoadLabel(fetching);
    setProgress(null);
    void (async () => {
      const response = await objectFetch(url, {
        signal: controller.signal,
      });
      if (!response.ok)
        throw new Error(
          `原页读取失败（${response.status}）。请刷新原件访问地址后重试。`,
        );
      if (!active) return;
      const buffer = await readPdfBytes(
        response,
        byteSize,
        controller.signal,
        (item) => {
          if (active) setProgress(item);
        },
      );
      if (!active) return;
      setProgress(null);
      if (expectedSha256 !== undefined) {
        setLoadLabel("正在核验原件摘要…");
        if ((await sha256Hex(buffer)) !== expectedSha256)
          throw new Error(
            "原件字节与固定版本摘要不一致，未显示其他文件的物理页。",
          );
      }
      if (!active) return;
      setLoadLabel("正在载入 PDF 文档…");
      const data = new Uint8Array(buffer);
      // Use PDF.js's own compatibility build for the supported browser baseline.
      const pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs");
      pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
      if (!active) return;
      loadingTask = pdfjs.getDocument({
        data,
        cMapUrl: "/pdfjs/cmaps/",
        cMapPacked: true,
        standardFontDataUrl: "/pdfjs/standard_fonts/",
        wasmUrl: "/pdfjs/wasm/",
        iccUrl: "/pdfjs/iccs/",
      });
      const loaded = await loadingTask.promise;
      if (!active) {
        await loadingTask.destroy();
        return;
      }
      setPdf(loaded);
      onPageCount(loaded.numPages);
    })().catch((failure: unknown) => {
      if (active) setError(failure);
    });
    return () => {
      active = false;
      controller.abort();
      if (loadingTask) void loadingTask.destroy();
    };
  }, [url, onPageCount, expectedSha256, byteSize]);
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) =>
      setWidth(Math.max(1, entry.contentRect.width)),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!pdf || !canvas.current) return;
    let cancelled = false;
    let task: RenderTask | undefined;
    setRendering(true);
    setError(null);
    void (async () => {
      const source = await pdf.getPage(page);
      if (cancelled || !canvas.current) return;
      const base = source.getViewport({ scale: 1 });
      const viewport = source.getViewport({
        scale: Math.min(width / base.width, 2),
      });
      const target = canvas.current;
      const context = target.getContext("2d");
      if (!context)
        throw new Error("此浏览器无法绘制PDF原页。可下载原件查看。");
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      target.width = Math.floor(viewport.width * ratio);
      target.height = Math.floor(viewport.height * ratio);
      target.style.width = `${Math.floor(viewport.width)}px`;
      target.style.height = `${Math.floor(viewport.height)}px`;
      task = source.render({
        canvas: target,
        canvasContext: context,
        viewport,
        transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
      });
      await task.promise;
      if (!cancelled) setRendering(false);
    })().catch((failure: unknown) => {
      if (!cancelled) {
        setError(failure);
        setRendering(false);
      }
    });
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [pdf, page, width]);
  return (
    <div className="pdf-canvas-container" ref={container}>
      {error ? (
        <ErrorNotice error={error} onRetry={onRefresh} />
      ) : (
        (!pdf || rendering) && (
          <Loading text={pdf ? `正在绘制物理页 ${page}…` : loadLabel} />
        )
      )}
      {!error && !pdf && progress && (
        <div className="pdf-read-progress">
          {progress.total !== undefined && (
            <progress
              aria-label="PDF 原件接收进度"
              max={progress.total}
              value={progress.received}
            />
          )}
          <small>
            已收到 {sizeLabel(progress.received)}
            {progress.total !== undefined && ` / ${sizeLabel(progress.total)}`}
          </small>
        </div>
      )}
      <canvas
        ref={canvas}
        role="img"
        aria-label={`${filename}，物理页${page}原页`}
        hidden={!pdf || !!error}
      />
    </div>
  );
}
