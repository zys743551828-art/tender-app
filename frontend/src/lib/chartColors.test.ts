import { describe, expect, it } from 'vitest';
import { scoreTicks } from './chartColors';

describe('scoreTicks', () => {
  it('取整齐的步长，最后一格是满分', () => {
    expect(scoreTicks(30)).toEqual([0, 10, 20, 30]);
    expect(scoreTicks(100)).toEqual([0, 25, 50, 75, 100]);
    expect(scoreTicks(8)).toEqual([0, 2, 4, 6, 8]);
    expect(scoreTicks(15)).toEqual([0, 5, 10, 15]);
  });
  it('满分无效时只有 0', () => {
    expect(scoreTicks(0)).toEqual([0]);
    expect(scoreTicks(Number.NaN)).toEqual([0]);
  });
});
