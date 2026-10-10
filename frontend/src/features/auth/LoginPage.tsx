import { useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../../api/endpoints';
import { apiClient } from '../../api/client';
import { ErrorNotice, Field } from '../../components/ui';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Icon } from '../../components/Icon';
import { useIdempotentAction } from '../../lib/useIdempotentAction';
import { ME_KEY, safeNext, useMeQuery } from './auth';

export function LoginPage() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const next = safeNext(params.get('next'));
  const meQ = useMeQuery();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [touched, setTouched] = useState(false);

  const login = useIdempotentAction(
    (v: { username: string; password: string }, o) => api.auth.login(v, o),
    {
      onSuccess: (me) => {
        apiClient.setCsrfToken(me.csrf_token);
        qc.setQueryData(ME_KEY, me);
        nav(next, { replace: true });
      },
    },
  );

  // 已登录用户直接进入工作区。
  if (meQ.data) return <Navigate to={next} replace />;

  const userErr = touched && !username.trim() ? '请输入账号' : null;
  const passErr = touched && !password ? '请输入密码' : null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (!username.trim() || !password) return;
    login.mutate({ username: username.trim(), password });
  };

  return (
    <main
      id="main"
      className="relative flex min-h-dvh items-center justify-center overflow-hidden bg-background px-4 py-10"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 [background:radial-gradient(60%_50%_at_50%_0%,var(--primary-soft),transparent_70%)]"
      />
      <div className="relative w-full max-w-[380px]">
        <div className="mb-8 flex items-center gap-2.5">
          <span className="inline-flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground shadow-sm">
            <Icon name="Building2" size={17} />
          </span>
          <span className="text-[15px] font-semibold">施组工作台</span>
        </div>
        <div className="rounded-xl border border-border bg-card p-7 shadow-sm">
          <h1 className="text-lg font-semibold tracking-tight">登录</h1>
          <p className="mt-1 mb-6 text-[13px] text-muted-foreground">
            查出施组里的废标风险，估计技术分，找到最值得改的地方。
          </p>
          <form onSubmit={submit} noValidate>
            <Field label="账号" error={userErr}>
              {(p) => (
                <Input
                  {...p}
                  type="text"
                  autoComplete="username"
                  value={username}
                  onChange={(e) => {
                    setUsername(e.target.value);
                  }}
                />
              )}
            </Field>
            <Field label="密码" error={passErr}>
              {(p) => (
                <Input
                  {...p}
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => {
                    setPassword(e.target.value);
                  }}
                />
              )}
            </Field>
            {login.isError ? <ErrorNotice error={login.error} title="登录没有成功" /> : null}
            <Button
              type="submit"
              variant="primary"
              className="mt-2 w-full"
              disabled={login.isPending}
            >
              {login.isPending ? '正在登录…' : '登录'}
            </Button>
          </form>
        </div>
      </div>
    </main>
  );
}
