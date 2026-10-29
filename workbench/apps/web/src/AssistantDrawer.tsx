import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { AssistantWorkspace } from "./AssistantWorkspace";
import { AuxiliaryResizeHandle } from "./AuxiliaryResizeHandle";
import { useAssistantDock } from "./useAssistantDock";
import { useAuxiliaryFocus } from "./useAuxiliaryFocus";
import { WorkspaceAuxiliaryContext } from "./workspaceAuxiliaryContext";
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
      data-workspace-auxiliary-surface="true"
      data-docked={dock.docked}
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
        <AuxiliaryResizeHandle
          label="助手"
          controls="project-assistant-panel"
          width={dock.width}
          max={dock.max}
          onResize={dock.resize}
          onClose={onClose}
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
        data-workspace-auxiliary-panel="true"
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
        <WorkspaceAuxiliaryContext.Provider value={{ panel, dock }}>
          <AssistantWorkspace bidId={bidId} memberId={memberId} embedded />
        </WorkspaceAuxiliaryContext.Provider>
      </div>
    </div>,
    document.body,
  );
}
