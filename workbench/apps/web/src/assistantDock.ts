export const assistantMinimumWidth = 340;
export const assistantMaximumWidth = 720;
export const assistantBodyMinimumWidth = 620;
export const assistantDockGap = 12;

export function assistantDockBounds(available: number, requested: number) {
  const max = Math.min(
    assistantMaximumWidth,
    Math.floor(available) - assistantBodyMinimumWidth - assistantDockGap,
  );
  const docked = max >= assistantMinimumWidth;
  return {
    docked,
    max,
    width: docked
      ? Math.max(assistantMinimumWidth, Math.min(max, Math.round(requested)))
      : 0,
  };
}
