import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Link, Outlet, useLocation, useMatch, useNavigate } from 'react-router-dom';
import { api } from '../api/endpoints';
import { apiClient } from '../api/client';
import { Icon } from '../components/Icon';
import { ToastProvider } from '../components/Toast';
import { Kbd } from '../components/ui/kbd';
import { TooltipProvider } from '../components/ui/tooltip';
import { ME_KEY, useAuth } from '../features/auth/auth';
import { CommandMenu, useCommandMenu } from '../features/command/CommandMenu';
import { useProject } from '../features/projects/queries';
import { cn } from '../lib/cn';
import { useTheme, type ThemePref } from '../lib/theme';
import { ProjectNav, SideLink } from './ProjectNav';

const THEMES: { value: ThemePref; label: string }[] = [
  { value: 'light', label: '浅色' },
  { value: 'dark', label: '深色' },
  { value: 'system', label: '跟随系统' },
];

const menuItem =
  'flex h-8 cursor-pointer items-center gap-2 rounded-md px-2 text-[13px] outline-none data-[highlighted]:bg-muted [&_svg]:size-4 [&_svg]:text-muted-foreground';

/**
 * 两级导航：全局层是“项目”和“度量”；进入某个项目后，侧栏换成该项目的导航（含“← 全部项目”）。
 * Ctrl／⌘ + K 打开命令面板。窄屏时侧栏收起，由顶部菜单按钮展开。
 */
export function AppShell() {
  const { me } = useAuth();
  const qc = useQueryClient();
  const nav = useNavigate();
  const location = useLocation();
  const match = useMatch('/projects/:projectId/*');
  const projectId = match?.params.projectId;
  const project = useProject(projectId);
  const [open, setOpen] = useState(false);
  const [cmdOpen, setCmdOpen] = useCommandMenu();
  const [theme, setTheme] = useTheme();
  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);

  const logout = async () => {
    try {
      await api.auth.logout();
    } finally {
      apiClient.setCsrfToken(null);
      qc.clear();
      qc.setQueryData(ME_KEY, null);
      nav('/login', { replace: true });
    }
  };
  const p = project.data;
  const close = () => {
    setOpen(false);
  };

  return (
    <TooltipProvider delayDuration={300}>
      <ToastProvider>
        <a
          className="sr-only rounded-md bg-primary px-4 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[100]"
          href="#main"
        >
          跳到工作区
        </a>
        <div className="flex min-h-dvh flex-col lg:flex-row">
          <div className="sticky top-0 z-30 flex h-12 items-center gap-2 border-b border-border bg-sidebar px-2 lg:hidden">
            <button
              type="button"
              className="inline-flex size-9 cursor-pointer items-center justify-center rounded-md hover:bg-muted"
              aria-expanded={open}
              aria-controls="sidebar"
              onClick={() => {
                setOpen((v) => !v);
              }}
            >
              <Icon name="Menu" size={18} />
              <span className="sr-only">{open ? '收起导航' : '展开导航'}</span>
            </button>
            <Link to="/projects" className="text-sm font-semibold text-foreground no-underline">
              施组工作台
            </Link>
          </div>
          <aside
            id="sidebar"
            className={cn(
              'flex-col gap-5 border-border bg-sidebar px-3 pt-4 pb-3 lg:sticky lg:top-0 lg:flex lg:h-dvh lg:w-[232px] lg:shrink-0 lg:overflow-y-auto lg:border-r',
              open ? 'flex border-b' : 'hidden',
            )}
          >
            <Link
              to="/projects"
              className="flex items-center gap-2.5 px-2 text-foreground no-underline"
              aria-label="施组工作台，回到全部项目"
            >
              <span className="inline-flex size-7 items-center justify-center rounded-md bg-primary text-primary-foreground shadow-xs">
                <Icon name="Building2" size={15} />
              </span>
              <span className="leading-tight">
                <span className="block text-[13px] font-semibold">施组工作台</span>
                <span className="block text-[11px] text-muted-foreground">技术标评审与报价</span>
              </span>
            </Link>
            <button
              type="button"
              onClick={() => {
                setCmdOpen(true);
              }}
              className="flex h-8 cursor-pointer items-center gap-2 rounded-md border border-border bg-card px-2 text-[13px] text-muted-foreground shadow-xs hover:text-foreground"
            >
              <Icon name="Search" />
              <span className="flex-1 text-left">搜索或跳转</span>
              <Kbd>Ctrl K</Kbd>
            </button>
            {projectId ? (
              <>
                <Link
                  to="/projects"
                  className="-mb-2 flex items-center gap-1.5 px-2 text-xs text-muted-foreground no-underline hover:text-foreground"
                  onClick={close}
                >
                  <Icon name="ArrowLeft" size={14} />
                  全部项目
                </Link>
                {p ? (
                  <ProjectNav project={p} onNavigate={close} />
                ) : (
                  <p className="px-2 text-xs text-muted-foreground">正在读取项目…</p>
                )}
              </>
            ) : (
              <nav className="flex flex-col gap-0.5" aria-label="主导航">
                <SideLink to="/projects" icon="FolderOpen" label="项目" onNavigate={close} />
                <SideLink to="/metrics" icon="Activity" label="度量" onNavigate={close} />
              </nav>
            )}
            <div className="mt-auto">
              <p className="m-0 px-2 pb-2 text-[11px] leading-relaxed text-muted-foreground">
                AI 产生的内容均为建议，须经人工确认
              </p>
              <DropdownMenu.Root>
                <DropdownMenu.Trigger className="flex h-10 w-full cursor-pointer items-center gap-2.5 rounded-md px-2 text-left hover:bg-muted data-[state=open]:bg-muted">
                  <span
                    aria-hidden="true"
                    className="inline-flex size-6 items-center justify-center rounded-full bg-primary-soft text-xs font-semibold text-primary-soft-foreground"
                  >
                    {me.display_name.slice(0, 1)}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
                    {me.display_name}
                  </span>
                  <Icon name="Settings" className="text-muted-foreground" />
                  <span className="sr-only">账号与外观</span>
                </DropdownMenu.Trigger>
                <DropdownMenu.Portal>
                  <DropdownMenu.Content
                    side="top"
                    align="start"
                    sideOffset={6}
                    className="z-50 w-52 animate-in rounded-lg border border-border bg-popover p-1 shadow-lg"
                  >
                    <DropdownMenu.Label className="px-2 py-1.5 text-[11px] font-medium text-muted-foreground">
                      外观
                    </DropdownMenu.Label>
                    <DropdownMenu.RadioGroup
                      value={theme}
                      onValueChange={(v) => {
                        setTheme(v as ThemePref);
                      }}
                    >
                      {THEMES.map((t) => (
                        <DropdownMenu.RadioItem key={t.value} value={t.value} className={menuItem}>
                          <Icon
                            name={
                              t.value === 'light' ? 'Sun' : t.value === 'dark' ? 'Moon' : 'Monitor'
                            }
                          />
                          <span className="flex-1">{t.label}</span>
                          <DropdownMenu.ItemIndicator>
                            <Icon name="Check" />
                          </DropdownMenu.ItemIndicator>
                        </DropdownMenu.RadioItem>
                      ))}
                    </DropdownMenu.RadioGroup>
                    <DropdownMenu.Separator className="my-1 h-px bg-border" />
                    <DropdownMenu.Item className={menuItem} onSelect={() => void logout()}>
                      <Icon name="LogOut" />
                      退出登录
                    </DropdownMenu.Item>
                  </DropdownMenu.Content>
                </DropdownMenu.Portal>
              </DropdownMenu.Root>
            </div>
          </aside>
          <main id="main" tabIndex={-1} className="min-w-0 flex-1 focus:outline-none">
            <div className="mx-auto w-full max-w-[1200px] px-4 pt-6 pb-16 sm:px-8 sm:pt-8">
              <Outlet />
            </div>
          </main>
        </div>
        <CommandMenu open={cmdOpen} onOpenChange={setCmdOpen} setTheme={setTheme} />
      </ToastProvider>
    </TooltipProvider>
  );
}
