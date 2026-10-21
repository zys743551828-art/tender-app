import type { ThemePreference } from "./theme";

export function ThemePicker({
  preference,
  choose,
}: {
  preference: ThemePreference;
  choose: (value: ThemePreference) => void;
}) {
  return (
    <label className="theme-picker">
      <span>外观</span>
      <select
        aria-label="外观主题"
        value={preference}
        onChange={(event) => choose(event.target.value as ThemePreference)}
      >
        <option value="system">跟随系统</option>
        <option value="light">浅色</option>
        <option value="dark">深色</option>
      </select>
    </label>
  );
}
