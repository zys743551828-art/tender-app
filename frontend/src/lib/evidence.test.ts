import { describe, expect, it } from 'vitest';
import { bboxToPercent, bboxToRect, clampPage, fitWidthScale, parseBbox } from './evidence';

describe('parseBbox：只接受可信坐标，否则不画高亮', () => {
  it('合法归一化坐标原样通过', () => {
    expect(parseBbox([0.1, 0.2, 0.6, 0.4])).toEqual([0.1, 0.2, 0.6, 0.4]);
  });
  it('null / 长度不对 / 非有限数 → null', () => {
    expect(parseBbox(null)).toBeNull();
    expect(parseBbox(undefined)).toBeNull();
    expect(parseBbox([0.1, 0.2, 0.3])).toBeNull();
    expect(parseBbox([0.1, 0.2, Number.NaN, 0.4])).toBeNull();
    expect(parseBbox([0.1, 0.2, Infinity, 0.4])).toBeNull();
  });
  it('越界（如误用像素或 PDF 点坐标）→ null，不静默缩放', () => {
    expect(parseBbox([72, 100, 300, 140])).toBeNull();
    expect(parseBbox([-0.2, 0, 0.5, 0.5])).toBeNull();
    expect(parseBbox([0, 0, 1.5, 0.5])).toBeNull();
  });
  it('退化（零面积或反向）→ null', () => {
    expect(parseBbox([0.3, 0.3, 0.3, 0.5])).toBeNull();
    expect(parseBbox([0.6, 0.2, 0.2, 0.4])).toBeNull();
  });
  it('浮点误差范围内的轻微越界会被夹到 [0,1]', () => {
    expect(parseBbox([-0.001, 0, 1.001, 1])).toEqual([0, 0, 1, 1]);
  });
});

describe('坐标换算（原点左上，y 向下）', () => {
  it('归一化 → 像素矩形', () => {
    const r = bboxToRect([0.1, 0.2, 0.6, 0.4], 800, 1000);
    expect(r.left).toBeCloseTo(80);
    expect(r.top).toBeCloseTo(200);
    expect(r.width).toBeCloseTo(400);
    expect(r.height).toBeCloseTo(200);
  });
  it('整页 bbox 铺满页面', () => {
    expect(bboxToRect([0, 0, 1, 1], 595, 842)).toEqual({
      left: 0,
      top: 0,
      width: 595,
      height: 842,
    });
  });
  it('百分比矩形与页面尺寸无关，缩放后仍对齐', () => {
    expect(bboxToPercent([0.25, 0.5, 0.75, 0.6])).toEqual({
      left: 25,
      top: 50,
      width: 50,
      height: expect.closeTo(10, 5),
    });
  });
  it('横向页面（宽>高）同样按各自方向缩放', () => {
    const r = bboxToRect([0.5, 0.5, 1, 1], 1200, 800);
    expect(r).toEqual({ left: 600, top: 400, width: 600, height: 400 });
  });
});

describe('页码与缩放', () => {
  it('clampPage 限制在 [1, pageCount]，并处理非法输入', () => {
    expect(clampPage(0, 10)).toBe(1);
    expect(clampPage(11, 10)).toBe(10);
    expect(clampPage(4.9, 10)).toBe(4);
    expect(clampPage(Number.NaN, 10)).toBe(1);
    expect(clampPage(3, 0)).toBe(1);
  });
  it('fitWidthScale 适合宽度，手机最小 240，桌面最大 1000', () => {
    expect(fitWidthScale(390, 595)).toBeCloseTo(390 / 595);
    expect(fitWidthScale(100, 600)).toBeCloseTo(240 / 600);
    expect(fitWidthScale(3000, 500)).toBeCloseTo(2);
  });
});
