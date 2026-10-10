import { useQuery, type QueryClient } from '@tanstack/react-query';
import { api } from '../../api/endpoints';
import type { FactList } from '../../api/types';

export const factKeys = {
  list: (projectId: string) => ['projects', projectId, 'facts'] as const,
};

/** 项目当前（最新）事实集。每次录入都会生成新事实集，条目 ID 随之更换。 */
export function useFacts(projectId: string) {
  return useQuery<FactList>({
    queryKey: factKeys.list(projectId),
    queryFn: ({ signal }) => api.facts.list(projectId, { signal }),
  });
}

/** 事实集更换后：重新读取事实，并让流水线与报告得知“事实有更新”。 */
export function refreshFacts(qc: QueryClient, projectId: string): Promise<unknown> {
  return Promise.all([
    qc.invalidateQueries({ queryKey: factKeys.list(projectId) }),
    qc.invalidateQueries({ queryKey: ['projects', projectId, 'pipeline'] }),
    qc.invalidateQueries({ queryKey: ['projects', projectId, 'report'] }),
  ]);
}
