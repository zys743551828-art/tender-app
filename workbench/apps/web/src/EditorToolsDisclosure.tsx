import { useId, useState, type ReactNode } from "react";
import "./EditorToolsDisclosure.css";

/** Collapse formatting, not the editor: selection, draft and save queue survive. */
export function EditorToolsDisclosure({ children }: { children: ReactNode }) {
  const [expanded, setExpanded] = useState(false);
  const id = useId();
  return (
    <div className="editor-tools-disclosure">
      <button
        className="text-button"
        type="button"
        aria-expanded={expanded}
        aria-controls={id}
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? "收起文字格式与编辑工具" : "文字格式与编辑工具"}
      </button>
      <div id={id}>{children}</div>
    </div>
  );
}
