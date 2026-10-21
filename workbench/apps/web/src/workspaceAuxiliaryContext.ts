import { createContext, type RefObject } from "react";

/** Preserve the originating panel across asynchronous source lookup and portals. */
export const WorkspaceAuxiliaryContext =
  createContext<RefObject<HTMLElement | null> | null>(null);
