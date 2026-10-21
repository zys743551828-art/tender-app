import { useLayoutEffect, useState } from "react";
import { assistantDockBounds, assistantDockGap } from "./assistantDock";

export function useAssistantDock(
  targetId: string | undefined,
  memberId: string,
) {
  const preferenceKey = `tender:assistant-layout:${memberId}:width`;
  const [requested, setRequested] = useState(() => {
    try {
      const value = Number(localStorage.getItem(preferenceKey));
      return Number.isFinite(value) && value >= 340 && value <= 720
        ? value
        : 400;
    } catch {
      return 400;
    }
  });
  const [box, setBox] = useState({ available: 0, right: 0, top: 0 });
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
    if (!target || !bounds.docked) return;
    const previous = target.getAttribute("data-assistant-docked");
    const width = target.style.getPropertyValue("--assistant-dock-space");
    target.setAttribute("data-assistant-docked", "true");
    target.style.setProperty(
      "--assistant-dock-space",
      `${bounds.width + assistantDockGap}px`,
    );
    return () => {
      if (previous === null) target.removeAttribute("data-assistant-docked");
      else target.setAttribute("data-assistant-docked", previous);
      if (width) target.style.setProperty("--assistant-dock-space", width);
      else target.style.removeProperty("--assistant-dock-space");
    };
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
