import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { api } from '../../api/endpoints';
import type { Project, ProjectCreate, ProjectUpdate } from '../../api/types';
import { useIdempotentAction } from '../../lib/useIdempotentAction';

export const projectKeys = {
  all: ['projects'] as const,
  detail: (id: string) => ['projects', id] as const,
};

/**
 * 项目详情（revision、state）会随规则确认、评审、提交等动作变化；这些动作成功后调用它，
 * 否则页面拿着旧 revision 去 PATCH 会得到不必要的 412。
 * detail 的键是其他项目级查询（任务、问题…）的前缀，所以必须 exact，只刷新项目本身与总览列表。
 */
export function invalidateProject(qc: QueryClient, projectId: string): Promise<void> {
  return Promise.all([
    qc.invalidateQueries({ queryKey: projectKeys.detail(projectId), exact: true }),
    qc.invalidateQueries({ queryKey: projectKeys.all, exact: true }),
  ]).then(() => undefined);
}

/** 进入依赖 revision 的页面（设置、成员）时重新读取项目，避免用过期 revision 提交。 */
export function useRefetchProjectOnMount(projectId: string): void {
  const qc = useQueryClient();
  useEffect(() => {
    void qc.invalidateQueries({ queryKey: projectKeys.detail(projectId), exact: true });
  }, [qc, projectId]);
}

export function useProjects() {
  return useQuery({
    queryKey: projectKeys.all,
    queryFn: ({ signal }) => api.projects.list({ signal }),
  });
}

export function useProject(id: string | undefined) {
  return useQuery<Project>({
    queryKey: projectKeys.detail(id ?? ''),
    queryFn: ({ signal }) => api.projects.get(id ?? '', { signal }),
    enabled: Boolean(id),
    retry: (n, e) => n < 1 && !(e instanceof Error && 'kind' in e),
  });
}

export function useCreateProject(onCreated?: (p: Project) => void) {
  const qc = useQueryClient();
  return useIdempotentAction((b: ProjectCreate, o) => api.projects.create(b, o), {
    onSuccess: async (p) => {
      await qc.invalidateQueries({ queryKey: projectKeys.all });
      onCreated?.(p);
    },
  });
}

/** 项目编辑：If-Match 带当前读到的 revision；412 时由页面提示刷新并保留输入。 */
export function useUpdateProject(projectId: string, onUpdated?: (p: Project) => void) {
  const qc = useQueryClient();
  return useIdempotentAction(
    (v: { revision: number; body: ProjectUpdate }, o) =>
      api.projects.update(projectId, v.revision, v.body, o),
    {
      onSuccess: async (p) => {
        qc.setQueryData(projectKeys.detail(projectId), p);
        await qc.invalidateQueries({ queryKey: projectKeys.all });
        onUpdated?.(p);
      },
    },
  );
}
