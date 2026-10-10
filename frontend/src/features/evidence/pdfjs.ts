/**
 * PDF.js 的懒加载入口：主包不含 pdfjs，进入证据页时才加载。
 * worker 由 Vite 作为静态资源随构建输出（?url），不依赖任何外部 CDN，内网可用。
 */
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

type PdfjsModule = typeof import('pdfjs-dist');
let cached: Promise<PdfjsModule> | null = null;

export function loadPdfjs(): Promise<PdfjsModule> {
  cached ??= import('pdfjs-dist').then((m) => {
    m.GlobalWorkerOptions.workerSrc = workerUrl;
    return m;
  });
  return cached;
}
