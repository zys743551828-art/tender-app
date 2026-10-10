import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { api } from '../../api/endpoints';
import { isApiError } from '../../api/errors';
import type { PipelineStatus, Report } from '../../api/types';
import { useIdempotentAction } from '../../lib/useIdempotentAction';
import { invalidateProject } from '../projects/queries';

export const pipelineKey = (projectId: string) => ['projects', projectId, 'pipeline'] as const;
export const reportKey = (projectId: string) => ['projects', projectId, 'report'] as const;

/** 评审结果变化后需要重新读取的查询：报告、问题、规则、预测都随最新一轮评审而变。 */
const DEPENDENT_KEYS = ['report', 'findings', 'rules', 'compliance', 'prediction', 'snapshots'];

function refreshReviewData(
  qc: ReturnType<typeof useQueryClient>,
  projectId: string,
): Promise<void> {
  return Promise.all([
    qc.invalidateQueries({
      predicate: (q) =>
        q.queryKey[0] === 'projects' &&
        q.queryKey[1] === projectId &&
        DEPENDENT_KEYS.includes(String(q.queryKey[2])),
    }),
    invalidateProject(qc, projectId),
  ]).then(() => undefined);
}

/**
 * 流水线状态。评审进行中每 3 秒刷新一次；由进行中变为完成（或失败）时，
 * 报告、问题与项目状态随之重新读取，页面不需要人手动刷新。
 */
export function usePipeline(projectId: string) {
  const qc = useQueryClient();
  const q = useQuery<PipelineStatus>({
    queryKey: pipelineKey(projectId),
    queryFn: ({ signal }) => api.pipeline.get(projectId, { signal }),
    refetchInterval: (query) => (query.state.data?.stage === 'running' ? 3000 : false),
  });
  const stage = q.data?.stage;
  const prev = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (prev.current === 'running' && stage !== undefined && stage !== 'running') {
      void refreshReviewData(qc, projectId);
    }
    prev.current = stage;
  }, [stage, qc, projectId]);
  return q;
}

/** 评审报告；还没有完成的评审（404 report_not_ready）时 data 为 null，不当作错误。 */
export function useReport(projectId: string) {
  return useQuery<Report | null>({
    queryKey: reportKey(projectId),
    queryFn: async ({ signal }) => {
      try {
        return await api.report.get(projectId, { signal });
      } catch (e) {
        if (isApiError(e) && e.kind === 'not_found' && e.is('report_not_ready')) return null;
        throw e;
      }
    },
  });
}

/** 重新评审：基于最新资料、规则与事实再走一遍，已完成且输入没变的环节不会重做。 */
export function useRestartAnalysis(projectId: string) {
  const qc = useQueryClient();
  return useIdempotentAction((_: null, o) => api.pipeline.restart(projectId, o), {
    onSuccess: async (status) => {
      qc.setQueryData(pipelineKey(projectId), status);
      await refreshReviewData(qc, projectId);
    },
    onError: () => refreshReviewData(qc, projectId),
  });
}
