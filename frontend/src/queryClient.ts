import { QueryClient } from '@tanstack/react-query';
import { isApiError } from './api/errors';

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: false,
        // 只重试"可重试"的错误（503/网络），4xx 属于确定结果，立即展示。
        retry: (count, err) => count < 2 && (!isApiError(err) || err.retryable),
      },
      mutations: { retry: false },
    },
  });
}
