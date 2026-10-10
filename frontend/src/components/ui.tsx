import { useId, type ReactNode } from 'react';
import { describeError } from '../api/errors';
import { cn } from '../lib/cn';
import type { Tone } from '../lib/labels';
import { Icon, type IconName } from './Icon';
import { Badge } from './ui/badge';
import { Skeleton } from './ui/skeleton';

export function Tag({
  tone = 'neutral',
  children,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Badge tone={tone} className={className}>
      {children}
    </Badge>
  );
}

/** AI 产生、尚未人工确认的内容固定使用靛蓝标识；人工确认后调用方不再渲染它。 */
export function AiBadge({ children = 'AI 建议 · 待人工确认' }: { children?: ReactNode }) {
  return (
    <Badge tone="ai">
      <Icon name="Sparkles" />
      {children}
    </Badge>
  );
}

export function PageHead({
  title,
  lede,
  actions,
}: {
  title: string;
  lede?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {lede ? (
          <p className="mt-1 max-w-[68ch] text-[13px] text-muted-foreground">{lede}</p>
        ) : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}

/** 加载中：骨架占位，读屏读出文字。 */
export function Loading({ label = '加载中…', rows = 3 }: { label?: string; rows?: number }) {
  return (
    <div role="status" className="flex flex-col gap-2.5 py-2">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={cn('h-4', i === rows - 1 ? 'w-2/5' : 'w-full')} />
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  children,
  action,
  icon = 'FolderOpen',
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  icon?: IconName;
}) {
  return (
    <div className="mb-5 flex flex-col items-center gap-2 rounded-lg border border-dashed border-border-strong px-6 py-12 text-center">
      <span className="mb-1 inline-flex size-10 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <Icon name={icon} size={18} />
      </span>
      <h2 className="text-[15px] font-semibold">{title}</h2>
      {children ? (
        <p className="max-w-[46ch] text-[13px] text-muted-foreground">{children}</p>
      ) : null}
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  );
}

type AlertTone = 'danger' | 'warning' | 'info' | 'ai' | 'success';
const ALERT: Record<AlertTone, { box: string; icon: IconName }> = {
  danger: {
    box: 'border-danger-border bg-danger-soft text-danger-foreground',
    icon: 'CircleAlert',
  },
  warning: {
    box: 'border-warning-border bg-warning-soft text-warning-foreground',
    icon: 'TriangleAlert',
  },
  info: { box: 'border-border bg-subtle text-foreground', icon: 'Info' },
  ai: { box: 'border-ai-border bg-ai-soft text-ai-foreground', icon: 'Sparkles' },
  success: {
    box: 'border-success-border bg-success-soft text-success-foreground',
    icon: 'CircleCheck',
  },
};

/** 提示条：图标 + 文字，颜色只是辅助。 */
export function Alert({
  tone = 'info',
  children,
  role = 'note',
  className,
  action,
}: {
  tone?: AlertTone;
  children: ReactNode;
  role?: 'note' | 'alert' | 'status';
  className?: string;
  action?: ReactNode;
}) {
  const a = ALERT[tone];
  return (
    <div
      role={role}
      data-tone={tone}
      className={cn('mb-4 flex gap-3 rounded-lg border px-4 py-3 text-[13px]', a.box, className)}
    >
      <Icon name={a.icon} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1 [&_p]:m-0 [&_strong]:font-semibold">{children}</div>
      {action ? <div className="shrink-0 self-center">{action}</div> : null}
    </div>
  );
}

/** 错误展示：中文 message + 请求编号（便于报障）+ 可选重试。 */
export function ErrorNotice({
  error,
  onRetry,
  title,
  hint,
}: {
  error: unknown;
  onRetry?: () => void;
  title?: string;
  /** 接下来怎么做（后端 message 之外的一句话指引）。 */
  hint?: string | null;
}) {
  const d = describeError(error);
  return (
    <Alert tone="danger" role="alert">
      <strong>{title ?? '操作没有完成'}</strong>
      <p>{d.message}</p>
      {hint ? <p>{hint}</p> : null}
      {d.requestId || (onRetry && d.retryable) ? (
        <p className="mt-1 flex items-center gap-4 text-xs opacity-80">
          {d.requestId ? <span>请求编号 {d.requestId}</span> : null}
          {onRetry && d.retryable ? (
            <button
              type="button"
              className="cursor-pointer font-medium underline underline-offset-2"
              onClick={onRetry}
            >
              重试
            </button>
          ) : null}
        </p>
      ) : null}
    </Alert>
  );
}

export function Notice({
  children,
  tone = 'signal',
}: {
  children: ReactNode;
  tone?: 'signal' | 'ai' | 'plain';
}) {
  return (
    <Alert tone={tone === 'signal' ? 'warning' : tone === 'ai' ? 'ai' : 'info'}>{children}</Alert>
  );
}

/** 标签与控件关联；错误文字通过 aria-describedby 关联并 aria-invalid。 */
export function Field({
  label,
  error,
  hint,
  children,
  className,
}: {
  label: string;
  error?: string | null;
  hint?: string;
  children: (p: { id: string; 'aria-invalid'?: true; 'aria-describedby'?: string }) => ReactNode;
  className?: string;
}) {
  const id = useId();
  const descId = `${id}-d`;
  const describedBy = error || hint ? descId : undefined;
  return (
    <div className={cn('mb-4 flex min-w-0 flex-col gap-1.5', className)}>
      <label htmlFor={id} className="text-[13px] font-medium">
        {label}
      </label>
      {children({
        id,
        ...(error ? { 'aria-invalid': true as const } : {}),
        ...(describedBy ? { 'aria-describedby': describedBy } : {}),
      })}
      {error ? (
        <p id={descId} className="m-0 text-xs font-medium text-danger-foreground">
          {error}
        </p>
      ) : hint ? (
        <p id={descId} className="m-0 text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export function ProgressBar({
  value,
  label,
  className,
}: {
  value: number;
  label: string;
  className?: string;
}) {
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  return (
    <div
      className={cn('h-1.5 w-full overflow-hidden rounded-full bg-muted', className)}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
    >
      <span
        className="block h-full rounded-full bg-primary transition-[width] duration-300"
        style={{ width: `${String(pct)}%` }}
      />
    </div>
  );
}

/** 一组“名称—数值”：卡片和页头里的关键数字。 */
export function Stat({
  label,
  value,
  sub,
  tone,
}: {
  label: ReactNode;
  value: ReactNode;
  sub?: ReactNode;
  tone?: 'danger';
}) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          'm-0 mt-0.5 text-lg font-semibold tracking-tight tabular',
          tone === 'danger' && 'text-danger-foreground',
        )}
      >
        {value}
      </dd>
      {sub ? <dd className="m-0 text-xs text-muted-foreground">{sub}</dd> : null}
    </div>
  );
}
