import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import { hashSource, Sha256, sha256Hex, type SliceableSource } from './sha256';

const enc = (s: string) => new TextEncoder().encode(s);
const nodeHex = (b: Uint8Array) => createHash('sha256').update(b).digest('hex');

describe('Sha256 已知向量（FIPS 180-4 / NIST）', () => {
  it('空串', () => {
    expect(sha256Hex(new Uint8Array())).toBe(
      'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    );
  });
  it('"abc"', () => {
    expect(sha256Hex(enc('abc'))).toBe(
      'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
    );
  });
  it('448 位消息（恰好需要额外一个填充块）', () => {
    expect(sha256Hex(enc('abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq'))).toBe(
      '248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1',
    );
  });
  it('896 位消息', () => {
    expect(
      sha256Hex(
        enc(
          'abcdefghbcdefghicdefghijdefghijkefghijklfghijklmghijklmnhijklmnoijklmnopjklmnopqklmnopqrlmnopqrsmnopqrstnopqrstu',
        ),
      ),
    ).toBe('cf5b16a778af8380036ce59e7b0492370b249b11e8f07a51afac45037afee9d1');
  });
  it('一百万个 "a"，且分 1 字节 / 63 / 64 / 65 字节不规则增量喂入结果一致', () => {
    const data = new Uint8Array(1_000_000).fill(0x61);
    const expected = 'cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0';
    expect(sha256Hex(data)).toBe(expected);
    const h = new Sha256();
    const sizes = [1, 63, 64, 65, 4097];
    let pos = 0;
    for (let i = 0; pos < data.length; i++) {
      const n = Math.min(sizes[i % sizes.length] ?? 1, data.length - pos);
      h.update(data.subarray(pos, pos + n));
      pos += n;
    }
    expect(h.hexDigest()).toBe(expected);
  });
  it('与 Node crypto 对任意长度（0–200 字节）一致，覆盖所有填充边界', () => {
    for (let n = 0; n <= 200; n++) {
      const b = new Uint8Array(n).map((_, i) => (i * 31 + n) & 0xff);
      expect(sha256Hex(b)).toBe(nodeHex(b));
    }
  });
  it('digest 之后不能再 update', () => {
    const h = new Sha256();
    h.digest();
    expect(() => h.update(enc('x'))).toThrow();
  });
});

/** 合成的大文件：按需生成每个分片，不会整体分配，并记录任一时刻最大的单次读取量。 */
function syntheticSource(size: number) {
  const stats = { maxSlice: 0, slices: 0 };
  const byteAt = (i: number) => (i * 2654435761 + (i >>> 7)) & 0xff;
  const make = (a: number, b: number) => {
    const out = new Uint8Array(b - a);
    for (let i = a; i < b; i++) out[i - a] = byteAt(i);
    return out;
  };
  const src: SliceableSource = {
    size,
    slice(a, b) {
      stats.maxSlice = Math.max(stats.maxSlice, b - a);
      stats.slices++;
      return { arrayBuffer: () => Promise.resolve(make(a, b).buffer) };
    },
  };
  return { src, stats, make };
}

describe('hashSource 分块读取', () => {
  it('超过 100 MiB 的文件按块读取、结果与一次性计算一致，且从不一次读入整个文件', async () => {
    const size = 100 * 1024 * 1024 + 12_345; // 100 MiB 多一点，且不是块大小的整数倍
    const { src, stats, make } = syntheticSource(size);
    const progress: number[] = [];
    const got = await hashSource(src, { onProgress: (h) => progress.push(h) });

    // 参照：用 Node crypto 按另一种块大小（1 MiB）增量计算同一段合成数据。
    const ref = createHash('sha256');
    for (let p = 0; p < size; p += 1024 * 1024)
      ref.update(make(p, Math.min(p + 1024 * 1024, size)));
    expect(got).toBe(ref.digest('hex'));

    expect(stats.maxSlice).toBeLessThanOrEqual(4 * 1024 * 1024);
    expect(stats.maxSlice).toBeLessThan(size / 20);
    expect(stats.slices).toBe(Math.ceil(size / (4 * 1024 * 1024)));
    expect(progress.at(-1)).toBe(size);
    expect(progress).toEqual([...progress].sort((a, b) => a - b));
  }, 60_000);

  it('空文件与可取消', async () => {
    const empty = syntheticSource(0).src;
    expect(await hashSource(empty)).toBe(
      'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    );
    const ac = new AbortController();
    ac.abort();
    await expect(hashSource(syntheticSource(10).src, { signal: ac.signal })).rejects.toThrow();
  });
});
