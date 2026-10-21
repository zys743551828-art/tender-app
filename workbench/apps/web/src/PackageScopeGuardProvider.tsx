import { useCallback, useMemo, useState, type ReactNode } from "react";
import {
  PackageScopeRegistrationContext,
  PackageScopeStateContext,
  type PackageScopeRegistration,
} from "./packageScopeGuard";

export function PackageScopeGuardProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [entries, setEntries] = useState(
    new Map<symbol, PackageScopeRegistration>(),
  );
  const register = useCallback(
    (token: symbol, registration: PackageScopeRegistration) => {
      setEntries((old) => new Map(old).set(token, registration));
      return () =>
        setEntries((old) => {
          // A delayed cleanup cannot remove a newer registration or another mounted command.
          if (old.get(token) !== registration) return old;
          const next = new Map(old);
          next.delete(token);
          return next;
        });
    },
    [],
  );
  const state = useMemo(
    () => ({
      busy: [...entries.values()].some((entry) => entry.state.busy),
      pending: [...entries.values()].some((entry) => entry.state.pending),
      dirty: [...entries.values()].some((entry) => entry.state.dirty),
    }),
    [entries],
  );
  return (
    <PackageScopeRegistrationContext.Provider value={register}>
      <PackageScopeStateContext.Provider value={state}>
        {children}
      </PackageScopeStateContext.Provider>
    </PackageScopeRegistrationContext.Provider>
  );
}
