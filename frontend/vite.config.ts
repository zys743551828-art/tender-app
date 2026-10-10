/// <reference types="vitest/config" />
import { cpSync, createReadStream, existsSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig, type Plugin } from 'vite';

/**
 * PDF.js 渲染中文原件需要 CMap（预定义字符映射）与标准字体数据，默认从 CDN 取；内网部署不能依赖 CDN，
 * 所以构建时把它们从 node_modules 复制到 dist/pdfjs/，开发服务器同路径直接提供。
 */
function pdfjsAssets(): Plugin {
  const root = resolve('node_modules/pdfjs-dist');
  const dirs = ['cmaps', 'standard_fonts'];
  return {
    name: 'pdfjs-assets',
    configureServer(server) {
      server.middlewares.use('/pdfjs', (req, res, next) => {
        const file = join(root, decodeURIComponent((req.url ?? '').split('?')[0] ?? ''));
        if (!file.startsWith(root) || !existsSync(file) || !statSync(file).isFile()) {
          next();
          return;
        }
        res.setHeader('Content-Type', 'application/octet-stream');
        createReadStream(file).pipe(res);
      });
    },
    closeBundle() {
      for (const d of dirs) cpSync(join(root, d), resolve('dist/pdfjs', d), { recursive: true });
    },
  };
}

// 开发：/api 代理到后端 8000；预览（vite preview）同样代理，可用 API_TARGET 覆盖（截图自查用本地假后端）。
const target = process.env.API_TARGET ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react(), tailwindcss(), pdfjsAssets()],
  server: { port: 5173, proxy: { '/api': { target, changeOrigin: false } } },
  preview: { port: 4173, proxy: { '/api': { target, changeOrigin: false } } },
  build: {
    target: 'es2022',
    sourcemap: false,
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        // 图表库单独成块，只随报价、度量两页按需加载。
        manualChunks: (id) =>
          /node_modules\/(recharts|d3-|victory-vendor)/.test(id) ? 'charts' : undefined,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    restoreMocks: true,
  },
});
