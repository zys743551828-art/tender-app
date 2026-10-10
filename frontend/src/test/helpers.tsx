import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { apiClient } from '../api/client';
import { App } from '../routes/App';
import {
  DEFAULT_PROJECT_SETTINGS,
  type Me,
  type Project,
  type ProjectOverview,
  type ProjectSummary,
} from '../api/types';

export const ME: Me = {
  member_id: 'mem-1',
  display_name: '张工',
  csrf_token: 'csrf-abc',
};

export function project(over: Partial<Project> = {}): Project {
  return {
    project_id: 'prj-1',
    title: '城市支路及排水改造',
    tender_number: 'ZB-2026-018',
    lot: '一标段',
    round: 1,
    region: '上海',
    engineering_type: '市政道路',
    deadline: null,
    state: 'issues_open',
    revision: 3,
    owner_id: 'mem-1',
    created_at: '2026-10-01T08:00:00Z',
    settings: DEFAULT_PROJECT_SETTINGS,
    ...over,
  };
}

/** 总览列表里的项目：默认还没有评审，下一步是上传资料。 */
export function overview(
  over: Partial<Project> = {},
  summary: Partial<ProjectSummary> = {},
): ProjectOverview {
  return {
    ...project(over),
    summary: {
      reviewed: false,
      qualification_open: 0,
      prediction: null,
      next_action: {
        key: 'upload_materials',
        title: '上传招标文件、施组正文',
        detail: '招标文件和施组正文都到齐后自动开始评审。',
        target: 'materials',
        count: null,
      },
      ...summary,
    },
  };
}

export function renderApp(path: string) {
  return renderAppWithClient(path).result;
}

/** 同 renderApp，另外返回 QueryClient，便于测试里主动让某个查询失效。 */
export function renderAppWithClient(path: string) {
  apiClient.setCsrfToken(null);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 }, mutations: { retry: false } },
  });
  const result = render(
    <QueryClientProvider client={client}>
      <MemoryRouter
        initialEntries={[path]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { result, qc: client };
}

export function apiError(
  code: string,
  message: string,
  extra: Partial<{ retryable: boolean; request_id: string }> = {},
) {
  return {
    code,
    message,
    request_id: extra.request_id ?? 'req-test-1',
    retryable: extra.retryable ?? false,
    details: {},
  };
}
