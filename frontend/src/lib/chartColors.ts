import { useEffect, useState } from 'react';

/**
 * 图表颜色取自设计令牌。SVG 的表现属性不能直接写 var(--x)，所以在这里读出当前主题的实际色值，
 * 浅色／深色切换时（<html> 的 class 变化）重新读取。
 */
const KEYS = [
  'primary',
  'foreground',
  'muted-foreground',
  'border',
  'card',
  'danger',
  'warning',
  'popover',
] as const;
export type ChartColors = Record<(typeof KEYS)[number], string>;

function read(): ChartColors {
  const cs = getComputedStyle(document.documentElement);
  const out = {} as ChartColors;
  for (const k of KEYS) out[k] = cs.getPropertyValue(`--${k}`).trim() || '#888';
  return out;
}

export function useChartColors(): ChartColors {
  const [c, setC] = useState<ChartColors>(read);
  useEffect(() => {
    const obs = new MutationObserver(() => {
      setC(read());
    });
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => {
      obs.disconnect();
    };
  }, []);
  return c;
}

/** 0 到满分的纵轴刻度：步长取 1、2、2.5、5 乘 10 的整数次幂里最接近满分 / 4 的值，最后一格总是满分。 */
export function scoreTicks(full: number): number[] {
  if (!Number.isFinite(full) || full <= 0) return [0];
  const raw = full / 4;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = ([1, 2, 2.5, 5, 10].find((m) => m * mag >= raw) ?? 10) * mag;
  const ticks: number[] = [];
  for (let t = 0; t < full - step * 0.3; t += step) ticks.push(+t.toFixed(6));
  ticks.push(full);
  return ticks;
}
