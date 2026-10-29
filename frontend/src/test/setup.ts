import { transferableAbortController } from 'node:util';
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterAll, afterEach, beforeAll } from 'vitest';
import { toast } from 'sonner';
import { server } from './server';

// Node fetch 校验原生 AbortSignal 类型；jsdom 信号属于另一运行时。
// 测试传输使用 Node 控制器，仍执行真实取消，而不是忽略 signal。
globalThis.AbortController = transferableAbortController().constructor as typeof AbortController;
globalThis.AbortSignal = new AbortController().signal.constructor as typeof AbortSignal;

// 测试中按浏览器 origin 解析 Node fetch 不支持的相对 URL。
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
