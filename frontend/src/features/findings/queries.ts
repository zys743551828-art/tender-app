import {
  keepPreviousData,
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { api } from '../../api/endpoints';
import type {
  Finding,
  InputSnapshot,
  ReviewRequest,
  Revision,
  RevisionDiff,
  RevisionRequest,
  Task,
} from '../../api/types';
import { useIdempotentAction } from '../../lib/useIdempotentAction';
import { invalidateProject } from '../projects/queries';
import { taskKeys } from '../tasks/queries';

export const findingKeys = {
  /** 前缀：失效它会同时失效所有筛选条件下的问题列表。 */
  list: (projectId: string) => ['projects', projectId, 'findings'] as const,
  filtered: (projectId: string, f: FindingFilter) =>
    [
      'projects',
      projectId,
      'findings',
      f.snapshotId ?? null,
      f.status ?? null,
      f.category ?? null,
    ] as const,
};

/** 由服务端筛选的条件：评审输入、状态、问题分类。 */
export interface FindingFilter {
  snapshotId?: string;
  status?: string;
  category?: string;
}

export function useFindings(
  projectId: string,
  filter: FindingFilter = {},
  options: { enabled?: boolean } = {},
) {
  return useInfiniteQuery({
    queryKey: findingKeys.filtered(projectId, filter),
    queryFn: ({ pageParam }) =>
      api.findings.list(projectId, {
        cursor: pageParam,
        limit: 25,
        snapshotId: filter.snapshotId,
        status: filter.status,
        category: filter.category,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.nextCursor,
    // 切换筛选时保留旧列表直到新结果到达：否则整个列表（含筛选下拉）会卸载重建，焦点丢失。
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
  });
}

/** 审核的 object_version：问题当前的 revision。 */
export function findingObjectVersion(f: Finding): string {
  return String(f.revision);
}

export function useReviewFinding(projectId: string, finding: Finding, onDone?: () => void) {
  const qc = useQueryClient();
  return useIdempotentAction(
    (v: Pick<ReviewRequest, 'decision' | 'reason'>, o) =>
      api.findings.review(
        finding.finding_id,
        {
          object_version: findingObjectVersion(finding),
          decision: v.decision,
          ...(v.reason ? { reason: v.reason } : {}),
        },
        o,
      ),
    {
      onSuccess: async () => {
        await Promise.all([
          qc.invalidateQueries({ queryKey: findingKeys.list(projectId) }),
          invalidateProject(qc, projectId),
        ]);
        onDone?.();
      },
    },
  );
}

export const revisionKeys = {
  list: (projectId: string) => ['projects', projectId, 'revisions'] as const,
};

export function useRevisions(projectId: string) {
  return useQuery<Revision[]>({
    queryKey: revisionKeys.list(projectId),
    queryFn: ({ signal }) => api.revisions.list(projectId, { signal }),
  });
}

/** 差异正文（产物不可变）；展开建议时才读取。 */
export function useRevisionDiff(revisionId: string, enabled: boolean) {
  return useQuery<RevisionDiff>({
    queryKey: ['revisions', revisionId, 'diff'],
    queryFn: ({ signal }) => api.revisions.diff(revisionId, { signal }),
    enabled,
    staleTime: Infinity,
  });
}

/** 本轮评审的输入不可变；改稿的底稿版本就是其中的正文版本。 */
export function useSnapshot(snapshotId: string) {
  return useQuery<InputSnapshot>({
    queryKey: ['snapshots', snapshotId],
    queryFn: () => api.snapshots.get(snapshotId),
    enabled: snapshotId !== '',
    staleTime: Infinity,
  });
}

/** 发起改稿建议：202 返回任务（不是 Revision），完成后到 revisions.list 取建议。 */
export function useProposeRevision(projectId: string, onStarted: (t: Task) => void) {
  const qc = useQueryClient();
  return useIdempotentAction((b: RevisionRequest, o) => api.revisions.propose(projectId, b, o), {
    onSuccess: async (t) => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: taskKeys.list(projectId) }),
        invalidateProject(qc, projectId),
      ]);
      onStarted(t);
    },
  });
}

/** 采纳/驳回后刷新建议与问题（采纳会让相关问题变为 revision_pending）。 */
async function refreshAfterReview(qc: ReturnType<typeof useQueryClient>, projectId: string) {
  await Promise.all([
    qc.invalidateQueries({ queryKey: revisionKeys.list(projectId) }),
    qc.invalidateQueries({ queryKey: findingKeys.list(projectId) }),
    invalidateProject(qc, projectId),
  ]);
}

export function useAdoptRevision(projectId: string, onDone: (r: Revision) => void) {
  const qc = useQueryClient();
  return useIdempotentAction(
    (r: Revision, o) =>
      api.revisions.adopt(
        r.revision_id,
        { base_version_id: r.base_version_id, edited_diff_artifact_id: null },
        o,
      ),
    {
      onSuccess: async (r) => {
        await refreshAfterReview(qc, projectId);
        onDone(r);
      },
      // 建议已过期或已被别人处理：刷新列表，让页面显示最新状态。
      onError: () => refreshAfterReview(qc, projectId),
    },
  );
}

export function useRejectRevision(projectId: string, onDone: (r: Revision) => void) {
  const qc = useQueryClient();
  return useIdempotentAction(
    (v: { revision: Revision; reason: string }, o) =>
      api.revisions.reject(
        v.revision.revision_id,
        { base_version_id: v.revision.base_version_id, reason: v.reason },
        o,
      ),
    {
      onSuccess: async (r) => {
        await refreshAfterReview(qc, projectId);
        onDone(r);
      },
      onError: () => refreshAfterReview(qc, projectId),
    },
  );
}
