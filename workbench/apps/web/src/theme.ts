import { useCallback, useEffect, useState } from "react";

export type ThemePreference = "light" | "dark" | "system";
export const THEME_KEY = "bid-workbench:theme";
const SYSTEM_QUERY = "(prefers-color-scheme: dark)";

export function readThemePreference(): ThemePreference {
  try {
    const value = localStorage.getItem(THEME_KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(preference: ThemePreference) {
  const dark =
    preference === "dark" ||
    (preference === "system" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia(SYSTEM_QUERY).matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

export function useTheme() {
  const [preference, setPreference] =
    useState<ThemePreference>(readThemePreference);

  useEffect(() => {
    applyTheme(preference);
    const media =
      typeof window.matchMedia === "function"
        ? window.matchMedia(SYSTEM_QUERY)
        : null;
    const systemChanged = () => {
      if (preference === "system") applyTheme("system");
    };
    const storageChanged = (event: StorageEvent) => {
      if (event.key === THEME_KEY || event.key === null)
        setPreference(readThemePreference());
    };
    media?.addEventListener("change", systemChanged);
    window.addEventListener("storage", storageChanged);
    return () => {
      media?.removeEventListener("change", systemChanged);
      window.removeEventListener("storage", storageChanged);
    };
  }, [preference]);

  const choose = useCallback((next: ThemePreference) => {
    // A browser storage restriction must not prevent changing the current view.
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      // Keep the preference for the currently mounted app only.
    }
    applyTheme(next);
    setPreference(next);
  }, []);

  return { preference, choose };
}
