import { useRef } from "react";
import { assistantMinimumWidth } from "./assistantDock";

/** One keyboard and pointer contract for the shared assistant/source boundary. */
export function AuxiliaryResizeHandle({
  label,
  controls,
  width,
  max,
  onResize,
  onClose,
}: {
  label: string;
  controls: string;
  width: number;
  max: number;
  onResize: (width: number) => void;
  onClose: () => void;
}) {
  const drag = useRef<{ x: number; width: number } | null>(null);
  return (
    <div
      className="assistant-resize-handle"
      title="拖动边界调整宽度，或聚焦后使用左右方向键"
      role="separator"
      aria-label={`调整${label}面板宽度`}
      aria-orientation="vertical"
      aria-controls={controls}
      aria-valuemin={assistantMinimumWidth}
      aria-valuemax={max}
      aria-valuenow={width}
      aria-valuetext={`${label}宽 ${width} 像素，正文空间至少 620 像素`}
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
          Home: assistantMinimumWidth - width,
          End: max - width,
        };
        if (event.key in steps) {
          event.preventDefault();
          onResize(width + steps[event.key]);
        }
      }}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        drag.current = { x: event.clientX, width };
        event.currentTarget.setPointerCapture(event.pointerId);
        event.currentTarget.focus({ preventScroll: true });
        event.preventDefault();
      }}
      onPointerMove={(event) => {
        if (drag.current)
          onResize(drag.current.width + drag.current.x - event.clientX);
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
  );
}
