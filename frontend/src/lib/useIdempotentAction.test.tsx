import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { useIdempotentAction } from './useIdempotentAction';

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider
    client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}
  >
    {children}
  </QueryClientProvider>
);

describe('useIdempotentAction', () => {
  it('失败后原样重试复用同一个键；内容改变换新键；成功后下一次动作换新键', async () => {
    const keys: string[] = [];
    let fail = 3;
    const fn = vi.fn((_v: { reason: string }, o: { idempotencyKey: string }) => {
      keys.push(o.idempotencyKey);
      return fail-- > 0 ? Promise.reject(new Error('boom')) : Promise.resolve('ok');
    });
    const { result } = renderHook(() => useIdempotentAction(fn), { wrapper });
    const run = async (reason: string) => {
      await act(async () => {
        await result.current.mutateAsync({ reason }).catch(() => undefined);
      });
    };
    await run('a'); // 失败
    await run('a'); // 原样重试，失败：复用键
    await run('b'); // 内容变了，失败：换新键
    await run('b'); // 原样重试，成功：复用键
    await run('b'); // 成功后的新动作：新键
    expect(keys[1]).toBe(keys[0]);
    expect(keys[2]).not.toBe(keys[1]);
    expect(keys[3]).toBe(keys[2]);
    expect(keys[4]).not.toBe(keys[3]);
  });
});
