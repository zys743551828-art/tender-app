import { useEffect, useRef, useState, type ReactNode } from "react";
import { useAuxiliaryFocus } from "./useAuxiliaryFocus";
import "./AssistantSourceSurface.css";

/** Keep the composer mounted while a compact source-selection task is open. */
export function AssistantSourceSurface({
  children,
  onClose,
}: {
  children: ReactNode;
  onClose: () => void;
}) {
  const [compact, setCompact] = useState(() => window.innerWidth <= 850);
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const resize = () => setCompact(window.innerWidth <= 850);
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  useAuxiliaryFocus({
    open: true,
    modal: compact,
    panel,
    initialFocus: close,
    onClose,
  });
  return (
    <div
      ref={panel}
      role="dialog"
      aria-modal={compact ? true : undefined}
      aria-label="选择本次消息来源"
      tabIndex={-1}
      className={`assistant-source-surface${compact ? " assistant-source-surface--compact" : ""}`}
    >
      <header>
        <strong>本次消息的来源</strong>
        <button
          type="button"
          ref={close}
          className="button secondary"
          onClick={onClose}
        >
          返回提问
        </button>
      </header>
      {children}
    </div>
  );
}
