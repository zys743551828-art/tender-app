import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { AssistantWorkspace } from "./AssistantWorkspace";
import { assistantMinimumWidth } from "./assistantDock";
import { useAssistantDock } from "./useAssistantDock";
import { useAuxiliaryFocus } from "./useAuxiliaryFocus";
import {
  announceWorkspaceAuxiliary,
  listenWorkspaceAuxiliary,
} from "./workspaceAuxiliary";
import "./AssistantDrawer.css";

export function AssistantDrawer({
  bidId,
  memberId,
  onClose,
  dockTargetId,
}: {
  bidId: string;
  memberId: string;
  onClose: () => void;
  /** The stable task container reserves room; without one, use a modal. */
  dockTargetId?: string;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const drag = useRef<{ x: number; width: number } | null>(null);
  const dock = useAssistantDock(dockTargetId, memberId);
  useAuxiliaryFocus({
    open: true,
    modal: !dock.docked,
    panel,
    initialFocus: close,
    onClose,
  });
  useEffect(() => {
    announceWorkspaceAuxiliary(bidId, "assistant");
    return listenWorkspaceAuxiliary(bidId, "assistant", onClose);
  }, [bidId, onClose]);
  useEffect(() => {
    window.addEventListener("session-expired", onClose);
    return () => window.removeEventListener("session-expired", onClose);
  }, [onClose]);
  return createPortal(
    <div
      className={`assistant-surface ${dock.docked ? "assistant-surface--docked" : "assistant-surface--modal"}`}
      style={
        dock.docked
          ? {
              width: dock.width,
              right: window.innerWidth - dock.right,
              top: dock.top,
            }
          : undefined
      }
    >
      {dock.docked && (
        <div
          className="assistant-resize-handle"
          role="separator"
          aria-label="调整助手面板宽度"
          aria-orientation="vertical"
          aria-controls="project-assistant-panel"
          aria-valuemin={assistantMinimumWidth}
          aria-valuemax={dock.max}
          aria-valuenow={dock.width}
          aria-valuetext={`助手宽 ${dock.width} 像素，正文空间至少 620 像素`}
          tabIndex={0}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              onClose();
              return;
            }
            const steps: Record<string, number> = {
              ArrowLeft: 24,
              ArrowRight: -24,
              Home: assistantMinimumWidth - dock.width,
              End: dock.max - dock.width,
            };
            if (event.key in steps) {
              event.preventDefault();
              dock.resize(dock.width + steps[event.key]);
            }
          }}
          onPointerDown={(event) => {
            if (event.button !== 0) return;
            drag.current = { x: event.clientX, width: dock.width };
            event.currentTarget.setPointerCapture(event.pointerId);
            event.currentTarget.focus({ preventScroll: true });
            event.preventDefault();
          }}
          onPointerMove={(event) => {
            if (drag.current)
              dock.resize(drag.current.width + drag.current.x - event.clientX);
          }}
          onPointerUp={(event) => {
            drag.current = null;
            if (event.currentTarget.hasPointerCapture(event.pointerId))
              event.currentTarget.releasePointerCapture(event.pointerId);
          }}
          onPointerCancel={() => {
            drag.current = null;
          }}
          onLostPointerCapture={() => {
            drag.current = null;
          }}
        />
      )}
      <div
        id="project-assistant-panel"
        className="assistant-drawer"
        ref={panel}
        role={dock.docked ? "complementary" : "dialog"}
        aria-modal={dock.docked ? undefined : true}
        aria-label="项目主会话助手"
        tabIndex={-1}
      >
        <header className="retrieval-heading assistant-drawer-heading">
          <div>
            <h2>项目助手</h2>
            <p className="small-note">
              收起保留讨论与草稿，不取消正在处理的任务。
            </p>
          </div>
          <button ref={close} className="button secondary" onClick={onClose}>
            收起助手
          </button>
        </header>
        {dock.docked && (
          <p className="assistant-resize-hint">
            拖动左边界调整宽度；聚焦边界后可用左右方向键。
          </p>
        )}
        <AssistantWorkspace bidId={bidId} memberId={memberId} embedded />
      </div>
    </div>,
    document.body,
  );
}
