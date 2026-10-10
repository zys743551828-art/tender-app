import { Link, Outlet, useOutletContext, useParams } from 'react-router-dom';
import type { Project } from '../api/types';
import { isApiError } from '../api/errors';
import { EmptyState, ErrorNotice, Loading } from '../components/ui';
import { Button } from '../components/ui/button';
import { useProject } from '../features/projects/queries';

export interface ProjectContext {
  project: Project;
}

export function useProjectContext(): ProjectContext {
  return useOutletContext<ProjectContext>();
}

export function ProjectLayout() {
  const { projectId } = useParams();
  const q = useProject(projectId);
  if (q.isPending) return <Loading label="正在打开项目…" />;
  if (q.isError) {
    // 404：项目不存在。
    if (isApiError(q.error) && q.error.kind === 'not_found') {
      return (
        <EmptyState
          title="找不到这个项目"
          action={
            <Button asChild>
              <Link to="/projects">回到全部项目</Link>
            </Button>
          }
        >
          地址可能有误，或项目已被删除。
        </EmptyState>
      );
    }
    return <ErrorNotice error={q.error} onRetry={() => void q.refetch()} title="项目无法打开" />;
  }
  return <Outlet context={{ project: q.data } satisfies ProjectContext} />;
}
