import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { AssistantWorkspace } from "./AssistantWorkspace";

export function AssistantDrawer({
  bidId,
  memberId,
  onClose,
}: {
  bidId: string;
  memberId: string;
  onClose: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    close.current?.focus();
    function keydown(event: KeyboardEvent) {
      const dialogs = document.querySelectorAll('[role="dialog"]');
      if (dialogs[dialogs.length - 1] !== panel.current) return;
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const elements = [
        ...(panel.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled),a[href],input:not(:disabled),textarea:not(:disabled),select:not(:disabled),[tabindex="0"]',
        ) ?? []),
      ].filter((element) => element.getClientRects().length > 0);
      const first = elements[0],
        last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (
        !event.shiftKey &&
        (document.activeElement === last ||
          !panel.current?.contains(document.activeElement))
      ) {
        event.preventDefault();
        first?.focus();
      }
    }
    window.addEventListener("keydown", keydown);
    window.addEventListener("session-expired", onClose);
    return () => {
      window.removeEventListener("keydown", keydown);
      window.removeEventListener("session-expired", onClose);
      document.body.style.overflow = overflow;
      before?.focus();
    };
  }, [onClose]);
  return createPortal(
    <div className="retrieval-backdrop assistant-backdrop">
      <div
        className="assistant-drawer"
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label="项目主会话助手"
      >
        <header className="retrieval-heading">
          <div>
            <span className="eyebrow">同一主会话</span>
            <h2>项目助手</h2>
            <p className="small-note">
              收起保留讨论与草稿，不取消正在处理的任务。
            </p>
          </div>
          <button ref={close} className="button secondary" onClick={onClose}>
            收起助手
          </button>
        </header>
        <AssistantWorkspace bidId={bidId} memberId={memberId} embedded />
      </div>
    </div>,
    document.body,
  );
}
