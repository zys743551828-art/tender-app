import { useQuery, useQueryClient } from '@tanstack/react-query';
import { createContext, useContext, useEffect, useMemo, useReducer, type ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { api } from '../../api/endpoints';
import { apiClient } from '../../api/client';
import { isApiError } from '../../api/errors';
import type { Me } from '../../api/types';
import { Loading, ErrorNotice } from '../../components/ui';

export const ME_KEY = ['me'] as const;

interface AuthValue {
  me: Me;
}
const AuthCtx = createContext<AuthValue | null>(null);

export function useAuth(): AuthValue {
  const v = useContext(AuthCtx);
  if (!v) throw new Error('useAuth 必须在 RequireAuth 内使用');
  return v;
}

/**
 * 会话只靠 httpOnly cookie；csrf_token 只放内存（ApiClient），不进 localStorage。
 * me 查询返回 null 表示"未登录"（401 属于正常结果，不是异常）。
 */
export function useMeQuery() {
  return useQuery<Me | null>({
    queryKey: ME_KEY,
    queryFn: async ({ signal }) => {
      try {
        const me = await api.auth.me({ signal });
        apiClient.setCsrfToken(me.csrf_token);
        return me;
      } catch (e) {
        if (isApiError(e) && e.kind === 'auth') {
          apiClient.setCsrfToken(null);
          return null;
        }
        throw e;
      }
    },
    staleTime: 5 * 60_000,
    retry: (n, e) => !(isApiError(e) && !e.retryable) && n < 2,
  });
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const loc = useLocation();
  const q = useMeQuery();
  const [, rebind] = useReducer((n: number) => n + 1, 0);

  // 任意接口返回 401：清掉身份缓存，下面的 Navigate 随即带回登录页。
  useEffect(() => {
    apiClient.onUnauthorized = () => {
      // 会话失效：上一位用户的项目、问题等缓存一并丢弃，再标记未登录。
      qc.clear();
      qc.setQueryData(ME_KEY, null);
      // clear() 会让现有观察者脱离缓存；强制重渲染，让 useMeQuery 重新绑定到“未登录”的结果。
      rebind();
    };
    return () => {
      apiClient.onUnauthorized = undefined;
    };
  }, [qc]);

  const value = useMemo(() => (q.data ? { me: q.data } : null), [q.data]);

  if (q.isPending) return <Loading label="正在确认登录状态…" />;
  if (q.isError) {
    return (
      <main className="mx-auto max-w-lg px-4 py-16">
        <ErrorNotice error={q.error} title="无法确认登录状态" onRetry={() => void q.refetch()} />
      </main>
    );
  }
  if (!value) {
    const next = loc.pathname + loc.search;
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />;
  }
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

/** 只允许站内相对路径，避免登录后被重定向到外站。 */
export function safeNext(raw: string | null): string {
  if (!raw?.startsWith('/') || raw.startsWith('//') || raw.startsWith('/\\')) return '/projects';
  if (raw.startsWith('/login')) return '/projects';
  return raw;
}
