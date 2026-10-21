/* global localStorage, window, document */
// Runs before the app styles/render to avoid flashing a different saved theme.
(() => {
  let preference = "system";
  try {
    const value = localStorage.getItem("bid-workbench:theme");
    if (value === "light" || value === "dark") preference = value;
  } catch {
    // A restricted browser still follows its system appearance.
  }
  const dark =
    preference === "dark" ||
    (preference === "system" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
})();
