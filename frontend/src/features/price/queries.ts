import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { api } from '../../api/endpoints';
import type { PricePlan, PricePlanRequest, PricePlanWithSimulation } from '../../api/types';
import { useIdempotentAction } from '../../lib/useIdempotentAction';
import { reportKey } from '../report/queries';

export const priceKeys = {
  current: (projectId: string) => ['projects', projectId, 'price'] as const,
  history: (projectId: string) => ['projects', projectId, 'price', 'history'] as const,
};

/** 当前报价方案；还没有保存过时 data 为 null。 */
export function usePrice(projectId: string) {
  return useQuery<PricePlanWithSimulation | null>({
    queryKey: priceKeys.current(projectId),
    queryFn: ({ signal }) => api.price.get(projectId, { signal }),
  });
}

export function usePriceHistory(projectId: string) {
  return useQuery<PricePlan[]>({
    queryKey: priceKeys.history(projectId),
    queryFn: ({ signal }) => api.price.history(projectId, { signal }),
  });
}

/** 每次保存追加一个版本；成功后刷新当前方案、历史与报告里的报价摘要。 */
export function useSavePrice(projectId: string, onSaved?: () => void) {
  const qc = useQueryClient();
  return useIdempotentAction((b: PricePlanRequest, o) => api.price.save(projectId, b, o), {
    onSuccess: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: priceKeys.current(projectId) }),
        qc.invalidateQueries({ queryKey: reportKey(projectId) }),
      ]);
      onSaved?.();
    },
  });
}

/** 值稳定一段时间后才更新，避免每敲一个字就请求一次试算。 */
export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => {
      setV(value);
    }, ms);
    return () => {
      clearTimeout(t);
    };
  }, [value, ms]);
  return v;
}

/** 不保存的实时试算。请求体为 null（表单还没填完整）时不请求；换请求时保留上一次结果，避免闪烁。 */
export function useSimulation(projectId: string, body: PricePlanRequest | null) {
  return useQuery({
    queryKey: ['projects', projectId, 'price', 'simulate', body] as const,
    queryFn: ({ signal }) => {
      if (!body) throw new Error('缺少试算参数');
      return api.price.simulate(projectId, body, { signal });
    },
    enabled: body !== null,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}
