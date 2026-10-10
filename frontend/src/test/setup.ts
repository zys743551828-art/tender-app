import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterAll, afterEach, beforeAll } from 'vitest';
import { toast } from 'sonner';
import { server } from './server';

// Node 的 fetch 不接受相对 URL；浏览器会按页面 origin 解析，这里在测试里补上同样的行为。
const nativeFetch = globalThis.fetch.bind(globalThis);
globalThis.fetch = (input: RequestInfo | URL, init?: RequestInit) =>
  nativeFetch(
    typeof input === 'string' && input.startsWith('/')
      ? new URL(input, window.location.origin).href
      : input,
    init,
  );

// jsdom 没有 matchMedia / scrollIntoView：给出最小桩，行为等同"桌面宽度"。
window.matchMedia = (query: string) =>
  ({
    matches: false,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }) as unknown as MediaQueryList;
Element.prototype.scrollIntoView = () => undefined;

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' });
});
afterEach(() => {
  server.resetHandlers();
  // sonner 的提示存在模块级状态里，新挂载的 Toaster 会重放未关闭的提示；每个用例结束时全部关掉。
  toast.dismiss();
  cleanup();
  try {
    sessionStorage.clear();
  } catch {
    /* ignore */
  }
});
afterAll(() => {
  server.close();
});
