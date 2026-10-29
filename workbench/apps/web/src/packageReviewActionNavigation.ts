import { createContext } from "react";
import type { PackageNavigationTarget } from "./packageNavigation";

/** Host-owned navigation keeps project scope and existing unsaved-work guards. */
export const PackageReviewActionNavigation = createContext<{
  bidId: string;
  onOpenPackage: (target: PackageNavigationTarget) => void;
  onOpenRules?: () => void;
} | null>(null);
