import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { useEffect, useRef, type ReactNode } from 'react';
import { cn } from '../lib/cn';

/**
 * 模态对话框（Radix）：焦点陷阱、Esc 与点遮罩关闭、关闭后焦点回到打开前的元素，读屏读出标题。
 * 由调用方决定何时挂载（挂载即打开）；带 data-autofocus 的控件优先获得焦点。
 */
export function Dialog({
  title,
  description,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  description?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  // 由调用方挂载与卸载、没有 Radix Trigger：记住打开前的焦点，卸载时立即还回去。
  const opener = useRef<HTMLElement | null>(
    document.activeElement instanceof HTMLElement ? document.activeElement : null,
  );
  useEffect(
    () => () => {
      if (opener.current?.isConnected) opener.current.focus();
    },
    [],
  );
  return (
    <DialogPrimitive.Root
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 animate-in bg-overlay backdrop-blur-[2px]" />
        <DialogPrimitive.Content
          onOpenAutoFocus={(e) => {
            const el = (e.currentTarget as HTMLElement | null)?.querySelector<HTMLElement>(
              '[data-autofocus]',
            );
            if (el) {
              e.preventDefault();
              el.focus();
            }
          }}
          className={cn(
            'fixed top-1/2 left-1/2 z-50 flex max-h-[calc(100dvh-32px)] w-[calc(100%-32px)] -translate-x-1/2 -translate-y-1/2 animate-in flex-col overflow-y-auto rounded-xl border border-border bg-popover p-6 shadow-lg focus:outline-none',
            wide ? 'max-w-3xl' : 'max-w-lg',
          )}
        >
          <div className="mb-4 flex items-start justify-between gap-4">
            <div>
              <DialogPrimitive.Title className="text-base font-semibold">
                {title}
              </DialogPrimitive.Title>
              {description ? (
                <DialogPrimitive.Description className="mt-1 text-[13px] text-muted-foreground">
                  {description}
                </DialogPrimitive.Description>
              ) : (
                <DialogPrimitive.Description className="sr-only">
                  {title}
                </DialogPrimitive.Description>
              )}
            </div>
            <DialogPrimitive.Close
              aria-label="关闭"
              className="-mt-1 -mr-2 inline-flex size-8 cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <X className="size-4" />
            </DialogPrimitive.Close>
          </div>
          {children}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/** 对话框底部操作区：次要在左、主要在右。 */
export function DialogActions({ children }: { children: ReactNode }) {
  return <div className="mt-6 flex flex-wrap justify-end gap-2">{children}</div>;
}
