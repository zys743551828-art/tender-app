import { useMemo, type ReactNode } from 'react';
import { Toaster, toast } from 'sonner';

interface ToastApi {
  notify: (message: string) => void;
}

/** 操作结果的轻提示：右下角、几秒后自动消失，读屏以 polite 方式播报。 */
export function ToastProvider({ children }: { children: ReactNode }) {
  return (
    <>
      {children}
      <Toaster
        position="bottom-right"
        toastOptions={{
          className:
            '!rounded-lg !border !border-border !bg-popover !text-foreground !shadow-lg !text-[13px] !font-sans',
        }}
      />
    </>
  );
}

export function useToast(): ToastApi {
  return useMemo(() => ({ notify: (message: string) => toast(message) }), []);
}
