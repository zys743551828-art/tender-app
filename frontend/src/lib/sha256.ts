/**
 * 纯 TypeScript 的增量 SHA-256（FIPS 180-4）。
 *
 * 为什么自己实现：Web Crypto 的 digest() 只能一次性处理完整缓冲区，而资料文件最大 100 MiB，
 * 不能整体读入内存；并且内网 http 部署属于非安全上下文，crypto.subtle 根本不存在。
 * 这里按块 update()，内存占用只与单块大小有关。
 */

const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

const INIT = [
  0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
];

export class Sha256 {
  private readonly h = new Uint32Array(INIT);
  private readonly block = new Uint8Array(64);
  private readonly w = new Uint32Array(64);
  private blockLen = 0;
  private bytes = 0;
  private done = false;

  update(data: Uint8Array): this {
    if (this.done) throw new Error('SHA-256 已完成，不能继续 update');
    let i = 0;
    const n = data.length;
    this.bytes += n;
    if (this.blockLen > 0) {
      const take = Math.min(64 - this.blockLen, n);
      this.block.set(data.subarray(0, take), this.blockLen);
      this.blockLen += take;
      i = take;
      if (this.blockLen === 64) {
        this.compress(this.block, 0);
        this.blockLen = 0;
      }
    }
    for (; i + 64 <= n; i += 64) this.compress(data, i);
    if (i < n) {
      this.block.set(data.subarray(i), 0);
      this.blockLen = n - i;
    }
    return this;
  }

  /** 返回 32 字节摘要；之后实例不可再用。 */
  digest(): Uint8Array {
    if (this.done) throw new Error('SHA-256 已完成');
    this.done = true;
    const bitsHigh = Math.floor(this.bytes / 0x20000000); // bytes*8 的高 32 位
    const bitsLow = (this.bytes << 3) >>> 0;
    this.block[this.blockLen++] = 0x80;
    if (this.blockLen > 56) {
      this.block.fill(0, this.blockLen, 64);
      this.compress(this.block, 0);
      this.blockLen = 0;
    }
    this.block.fill(0, this.blockLen, 56);
    const v = new DataView(this.block.buffer);
    v.setUint32(56, bitsHigh);
    v.setUint32(60, bitsLow);
    this.compress(this.block, 0);
    const out = new Uint8Array(32);
    const ov = new DataView(out.buffer);
    for (let i = 0; i < 8; i++) ov.setUint32(i * 4, this.h[i] ?? 0);
    return out;
  }

  hexDigest(): string {
    return toHex(this.digest());
  }

  private compress(buf: Uint8Array, off: number): void {
    const w = this.w;
    const h = this.h;
    for (let i = 0; i < 16; i++) {
      const j = off + i * 4;
      w[i] =
        (((buf[j] ?? 0) << 24) |
          ((buf[j + 1] ?? 0) << 16) |
          ((buf[j + 2] ?? 0) << 8) |
          (buf[j + 3] ?? 0)) >>>
        0;
    }
    for (let i = 16; i < 64; i++) {
      const w15 = w[i - 15] ?? 0;
      const w2 = w[i - 2] ?? 0;
      const s0 = ((w15 >>> 7) | (w15 << 25)) ^ ((w15 >>> 18) | (w15 << 14)) ^ (w15 >>> 3);
      const s1 = ((w2 >>> 17) | (w2 << 15)) ^ ((w2 >>> 19) | (w2 << 13)) ^ (w2 >>> 10);
      w[i] = ((w[i - 16] ?? 0) + s0 + (w[i - 7] ?? 0) + s1) >>> 0;
    }
    let a = h[0] ?? 0,
      b = h[1] ?? 0,
      c = h[2] ?? 0,
      d = h[3] ?? 0;
    let e = h[4] ?? 0,
      f = h[5] ?? 0,
      g = h[6] ?? 0,
      hh = h[7] ?? 0;
    for (let i = 0; i < 64; i++) {
      const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
      const ch = (e & f) ^ (~e & g);
      const t1 = (hh + S1 + ch + (K[i] ?? 0) + (w[i] ?? 0)) >>> 0;
      const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) >>> 0;
      hh = g;
      g = f;
      f = e;
      e = (d + t1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (t1 + t2) >>> 0;
    }
    h[0] = ((h[0] ?? 0) + a) >>> 0;
    h[1] = ((h[1] ?? 0) + b) >>> 0;
    h[2] = ((h[2] ?? 0) + c) >>> 0;
    h[3] = ((h[3] ?? 0) + d) >>> 0;
    h[4] = ((h[4] ?? 0) + e) >>> 0;
    h[5] = ((h[5] ?? 0) + f) >>> 0;
    h[6] = ((h[6] ?? 0) + g) >>> 0;
    h[7] = ((h[7] ?? 0) + hh) >>> 0;
  }
}

export function toHex(bytes: Uint8Array): string {
  let s = '';
  for (const b of bytes) s += b.toString(16).padStart(2, '0');
  return s;
}

export function sha256Hex(data: Uint8Array): string {
  return new Sha256().update(data).hexDigest();
}

/** Blob/File 的最小接口，便于用合成数据测试 100 MiB 以上的读取而不真正分配内存。 */
export interface SliceableSource {
  readonly size: number;
  slice(start: number, end: number): { arrayBuffer(): Promise<ArrayBuffer> };
}

export const HASH_READ_CHUNK = 4 * 1024 * 1024;

export interface HashOptions {
  chunkSize?: number;
  onProgress?: (hashedBytes: number, total: number) => void;
  signal?: AbortSignal;
}

/** 分块读取并增量计算；任一时刻最多持有一个 chunkSize 的缓冲区。 */
export async function hashSource(src: SliceableSource, opts: HashOptions = {}): Promise<string> {
  const chunk = opts.chunkSize ?? HASH_READ_CHUNK;
  const hasher = new Sha256();
  for (let pos = 0; pos < src.size; pos += chunk) {
    if (opts.signal?.aborted) throw new DOMException('已取消', 'AbortError');
    const end = Math.min(pos + chunk, src.size);
    const buf = await src.slice(pos, end).arrayBuffer();
    hasher.update(new Uint8Array(buf));
    opts.onProgress?.(end, src.size);
    // 让出主线程，避免大文件计算期间界面卡死。
    await new Promise<void>((r) => setTimeout(r, 0));
  }
  if (src.size === 0) opts.onProgress?.(0, 0);
  return hasher.hexDigest();
}
