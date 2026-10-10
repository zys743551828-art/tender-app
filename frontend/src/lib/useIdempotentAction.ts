import { useMutation, type UseMutationResult } from '@tanstack/react-query';
import { useRef } from 'react';
import { newIdempotencyKey } from './uuid';

/**
 * 把"一次用户动作"绑定到一个 Idempotency-Key：
 * - 同样内容重试（失败后再点一次、网络抖动）复用同一个键，服务端同键同请求返回原记录；
 * - 内容变了（用户改了输入）换新键，避免服务端报 IDEMPOTENCY_CONFLICT；
 * - 成功后重置，下一次动作用新键。
 */
export function useIdempotentAction<TVars, TData>(
  fn: (vars: TVars, o: { idempotencyKey: string }) => Promise<TData>,
  opts: {
    onSuccess?: (data: TData, vars: TVars) => void | Promise<void>;
    onError?: (error: Error, vars: TVars) => void | Promise<void>;
  } = {},
): UseMutationResult<TData, Error, TVars> {
  const keyRef = useRef<{ key: string; sig: string } | null>(null);
  return useMutation<TData, Error, TVars>({
    mutationFn: async (vars) => {
      const sig = JSON.stringify(vars) || '';
      if (keyRef.current?.sig !== sig) keyRef.current = { key: newIdempotencyKey(), sig };
      const key = keyRef.current.key;
      const data = await fn(vars, { idempotencyKey: key });
      keyRef.current = null;
      return data;
    },
    onSuccess: opts.onSuccess,
    onError: opts.onError,
  });
}
