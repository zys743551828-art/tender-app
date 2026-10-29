import { useEffect, useId, useState, type ReactNode } from "react";
import "./EditorToolsDisclosure.css";

/** Collapse formatting, not the editor: selection, draft and save queue survive. */
export function EditorToolsDisclosure({ children }: { children: ReactNode }) {
  const [compact, setCompact] = useState(() => window.innerWidth <= 600);
  const [expanded, setExpanded] = useState(false);
  const id = useId();
  useEffect(() => {
    const resize = () => setCompact(window.innerWidth <= 600);
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  return (
    <div className="editor-tools-disclosure">
      <button
        className="text-button"
        type="button"
        hidden={!compact}
        aria-expanded={expanded}
        aria-controls={id}
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? "收起文字格式与编辑工具" : "文字格式与编辑工具"}
      </button>
      <div id={id} hidden={compact && !expanded}>
        {children}
      </div>
    </div>
  );
}
