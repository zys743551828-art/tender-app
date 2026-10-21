import { useLayoutEffect, useRef, useState } from "react";
import { assistantDockBounds, assistantDockGap } from "./assistantDock";
import {
  reserveWorkspaceDock,
  setWorkspaceDockWidth,
} from "./workspaceDockReservation";

export function useAssistantDock(
  targetId: string | undefined,
  memberId: string,
  options?: { preferenceKey?: string; defaultWidth?: number },
) {
  const preferenceKey =
    options?.preferenceKey ?? `tender:assistant-layout:${memberId}:width`;
  const defaultWidth = options?.defaultWidth ?? 400;
  const [requested, setRequested] = useState(() => {
    try {
      const value = Number(localStorage.getItem(preferenceKey));
      return Number.isFinite(value) && value >= 340 && value <= 720
        ? value
        : defaultWidth;
    } catch {
      return defaultWidth;
    }
  });
  const [box, setBox] = useState({ available: 0, right: 0, top: 0 });
  const owner = useRef(Symbol("workspace-dock"));
  useLayoutEffect(() => {
    const target = targetId ? document.getElementById(targetId) : null;
    if (!target) return;
    function measure() {
      const rect = target!.getBoundingClientRect();
      const right = Math.min(window.innerWidth, rect.right);
      const value = {
        available: Math.max(0, right - Math.max(0, rect.left)),
        right,
        top: Math.max(0, Math.min(80, rect.top)),
      };
      setBox((old) =>
        old.available === value.available &&
        old.right === value.right &&
        old.top === value.top
          ? old
          : value,
      );
    }
    measure();
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(measure);
    observer?.observe(target);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, { passive: true });
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure);
    };
  }, [targetId]);
  const bounds = assistantDockBounds(box.available, requested);
  useLayoutEffect(() => {
    const target = targetId ? document.getElementById(targetId) : null;
    if (target) return reserveWorkspaceDock(target, owner.current);
  }, [targetId]);
  useLayoutEffect(() => {
    const target = targetId ? document.getElementById(targetId) : null;
    if (!target) return;
    setWorkspaceDockWidth(
      target,
      owner.current,
      bounds.docked ? bounds.width + assistantDockGap : null,
    );
  }, [targetId, bounds.docked, bounds.width]);
  function resize(width: number) {
    const next = assistantDockBounds(box.available, width).width;
    if (!bounds.docked) return;
    setRequested(next);
    try {
      localStorage.setItem(preferenceKey, String(next));
    } catch {
      // Resizing the view does not depend on saving a browser preference.
    }
  }
  return { ...bounds, ...box, resize };
}
