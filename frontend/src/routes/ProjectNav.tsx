import { NavLink } from 'react-router-dom';
import type { Project } from '../api/types';
import { Icon, type IconName } from '../components/Icon';
import { cn } from '../lib/cn';
import { deadlineText } from '../lib/format';
import { projectStateLabel } from '../lib/labels';

/** 项目内页面，顺序即流程：报告是落地页，其后是处理问题、核对依据、报价、提交与结果，资料放在最后。 */
export const PROJECT_PAGES: { path: string; label: string; icon: IconName; end?: boolean }[] = [
  { path: '', label: '报告', icon: 'LayoutDashboard', end: true },
  { path: 'findings', label: '问题', icon: 'ListChecks' },
  { path: 'basis', label: '依据', icon: 'FileCheck2' },
  { path: 'price', label: '报价', icon: 'ChartNoAxesCombined' },
  { path: 'submit', label: '提交与结果', icon: 'Flag' },
  { path: 'materials', label: '资料', icon: 'FolderOpen' },
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

/** 项目层导航：项目名片 + 六个页面 + 工具入口。 */
export function ProjectNav({ project, onNavigate }: { project: Project; onNavigate: () => void }) {
  const base = `/projects/${project.project_id}`;
  const deadline = deadlineText(project.deadline);
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
        {visiblePages(project).map((p) => (
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
      <nav className="flex flex-col gap-0.5" aria-label="项目工具">
        <p className="m-0 px-2 pb-1 text-[11px] font-medium tracking-wide text-muted-foreground">
          工具
        </p>
        {PROJECT_TOOLS.map((p) => (
          <SideLink
            key={p.label}
            to={`${base}/${p.path}`}
            icon={p.icon}
            label={p.label}
            onNavigate={onNavigate}
          />
        ))}
      </nav>
    </>
  );
}
