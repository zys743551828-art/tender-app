import * as TabsPrimitive from '@radix-ui/react-tabs';
import type { ReactNode } from 'react';
import { cn } from '../lib/cn';

export interface TabDef {
  id: string;
  label: ReactNode;
  panel: ReactNode;
}

/** 标签页（Radix）：左右键、Home／End 切换并即时激活；下划线式，和页面标题对齐。 */
export function Tabs({
  tabs,
  active,
  onChange,
  label,
  className,
}: {
  tabs: TabDef[];
  active: string;
  onChange: (id: string) => void;
  label: string;
  className?: string;
}) {
  const current = tabs.some((t) => t.id === active) ? active : (tabs[0]?.id ?? '');
  return (
    <TabsPrimitive.Root value={current} onValueChange={onChange} className={className}>
      <TabsPrimitive.List
        aria-label={label}
        className="mb-5 flex gap-5 overflow-x-auto border-b border-border"
      >
        {tabs.map((t) => (
          <TabsPrimitive.Trigger
            key={t.id}
            value={t.id}
            className={cn(
              '-mb-px inline-flex h-10 cursor-pointer items-center gap-1.5 border-b-2 border-transparent text-sm whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground',
              'data-[state=active]:border-foreground data-[state=active]:font-medium data-[state=active]:text-foreground',
            )}
          >
            {t.label}
          </TabsPrimitive.Trigger>
        ))}
      </TabsPrimitive.List>
      {tabs.map((t) =>
        t.id === current ? (
          <TabsPrimitive.Content key={t.id} value={t.id} className="focus-visible:outline-none">
            {t.panel}
          </TabsPrimitive.Content>
        ) : null,
      )}
    </TabsPrimitive.Root>
  );
}
