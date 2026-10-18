import { useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/endpoints';
import type { Decision, EffectivityRequest, ResolveTermRequest } from '../../api/types';
import { useIdempotentAction } from '../../lib/useIdempotentAction';
import { invalidateProject } from '../projects/queries';
import { reportKey } from '../report/queries';
import { rulesKey } from './queries';

/** 规则决定之后要重新读取的：规则、报告、流水线（输入可能已更新）与项目状态。 */
export function refreshRules(qc: ReturnType<typeof useQueryClient>, projectId: string) {
  return Promise.all([
    qc.invalidateQueries({ queryKey: rulesKey(projectId) }),
    qc.invalidateQueries({ queryKey: reportKey(projectId) }),
    qc.invalidateQueries({ queryKey: ['projects', projectId, 'pipeline'] }),
    invalidateProject(qc, projectId),
  ]);
}

export function useResolveTerm(projectId: string, onDone: () => void) {
  const qc = useQueryClient();
  return useIdempotentAction(
    (request: ResolveTermRequest, options) => api.rules.resolveTerm(projectId, request, options),
    {
      onSuccess: async () => {
        await refreshRules(qc, projectId);
        onDone();
      },
    },
  );
}

export function useDecideEffectivity(projectId: string, onDone: () => void) {
  const qc = useQueryClient();
  return useIdempotentAction(
    (request: EffectivityRequest, options) =>
      api.rules.decideEffectivity(projectId, request, options),
    {
      onSuccess: async () => {
        await refreshRules(qc, projectId);
        onDone();
      },
    },
  );
}

/** 对一条规则做决定（确认不要求理由）。返回的审核对象编号与原规则不同，说明后端复制出了新规则包。 */
export function useReviewRule(
  projectId: string,
  onDone?: (v: { ruleId: string; decision: Decision; corrected: boolean }) => void,
) {
  const qc = useQueryClient();
  return useIdempotentAction(
    (v: { ruleId: string; version: number; decision: Decision; reason?: string }, o) =>
      api.rules.review(
        v.ruleId,
        { object_version: String(v.version), decision: v.decision, reason: v.reason },
        o,
      ),
    {
      onSuccess: async (review, v) => {
        await refreshRules(qc, projectId);
        onDone?.({
          ruleId: v.ruleId,
          decision: v.decision,
          corrected: review.object_id !== v.ruleId,
        });
      },
    },
  );
}

/** 一次确认多条未审核的规则（按原文接受）。 */
export function useConfirmPending(projectId: string, onDone?: (confirmed: number) => void) {
  const qc = useQueryClient();
  return useIdempotentAction(
    (v: { version: number; ruleIds: string[] }, o) =>
      api.rules.confirmPending(
        projectId,
        { object_version: String(v.version), rule_ids: v.ruleIds },
        o,
      ),
    {
      onSuccess: async (r) => {
        await refreshRules(qc, projectId);
        onDone?.(r.confirmed);
      },
    },
  );
}
