import { createContext, useContext, useEffect } from "react";
import type { RefObject } from "react";
export type NavigationGuard = () => Promise<boolean>;
export const NavigationGuardContext = createContext<
  (guard: NavigationGuard) => () => void
>(() => () => {});
export function useNavigationGuard(guard: RefObject<NavigationGuard>) {
  const register = useContext(NavigationGuardContext);
  useEffect(() => register(() => guard.current()), [register, guard]);
}
