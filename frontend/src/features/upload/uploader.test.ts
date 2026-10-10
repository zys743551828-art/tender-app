import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../api/errors';
import type { FileVersion, UploadComplete, UploadSession } from '../../api/types';
import {
  MAX_PARALLEL_PARTS,
  PartPutError,
  Uploader,
  fetchPutPart,
  type UploaderDeps,
  type UploadSource,
} from './uploader';

const MiB = 1024 * 1024;
const PART = 8 * MiB;
const HASH = 'a'.repeat(64);
const NOW = Date.parse('2026-10-07T08:00:00Z');

function source(size: number): UploadSource {
  return {
    name: '招标文件.pdf',
    type: 'application/pdf',
    size,
    slice: (a, b) => ({ arrayBuffer: () => Promise.resolve(new ArrayBuffer(b - a)) }),
  };
}

function session(parts: number, urlTag = 'u1', expiresInMs = 3_600_000): UploadSession {
  return {
    upload_id: 'upl-1',
    part_bytes: PART,
    part_count: parts,
    expires_at: new Date(NOW + expiresInMs).toISOString(),
    parts: Array.from({ length: parts }, (_, i) => ({
      part_number: i + 1,
      url: `https://oss.example/${urlTag}/part${String(i + 1)}`,
      expires_at: new Date(NOW + expiresInMs).toISOString(),
    })),
  };
}

const VERSION = { version_id: 'ver-1' } as FileVersion;

function setup(parts: number, over: Partial<UploaderDeps> = {}) {
  const calls = {
    init: [] as { key: string }[],
    complete: [] as { body: UploadComplete; key: string }[],
    put: [] as string[],
    refresh: 0,
  };
  const deps: UploaderDeps = {
    init: vi.fn((_b: unknown, o: { idempotencyKey: string }) => {
      calls.init.push({ key: o.idempotencyKey });
      return Promise.resolve(session(parts));
    }),
    refreshUrls: vi.fn(() => {
      calls.refresh++;
      return Promise.resolve(session(parts, `fresh${String(calls.refresh)}`));
    }),
    complete: vi.fn((_id: string, body: UploadComplete, o: { idempotencyKey: string }) => {
      calls.complete.push({ body, key: o.idempotencyKey });
      return Promise.resolve(VERSION);
    }),
    putPart: vi.fn((url: string) => {
      calls.put.push(url);
      return Promise.resolve(`"etag-${url.split('part')[1] ?? ''}"`);
    }),
    sleep: () => Promise.resolve(),
    now: () => NOW,
    hash: () => Promise.resolve(HASH),
    ...over,
  };
  return { deps, calls };
}

describe('Uploader 状态机', () => {
  it('正常路径：hash → init → 分片 → complete，complete 带按序的 etag 与整文件 sha256', async () => {
    const { deps, calls } = setup(3);
    const u = new Uploader(deps, { file: source(2 * PART + 5), role: 'tender' });
    const phases: string[] = [];
    u.subscribe((s) => {
      if (phases.at(-1) !== s.phase) phases.push(s.phase);
    });
    await u.start();
    expect(phases).toEqual(['idle', 'hashing', 'initializing', 'uploading', 'completing', 'done']);
    expect(u.getState().version).toBe(VERSION);
    expect(u.getState().uploadedBytes).toBe(2 * PART + 5);
    expect(calls.complete[0]?.body).toEqual({
      sha256: HASH,
      parts: [
        { part_number: 1, etag: '"etag-1"' },
        { part_number: 2, etag: '"etag-2"' },
        { part_number: 3, etag: '"etag-3"' },
      ],
    });
    expect(deps.init).toHaveBeenCalledWith(
      expect.objectContaining({
        original_name: '招标文件.pdf',
        role: 'tender',
        byte_size: 2 * PART + 5,
        sha256: HASH,
        version_of_file_id: null,
      }),
      expect.anything(),
    );
  });

  it('指定 versionOfFileId 时随 init 请求发送', async () => {
    const { deps } = setup(1);
    await new Uploader(deps, {
      file: source(PART),
      role: 'body',
      versionOfFileId: 'fil-9',
    }).start();
    expect(deps.init).toHaveBeenCalledWith(
      expect.objectContaining({ role: 'body', version_of_file_id: 'fil-9' }),
      expect.anything(),
    );
  });

  it('分片边界：每片按 8 MiB 切分，最后一片为余量', async () => {
    const slices: [number, number][] = [];
    const file: UploadSource = {
      ...source(2 * PART + 5),
      slice: (a, b) => {
        slices.push([a, b]);
        return { arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)) };
      },
    };
    const { deps } = setup(3);
    await new Uploader(deps, { file, role: 'body' }).start();
    expect(slices.sort((a, b) => a[0] - b[0])).toEqual([
      [0, PART],
      [PART, 2 * PART],
      [2 * PART, 2 * PART + 5],
    ]);
  });

  it('最多 4 路并行上传', async () => {
    let active = 0;
    let peak = 0;
    const { deps } = setup(10, {
      putPart: async (url) => {
        active++;
        peak = Math.max(peak, active);
        await new Promise((r) => setTimeout(r, 5));
        active--;
        return `"e${url}"`;
      },
    });
    const u = new Uploader(deps, { file: source(10 * PART), role: 'drawing' });
    await u.start();
    expect(u.getState().phase).toBe('done');
    expect(peak).toBe(MAX_PARALLEL_PARTS);
  });

  it('分片失败自动退避重试，成功后不影响其它分片', async () => {
    let fails = 2;
    const { deps, calls } = setup(2, {
      putPart: (url) => {
        calls.put.push(url);
        if (url.endsWith('part2') && fails-- > 0)
          return Promise.reject(new PartPutError(0, '网络中断，分片未传完'));
        return Promise.resolve('"ok"');
      },
    });
    const u = new Uploader(deps, { file: source(2 * PART), role: 'tender' });
    await u.start();
    expect(u.getState().phase).toBe('done');
    expect(calls.put.filter((x) => x.endsWith('part2'))).toHaveLength(3);
    expect(calls.put.filter((x) => x.endsWith('part1'))).toHaveLength(1);
  });

  it('重试耗尽后进入 failed；retry() 只补传未完成分片，复用幂等键与会话', async () => {
    let broken = true;
    const { deps, calls } = setup(3, {
      putPart: (url) => {
        calls.put.push(url);
        if (broken && url.endsWith('part3'))
          return Promise.reject(new PartPutError(500, '存储服务返回 HTTP 500'));
        return Promise.resolve('"ok"');
      },
    });
    const u = new Uploader(deps, { file: source(3 * PART), role: 'tender' });
    await u.start();
    expect(u.getState().phase).toBe('failed');
    expect(u.getState().error).toContain('1 个分片上传失败');
    expect(u.getState().error).toContain('可点击重试');
    expect(u.getState().parts.map((p) => p.status)).toEqual(['done', 'done', 'failed']);

    broken = false;
    calls.put.length = 0;
    await u.retry();
    expect(u.getState().phase).toBe('done');
    expect(calls.put).toEqual(['https://oss.example/u1/part3']); // 已完成的分片没有重传
    expect(deps.init).toHaveBeenCalledTimes(1); // 不重新建会话
    expect(calls.complete[0]?.body.parts).toHaveLength(3);
  });

  it('存储端回 403（预签名地址过期）：刷新地址后用新地址重试，且并发的刷新合并为一次', async () => {
    const { deps, calls } = setup(3, {
      putPart: (url) => {
        calls.put.push(url);
        if (url.includes('/u1/')) return Promise.reject(new PartPutError(403, '上传地址已失效'));
        return Promise.resolve('"ok"');
      },
    });
    const u = new Uploader(deps, { file: source(3 * PART), role: 'tender' });
    await u.start();
    expect(u.getState().phase).toBe('done');
    expect(calls.refresh).toBe(1);
    expect(calls.put.filter((x) => x.includes('/fresh1/'))).toHaveLength(3);
  });

  it('地址临近过期（<30s）时上传前先刷新，不先撞 403', async () => {
    const base = setup(1);
    const deps: UploaderDeps = {
      ...base.deps,
      init: () => Promise.resolve(session(1, 'u1', 10_000)),
    };
    const u = new Uploader(deps, { file: source(PART), role: 'tender' });
    await u.start();
    expect(u.getState().phase).toBe('done');
    expect(base.calls.refresh).toBe(1);
    expect(base.calls.put).toEqual(['https://oss.example/fresh1/part1']);
  });

  it('地址反复过期超过刷新上限 → failed 并给出明确提示', async () => {
    const { deps } = setup(1, {
      putPart: () => Promise.reject(new PartPutError(403, '上传地址已失效')),
    });
    const u = new Uploader(deps, { file: source(PART), role: 'tender' });
    await u.start();
    expect(u.getState().phase).toBe('failed');
    expect(u.getState().error).toContain('上传地址多次过期');
  });

  it('服务端复算校验失败（complete 返回错误）：failed，展示服务端中文说明与请求编号，不显示为完成', async () => {
    const { deps } = setup(1, {
      complete: () =>
        Promise.reject(
          new ApiError({
            status: 422,
            code: 'INVALID_CONTRACT',
            message: '文件校验失败：服务端复算的 SHA-256 与声明不一致，文件已隔离',
            requestId: 'req-77',
          }),
        ),
    });
    const u = new Uploader(deps, { file: source(PART), role: 'tender' });
    await u.start();
    const s = u.getState();
    expect(s.phase).toBe('failed');
    expect(s.error).toContain('SHA-256');
    expect(s.requestId).toBe('req-77');
    expect(s.version).toBeNull();
  });

  it('init 失败不可重试（如 403）时直接 failed，不发起分片', async () => {
    const { deps, calls } = setup(1, {
      init: () =>
        Promise.reject(
          new ApiError({ status: 403, code: 'ACCESS_DENIED', message: '没有执行该操作的权限' }),
        ),
    });
    const u = new Uploader(deps, { file: source(PART), role: 'tender' });
    await u.start();
    expect(u.getState().phase).toBe('failed');
    expect(calls.put).toHaveLength(0);
  });

  it('complete 失败后 retry：复用同一个 complete 幂等键', async () => {
    let n = 0;
    const { deps, calls } = setup(1, {
      complete: (_id, body, o) => {
        calls.complete.push({ body, key: o.idempotencyKey });
        return ++n === 1
          ? Promise.reject(
              new ApiError({
                status: 503,
                code: 'STORAGE_UNAVAILABLE',
                message: '存储暂不可用',
                retryable: true,
              }),
            )
          : Promise.resolve(VERSION);
      },
    });
    const u = new Uploader(deps, { file: source(PART), role: 'tender' });
    await u.start();
    expect(u.getState().phase).toBe('failed');
    await u.retry();
    expect(u.getState().phase).toBe('done');
    expect(calls.complete).toHaveLength(2);
    expect(calls.complete[0]?.key).toBe(calls.complete[1]?.key);
  });

  it('超过 100 MiB 或空文件在本地拒绝，不发任何请求', async () => {
    const { deps } = setup(1);
    const big = new Uploader(deps, { file: source(100 * MiB + 1), role: 'tender' });
    await big.start();
    expect(big.getState().error).toContain('100 MiB');
    const empty = new Uploader(deps, { file: source(0), role: 'tender' });
    await empty.start();
    expect(empty.getState().error).toContain('空');
    expect(deps.init).not.toHaveBeenCalled();
  });

  it('取消：进入 cancelled，之后可重新开始', async () => {
    const { deps } = setup(1, {
      putPart: (_u, _b, signal) =>
        new Promise((_res, rej) => {
          signal.addEventListener('abort', () => {
            rej(new DOMException('已取消', 'AbortError'));
          });
        }),
    });
    const u = new Uploader(deps, { file: source(PART), role: 'tender' });
    const p = u.start();
    await new Promise((r) => setTimeout(r, 10));
    u.cancel();
    await p;
    expect(u.getState().phase).toBe('cancelled');
  });
});

describe('fetchPutPart（直传存储）', () => {
  const ac = new AbortController();
  const blob = new Blob(['x']);

  it('读取响应头 ETag；不带 cookie（credentials: omit）', async () => {
    const f = vi.fn(() =>
      Promise.resolve(new Response(null, { status: 200, headers: { ETag: '"abc"' } })),
    );
    const etag = await fetchPutPart('https://oss/x', blob, ac.signal, f);
    expect(etag).toBe('"abc"');
    expect(f).toHaveBeenCalledWith(
      'https://oss/x',
      expect.objectContaining({ method: 'PUT', credentials: 'omit' }),
    );
  });

  it('读不到 ETag（CORS 未暴露）给出可操作的中文提示', async () => {
    const f = () => Promise.resolve(new Response(null, { status: 200 }));
    await expect(
      fetchPutPart('https://oss/x', blob, ac.signal, f as unknown as typeof fetch),
    ).rejects.toThrow(/ETag/);
  });

  it('403 → PartPutError(403)；网络错误 → PartPutError(0)', async () => {
    const f403 = () => Promise.resolve(new Response('denied', { status: 403 }));
    await expect(
      fetchPutPart('u', blob, ac.signal, f403 as unknown as typeof fetch),
    ).rejects.toMatchObject({ status: 403 });
    const fnet = () => Promise.reject(new TypeError('Failed to fetch'));
    await expect(
      fetchPutPart('u', blob, ac.signal, fnet as unknown as typeof fetch),
    ).rejects.toMatchObject({ status: 0 });
  });
});
