import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/endpoints';
import type { Outcome, Submission } from '../../api/types';

export const submissionKeys = {
  list: (projectId: string) => ['projects', projectId, 'submissions'] as const,
};
export const outcomeKeys = {
  list: (projectId: string) => ['projects', projectId, 'outcomes'] as const,
};

export function useSubmissions(projectId: string) {
  return useQuery<Submission[]>({
    queryKey: submissionKeys.list(projectId),
    queryFn: ({ signal }) => api.submissions.list(projectId, { signal }),
  });
}

export function useOutcomes(projectId: string) {
  return useQuery<Outcome[]>({
    queryKey: outcomeKeys.list(projectId),
    queryFn: ({ signal }) => api.outcomes.list(projectId, { signal }),
  });
}
