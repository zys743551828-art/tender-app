import { createContext, useContext, useEffect, useRef } from "react";
import {
  emptyPackageNavigationState,
  type PackageNavigationState,
} from "./packageNavigation";

export type PackageScopeRegistration = {
  scope: string;
  state: PackageNavigationState;
};
export const PackageScopeRegistrationContext = createContext<
  (token: symbol, registration: PackageScopeRegistration) => () => void
>(() => () => {});
export const PackageScopeStateContext = createContext(
  emptyPackageNavigationState,
);

/** Reports only the mounted operation's real state; storage/ACK ownership stays with its controller. */
export function usePackageScopeGuard(
  scope: string,
  state: Partial<PackageNavigationState>,
) {
  const register = useContext(PackageScopeRegistrationContext);
  const token = useRef(Symbol("package-operation"));
  const { busy = false, pending = false, dirty = false } = state;
  useEffect(
    () => register(token.current, { scope, state: { busy, pending, dirty } }),
    [register, scope, busy, pending, dirty],
  );
}
export function usePackageScopeState() {
  return useContext(PackageScopeStateContext);
}
