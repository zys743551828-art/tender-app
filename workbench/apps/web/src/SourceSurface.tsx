import {
  useEffect,
  useContext,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";
import { AuxiliaryResizeHandle } from "./AuxiliaryResizeHandle";
import { useAssistantDock } from "./useAssistantDock";
import { useAuxiliaryFocus } from "./useAuxiliaryFocus";
import { WorkspaceAuxiliaryContext } from "./workspaceAuxiliaryContext";
import {
  announceWorkspaceAuxiliary,
  listenWorkspaceAuxiliary,
} from "./workspaceAuxiliary";
import "./AssistantDrawer.css";
import "./SourceSurface.css";

const sourceOpened = "tender:source-surface-opened";

function useParentSurface(parent: HTMLElement | null) {
  const [box, setBox] = useState({
    docked: false,
    width: 0,
    right: 0,
    top: 0,
  });
  useLayoutEffect(() => {
    const surface = parent?.closest<HTMLElement>(
      "[data-workspace-auxiliary-surface]",
    );
    if (!surface) return;
    function measure() {
      const rect = surface!.getBoundingClientRect();
      const value = {
        docked: surface!.dataset.docked === "true",
        width: rect.width,
        right: rect.right,
        top: rect.top,
      };
      setBox((old) =>
        Object.keys(value).every(
          (key) =>
            old[key as keyof typeof old] === value[key as keyof typeof value],
        )
          ? old
          : value,
      );
    }
    measure();
    const sizes =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(measure);
    sizes?.observe(surface);
    const attributes = new MutationObserver(measure);
    attributes.observe(surface, { attributes: true });
    window.addEventListener("resize", measure);
    return () => {
      sizes?.disconnect();
      attributes.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [parent]);
  return box;
}

/** A nested source temporarily replaces its parent side panel, keeping its draft mounted. */
export function SourceSurface({
  bidId,
  className,
  labelledBy,
  initialFocus,
  returnFocus,
  onClose,
  children,
  dockTargetId = "main-content",
}: {
  bidId: string;
  className: string;
  labelledBy: string;
  initialFocus: RefObject<HTMLElement | null>;
  returnFocus?: RefObject<HTMLElement | null>;
  onClose: () => void;
  children: (singlePane: boolean) => ReactNode;
  dockTargetId?: string;
}) {
  const identity = useId();
  const originatingPanel = useContext(WorkspaceAuxiliaryContext);
  const [parent] = useState(
    () =>
      originatingPanel?.panel.current ??
      document.activeElement?.closest<HTMLElement>(
        '[data-workspace-auxiliary-panel], [role="dialog"]',
      ) ??
      null,
  );
  const ownDock = useAssistantDock(
    parent ? undefined : dockTargetId,
    "sources",
    {
      preferenceKey: "tender:source-layout:width",
      defaultWidth: 520,
    },
  );
  const parentDock = useParentSurface(parent);
  const dock = parent ? parentDock : ownDock;
  const controls = parent ? originatingPanel?.dock : ownDock;
  const panelId = `source-panel-${identity}`;
  const [viewport, setViewport] = useState(window.innerWidth);
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const resize = () => setViewport(window.innerWidth);
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  useAuxiliaryFocus({
    open: true,
    modal: !dock.docked,
    panel,
    initialFocus,
    returnFocus,
    onClose,
  });
  useLayoutEffect(() => {
    if (!parent) return;
    const surface = parent.closest<HTMLElement>(
      "[data-workspace-auxiliary-surface]",
    );
    const elements =
      surface && surface !== parent ? [parent, surface] : [parent];
    const previous = elements.map((element) => ({
      element,
      inert: element.getAttribute("inert"),
      hidden: element.getAttribute("aria-hidden"),
    }));
    for (const element of elements) {
      element.setAttribute("inert", "");
      element.setAttribute("aria-hidden", "true");
    }
    return () => {
      for (const { element, inert, hidden } of previous) {
        if (inert === null) element.removeAttribute("inert");
        else element.setAttribute("inert", inert);
        if (hidden === null) element.removeAttribute("aria-hidden");
        else element.setAttribute("aria-hidden", hidden);
      }
    };
  }, [parent]);
  useEffect(() => {
    window.addEventListener("session-expired", onClose);
    if (parent)
      return () => window.removeEventListener("session-expired", onClose);
    function otherSource(event: Event) {
      const detail = (event as CustomEvent<{ bidId: string; identity: string }>)
        .detail;
      if (detail?.bidId === bidId && detail.identity !== identity) onClose();
    }
    announceWorkspaceAuxiliary(bidId, "sources");
    window.dispatchEvent(
      new CustomEvent(sourceOpened, { detail: { bidId, identity } }),
    );
    window.addEventListener(sourceOpened, otherSource);
    const stop = listenWorkspaceAuxiliary(bidId, "sources", onClose);
    return () => {
      stop();
      window.removeEventListener(sourceOpened, otherSource);
      window.removeEventListener("session-expired", onClose);
    };
  }, [bidId, identity, onClose, parent]);
  return createPortal(
    <div
      className={`source-surface source-surface--${dock.docked ? "docked" : "modal"}${parent ? " source-surface--nested" : ""}`}
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
      {dock.docked && controls && (
        <AuxiliaryResizeHandle
          label="来源"
          controls={panelId}
          width={dock.width}
          max={controls.max}
          onResize={controls.resize}
          onClose={onClose}
        />
      )}
      <div
        id={panelId}
        className={className}
        ref={panel}
        role={dock.docked ? "complementary" : "dialog"}
        aria-modal={dock.docked ? undefined : true}
        aria-labelledby={labelledBy}
        tabIndex={-1}
        data-workspace-auxiliary-panel="true"
      >
        <WorkspaceAuxiliaryContext.Provider
          value={{ panel, dock: controls ?? ownDock }}
        >
          {children(dock.docked || viewport < 900)}
        </WorkspaceAuxiliaryContext.Provider>
      </div>
    </div>,
    document.body,
  );
}
