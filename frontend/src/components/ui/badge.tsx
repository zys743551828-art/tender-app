import { cva, type VariantProps } from 'class-variance-authority';
import type { HTMLAttributes } from 'react';
import { cn } from '../../lib/cn';

/** 状态标签：浅底深字、无边框；只在状态需要醒目时使用，能用一句话说清的不用标签。 */
export const badgeVariants = cva(
  'inline-flex items-center gap-1 whitespace-nowrap rounded-sm px-1.5 py-px text-xs font-medium leading-5 [&_svg]:size-3',
  {
    variants: {
      tone: {
        neutral: 'bg-muted text-muted-foreground',
        gray: 'bg-muted text-muted-foreground',
        blue: 'bg-primary-soft text-primary-soft-foreground',
        green: 'bg-success-soft text-success-foreground',
        amber: 'bg-warning-soft text-warning-foreground',
        red: 'bg-danger-soft text-danger-foreground',
        ai: 'bg-ai-soft text-ai-foreground',
      },
    },
    defaultVariants: { tone: 'neutral' },
  },
);

export function Badge({
  className,
  tone,
  ...props
}: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return (
    <span
      data-tone={tone ?? 'neutral'}
      className={cn(badgeVariants({ tone }), className)}
      {...props}
    />
  );
}
