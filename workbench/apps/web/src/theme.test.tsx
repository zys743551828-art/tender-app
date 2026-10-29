import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ThemePicker } from "./ThemePicker";
import { THEME_KEY, useTheme } from "./theme";

let systemDark = false;
const listeners = new Set<() => void>();
function changeSystem(value: boolean) {
  systemDark = value;
  act(() => listeners.forEach((listener) => listener()));
}
function Appearance() {
  return <ThemePicker {...useTheme()} />;
}
beforeEach(() => {
  localStorage.clear();
  systemDark = false;
  listeners.clear();
  delete document.documentElement.dataset.theme;
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      get matches() {
        return systemDark;
      },
      addEventListener: (_: string, listener: () => void) =>
        listeners.add(listener),
      removeEventListener: (_: string, listener: () => void) =>
        listeners.delete(listener),
    })),
  );
});

it("follows system appearance until the user makes an explicit choice", () => {
  render(<Appearance />);
  expect(screen.getByLabelText("外观主题")).toHaveValue("system");
  expect(document.documentElement.dataset.theme).toBe("light");
  changeSystem(true);
  expect(document.documentElement.dataset.theme).toBe("dark");
  fireEvent.change(screen.getByLabelText("外观主题"), {
    target: { value: "light" },
  });
  changeSystem(false);
  changeSystem(true);
  expect(document.documentElement.dataset.theme).toBe("light");
  expect(localStorage.getItem(THEME_KEY)).toBe("light");
});

it("restores the saved choice on remount and can return to live system updates", () => {
  const first = render(<Appearance />);
  fireEvent.change(screen.getByLabelText("外观主题"), {
    target: { value: "dark" },
  });
  first.unmount();
  render(<Appearance />);
  expect(screen.getByLabelText("外观主题")).toHaveValue("dark");
  fireEvent.change(screen.getByLabelText("外观主题"), {
    target: { value: "system" },
  });
  expect(document.documentElement.dataset.theme).toBe("light");
  changeSystem(true);
  expect(document.documentElement.dataset.theme).toBe("dark");
});

it("synchronizes another browser tab without responding to business storage changes", () => {
  render(<Appearance />);
  localStorage.setItem(THEME_KEY, "dark");
  act(() =>
    window.dispatchEvent(new StorageEvent("storage", { key: "draft" })),
  );
  expect(document.documentElement.dataset.theme).toBe("light");
  act(() =>
    window.dispatchEvent(new StorageEvent("storage", { key: THEME_KEY })),
  );
  expect(screen.getByLabelText("外观主题")).toHaveValue("dark");
  expect(document.documentElement.dataset.theme).toBe("dark");
  localStorage.clear();
  act(() => window.dispatchEvent(new StorageEvent("storage", { key: null })));
  expect(screen.getByLabelText("外观主题")).toHaveValue("system");
});

it("keeps the current view usable when the browser refuses storage", () => {
  const read = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new DOMException("restricted", "SecurityError");
  });
  const write = vi
    .spyOn(Storage.prototype, "setItem")
    .mockImplementation(() => {
      throw new DOMException("restricted", "SecurityError");
    });
  render(<Appearance />);
  fireEvent.change(screen.getByLabelText("外观主题"), {
    target: { value: "dark" },
  });
  expect(document.documentElement.dataset.theme).toBe("dark");
  read.mockRestore();
  write.mockRestore();
});

it("treats an invalid saved value as system and cleans up media listeners", () => {
  localStorage.setItem(THEME_KEY, "invalid");
  const mounted = render(<Appearance />);
  expect(screen.getByLabelText("外观主题")).toHaveValue("system");
  expect(listeners.size).toBe(1);
  mounted.unmount();
  expect(listeners.size).toBe(0);
});

it("supports browsers without a color-scheme media API", () => {
  vi.stubGlobal("matchMedia", undefined);
  render(<Appearance />);
  expect(document.documentElement.dataset.theme).toBe("light");
  fireEvent.change(screen.getByLabelText("外观主题"), {
    target: { value: "dark" },
  });
  expect(document.documentElement.dataset.theme).toBe("dark");
});
