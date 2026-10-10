import { Command } from 'cmdk';
import { useEffect, useState } from 'react';
import { useMatch, useNavigate } from 'react-router-dom';
import { Icon, type IconName } from '../../components/Icon';
import { Kbd } from '../../components/ui/kbd';
import type { ThemePref } from '../../lib/theme';
import { useProject, useProjects } from '../projects/queries';
import { PROJECT_TOOLS, visiblePages } from '../../routes/ProjectNav';

const item =
  'flex h-9 cursor-pointer items-center gap-2.5 rounded-md px-2.5 text-[13px] text-foreground aria-selected:bg-muted [&_svg]:text-muted-foreground';
const group =
  '[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground';

/** Ctrl／⌘ + K：跳转到项目或页面、切换主题。 */
export function useCommandMenu(): [boolean, (open: boolean) => void] {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
    };
  }, []);
  return [open, setOpen];
}

function Row({
  icon,
  label,
  onSelect,
  hint,
}: {
  icon: IconName;
  label: string;
  onSelect: () => void;
  hint?: string;
}) {
  return (
    <Command.Item value={`${label} ${hint ?? ''}`} onSelect={onSelect} className={item}>
      <Icon name={icon} />
      <span className="flex-1 truncate">{label}</span>
      {hint ? (
        <span className="max-w-[45%] truncate text-xs text-muted-foreground">{hint}</span>
      ) : null}
    </Command.Item>
  );
}

export function CommandMenu({
  open,
  onOpenChange,
  setTheme,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  setTheme: (p: ThemePref) => void;
}) {
  const nav = useNavigate();
  const match = useMatch('/projects/:projectId/*');
  const project = useProject(match?.params.projectId).data;
  const projects = useProjects();
  const go = (to: string) => {
    onOpenChange(false);
    nav(to);
  };
  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label="搜索或跳转"
      overlayClassName="fixed inset-0 z-50 bg-overlay backdrop-blur-[2px]"
      contentClassName="fixed top-[18vh] left-1/2 z-50 w-[calc(100%-32px)] max-w-xl -translate-x-1/2 animate-in overflow-hidden rounded-xl border border-border bg-popover shadow-lg"
    >
      <div className="flex items-center gap-2 border-b border-border px-3.5">
        <Icon name="Search" className="text-muted-foreground" />
        <Command.Input
          placeholder="搜索项目、页面或操作…"
          className="h-12 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
        />
        <Kbd>Esc</Kbd>
      </div>
      <Command.List className="max-h-[360px] overflow-y-auto p-1.5">
        <Command.Empty className="py-8 text-center text-[13px] text-muted-foreground">
          没有匹配的结果
        </Command.Empty>
        {project ? (
          <Command.Group heading={project.title} className={group}>
            {[...visiblePages(project), ...PROJECT_TOOLS].map((p) => (
              <Row
                key={p.label}
                icon={p.icon}
                label={p.label}
                onSelect={() => {
                  go(`/projects/${project.project_id}${p.path ? `/${p.path}` : ''}`);
                }}
              />
            ))}
          </Command.Group>
        ) : null}
        <Command.Group heading="项目" className={group}>
          {(projects.data ?? []).slice(0, 30).map((p) => (
            <Row
              key={p.project_id}
              icon="Building2"
              label={p.title}
              hint={p.summary.next_action?.title}
              onSelect={() => {
                go(`/projects/${p.project_id}`);
              }}
            />
          ))}
        </Command.Group>
        <Command.Group heading="前往" className={group}>
          <Row
            icon="FolderOpen"
            label="全部项目"
            onSelect={() => {
              go('/projects');
            }}
          />
          <Row
            icon="Activity"
            label="度量"
            onSelect={() => {
              go('/metrics');
            }}
          />
        </Command.Group>
        <Command.Group heading="外观" className={group}>
          <Row
            icon="Sun"
            label="浅色"
            onSelect={() => {
              setTheme('light');
              onOpenChange(false);
            }}
          />
          <Row
            icon="Moon"
            label="深色"
            onSelect={() => {
              setTheme('dark');
              onOpenChange(false);
            }}
          />
          <Row
            icon="Monitor"
            label="跟随系统"
            onSelect={() => {
              setTheme('system');
              onOpenChange(false);
            }}
          />
        </Command.Group>
      </Command.List>
    </Command.Dialog>
  );
}
