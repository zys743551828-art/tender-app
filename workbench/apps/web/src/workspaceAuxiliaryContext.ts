import { createContext, type RefObject } from "react";

/** Preserve the originating panel across asynchronous source lookup and portals. */
export const WorkspaceAuxiliaryContext = createContext<{
  panel: RefObject<HTMLElement | null>;
  dock: { max: number; resize: (width: number) => void };
} | null>(null);
