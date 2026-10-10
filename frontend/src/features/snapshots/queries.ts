import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/endpoints';
import type { InputSnapshot } from '../../api/types';

export const snapshotKeys = {
  list: (projectId: string) => ['projects', projectId, 'snapshots'] as const,
};

/** 各轮评审的输入快照（后端按时间倒序）。 */
export function useSnapshots(projectId: string) {
  const qc = useQueryClient();
  const q = useQuery<InputSnapshot[]>({
    queryKey: snapshotKeys.list(projectId),
    queryFn: ({ signal }) => api.snapshots.list(projectId, { signal }),
  });
  return {
    snapshots: q.data ?? [],
    isPending: q.isPending,
    error: q.error,
    refresh: () => qc.invalidateQueries({ queryKey: snapshotKeys.list(projectId) }),
  };
}
