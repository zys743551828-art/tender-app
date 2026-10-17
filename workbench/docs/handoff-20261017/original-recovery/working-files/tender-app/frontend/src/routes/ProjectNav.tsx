import { NavLink, useLocation } from 'react-router-dom';
import type { Project } from '../api/types';
import { Icon, type IconName } from '../components/Icon';
import { cn } from '../lib/cn';
import { deadlineText } from '../lib/format';
import { projectStateLabel } from '../lib/labels';

/** 常用页面直接显示，其他页面从更多功能或报告中的具体操作进入。 */
export const PROJECT_PAGES: { path: string; label: string; icon: IconName; end?: boolean }[] = [
  { path: '', label: '评审报告', icon: 'LayoutDashboard', end: true },
  { path: 'materials', label: '上传资料', icon: 'FolderOpen' },
  { path: 'findings', label: '处理问题', icon: 'ListChecks' },
  { path: 'basis', label: '依据', icon: 'FileCheck2' },
  { path: 'price', label: '报价', icon: 'ChartNoAxesCombined' },
  { path: 'submit', label: '提交与结果', icon: 'Flag' },
];
export const PROJECT_TOOLS: { path: string; label: string; icon: IconName }[] = [
  { path: 'search', label: '检索', icon: 'Search' },
  { path: 'settings', label: '设置', icon: 'Settings' },
];

export function visiblePages(project: Project) {
  return PROJECT_PAGES.filter((p) => p.path !== 'price' || project.settings.price);
}

export function SideLink({
  to,
  end,
  icon,
  label,
  onNavigate,
}: {
  to: string;
  end?: boolean;
  icon: IconName;
  label: string;
  onNavigate: () => void;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          'flex h-8 items-center gap-2.5 rounded-md px-2 text-[13px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground',
          isActive && 'bg-card font-medium text-foreground shadow-xs ring-1 ring-border',
        )
      }
    >
      <Icon name={icon} />
      <span className="min-w-0 flex-1 truncate">{label}</span>
    </NavLink>
  );
}

const PRIMARY_PATHS = new Set(['', 'materials', 'findings']);

/** 三个常用入口；访问其他页面时自动展开更多功能，保留当前位置。 */
export function ProjectNav({ project, onNavigate }: { project: Project; onNavigate: () => void }) {
  const location = useLocation();
  const base = `/projects/${project.project_id}`;
  const deadline = deadlineText(project.deadline);
  const pages = visiblePages(project);
  const extra = [...pages.filter((p) => !PRIMARY_PATHS.has(p.path)), ...PROJECT_TOOLS];
  const moreActive = extra.some((p) => location.pathname === `${base}/${p.path}`);
  return (
    <>
      <div className="px-2" aria-label="当前项目">
        <p className="m-0 text-[13px] leading-snug font-semibold break-words">{project.title}</p>
        <p
          className={cn(
            'm-0 mt-0.5 text-xs text-muted-foreground',
            deadline.urgent && 'text-danger-foreground',
          )}
        >
          {projectStateLabel(project.state)}
          {project.deadline ? ` · ${deadline.text}` : ''}
        </p>
      </div>
      <nav className="flex flex-col gap-0.5" aria-label="项目导航">
        {pages
          .filter((p) => PRIMARY_PATHS.has(p.path))
          .map((p) => (
            <SideLink
              key={p.label}
              to={p.path ? `${base}/${p.path}` : base}
              end={p.end}
              icon={p.icon}
              label={p.label}
              onNavigate={onNavigate}
            />
          ))}
      </nav>
      <details key={location.pathname} open={moreActive} className="group">
        <summary className="cursor-pointer rounded-md px-2 py-2 text-[13px] text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">
          更多功能
        </summary>
        <nav className="mt-1 flex flex-col gap-0.5" aria-label="项目工具">
          {extra.map((p) => (
            <SideLink
              key={p.label}
              to={`${base}/${p.path}`}
              icon={p.icon}
              label={p.label}
              onNavigate={onNavigate}
            />
          ))}
        </nav>
      </details>
    </>
  );
}
