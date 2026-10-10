import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/endpoints';
import { isApiError } from '../../api/errors';
import type { RuleSet } from '../../api/types';

export const rulesKey = (projectId: string) => ['projects', projectId, 'rules'] as const;

/** 还没有规则集（404）不是错误，返回 null 表示“未生成”。 */
export function useRuleSet(projectId: string) {
  return useQuery<RuleSet | null>({
    queryKey: rulesKey(projectId),
    queryFn: async () => {
      try {
        return await api.rules.get(projectId);
      } catch (e) {
        if (isApiError(e) && e.kind === 'not_found') return null;
        throw e;
      }
    },
  });
}
