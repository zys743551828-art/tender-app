/**
 * 证据定位的坐标换算。
 *
 * 契约：EvidenceRef.bbox 为归一化 [x0,y0,x1,y1]，原点在页面左上角，x 向右、y 向下，
 * 相对"按阅读方向显示的整页"（PDF.js viewport 已应用页面自带的 /Rotate）。
 * bbox 为 null、非有限数、越界或退化（面积为 0）时一律不画高亮，只显示整页——
 * 绝不为了"看起来有定位"而虚构区域。
 */

export type Bbox = readonly [number, number, number, number];

export interface Rect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** 允许的越界容差（浮点误差）；超过则认为坐标不可信。 */
const EPS = 0.002;

export function parseBbox(raw: readonly number[] | null | undefined): Bbox | null {
  if (raw?.length !== 4) return null;
  if (!raw.every((n) => typeof n === 'number' && Number.isFinite(n))) return null;
  const [x0, y0, x1, y1] = raw as unknown as [number, number, number, number];
  if ([x0, y0, x1, y1].some((n) => n < -EPS || n > 1 + EPS)) return null;
  const c = (n: number) => Math.min(1, Math.max(0, n));
  const b: Bbox = [c(x0), c(y0), c(x1), c(y1)];
  if (b[2] <= b[0] || b[3] <= b[1]) return null;
  return b;
}

/** 归一化 bbox → 以像素为单位的矩形（相对页面画布左上角）。 */
export function bboxToRect(bbox: Bbox, pageWidth: number, pageHeight: number): Rect {
  return {
    left: bbox[0] * pageWidth,
    top: bbox[1] * pageHeight,
    width: (bbox[2] - bbox[0]) * pageWidth,
    height: (bbox[3] - bbox[1]) * pageHeight,
  };
}

/** 百分比矩形：页面缩放/窗口变化时高亮自动跟随，无需重算。 */
export function bboxToPercent(bbox: Bbox): Rect {
  return bboxToRect(bbox, 100, 100);
}

/** 根据容器宽度与页面原始尺寸计算渲染缩放比例（适合宽度，限制最大宽度）。 */
export function fitWidthScale(
  containerWidth: number,
  pageWidthAtScale1: number,
  maxWidth = 1000,
): number {
  const target = Math.min(Math.max(containerWidth, 240), maxWidth);
  return target / pageWidthAtScale1;
}

export function clampPage(page: number, pageCount: number): number {
  if (!Number.isFinite(page) || pageCount < 1) return 1;
  return Math.min(Math.max(Math.trunc(page), 1), pageCount);
}
