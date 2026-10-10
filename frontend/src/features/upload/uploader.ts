import { ApiError, isApiError } from '../../api/errors';
import type {
  CompletedPart,
  FileRole,
  FileVersion,
  UploadComplete,
  UploadRequest,
  UploadSession,
} from '../../api/types';
import { hashSource, type SliceableSource } from '../../lib/sha256';
import { newIdempotencyKey } from '../../lib/uuid';

/** 产品限额（TECH-001 6.3）：浏览器最多 4 路并行；单文件 100 MiB；分片 8 MiB。 */
export const MAX_PARALLEL_PARTS = 4;
export const MAX_FILE_BYTES = 104_857_600;
export const MAX_PART_ATTEMPTS = 3;
export const MAX_URL_REFRESHES = 3;
/** 预签名地址距过期不足此时长时先刷新，避免传到一半失效。 */
export const URL_EXPIRY_MARGIN_MS = 30_000;

export type UploadPhase =
  | 'idle'
  | 'hashing'
  | 'initializing'
  | 'uploading'
  | 'completing'
  | 'done'
  | 'failed'
  | 'cancelled';

export type PartStatus = 'pending' | 'uploading' | 'done' | 'failed';

export interface PartState {
  partNumber: number;
  status: PartStatus;
  attempts: number;
  etag: string | null;
  error: string | null;
}

export interface UploadState {
  phase: UploadPhase;
  hashedBytes: number;
  uploadedBytes: number;
  totalBytes: number;
  parts: PartState[];
  /** 失败时的中文说明；校验失败（服务端复算 SHA-256 不一致等）也在此。 */
  error: string | null;
  requestId: string | null;
  version: FileVersion | null;
}

export interface UploadSource extends SliceableSource {
  readonly name: string;
  readonly type: string;
}

/** 存储端 PUT 失败：status 为 HTTP 状态码，0 表示网络错误；etag 缺失视为不可读（CORS 未暴露）。 */
export class PartPutError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'PartPutError';
  }
}

export interface UploaderDeps {
  init: (body: UploadRequest, o: { idempotencyKey: string }) => Promise<UploadSession>;
  refreshUrls: (uploadId: string) => Promise<UploadSession>;
  complete: (
    uploadId: string,
    body: UploadComplete,
    o: { idempotencyKey: string },
  ) => Promise<FileVersion>;
  /** 把分片直传到预签名地址，返回 ETag（响应头）。 */
  putPart: (
    url: string,
    body: { arrayBuffer(): Promise<ArrayBuffer> } | Blob,
    signal: AbortSignal,
  ) => Promise<string>;
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
  hash?: typeof hashSource;
}

export interface UploadInput {
  file: UploadSource;
  role: FileRole;
  /** 作为该已有文件（file_id）的新版本；null／省略表示新文件。 */
  versionOfFileId?: string | null;
}

const defaultSleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/**
 * 上传状态机：hash → init → 并行上传分片（≤4）→ complete。
 *
 * - 分片失败：指数退避重试至 MAX_PART_ATTEMPTS；仍失败则整体进入 failed，已完成分片保留，
 *   调用 retry() 只补传未完成分片（同一会话内的断点续传）。
 * - 预签名地址过期（距过期不足余量，或存储端回 403）：调用 refreshUrls 取新地址再重试，
 *   刷新次数有上限，且并发的刷新请求合并为一次。
 * - complete 失败（含服务端复算校验不一致）：整体 failed，保留服务端 message 与请求编号。
 * - 幂等键：init、complete 各用一个键，retry 时复用，保证服务端同键同会话。
 */
export class Uploader {
  private state: UploadState;
  private readonly listeners = new Set<(s: UploadState) => void>();
  private session: UploadSession | null = null;
  private sha256: string | null = null;
  private abort = new AbortController();
  private refreshing: Promise<void> | null = null;
  private refreshCount = 0;
  private readonly initKey = newIdempotencyKey();
  private readonly completeKey = newIdempotencyKey();
  private readonly sleep: (ms: number) => Promise<void>;
  private readonly now: () => number;
  private readonly hash: typeof hashSource;
  private running: Promise<void> | null = null;

  constructor(
    private readonly deps: UploaderDeps,
    private readonly input: UploadInput,
  ) {
    this.sleep = deps.sleep ?? defaultSleep;
    this.now = deps.now ?? Date.now;
    this.hash = deps.hash ?? hashSource;
    this.state = {
      phase: 'idle',
      hashedBytes: 0,
      uploadedBytes: 0,
      totalBytes: input.file.size,
      parts: [],
      error: null,
      requestId: null,
      version: null,
    };
  }

  getState(): UploadState {
    return this.state;
  }

  subscribe(fn: (s: UploadState) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private set(patch: Partial<UploadState>): void {
    this.state = { ...this.state, ...patch };
    for (const l of this.listeners) l(this.state);
  }

  private patchPart(n: number, patch: Partial<PartState>): void {
    const parts = this.state.parts.map((p) => (p.partNumber === n ? { ...p, ...patch } : p));
    const uploadedBytes = this.session
      ? parts
          .filter((p) => p.status === 'done')
          .reduce((sum, p) => sum + this.partSize(p.partNumber), 0)
      : 0;
    this.set({ parts, uploadedBytes });
  }

  private partSize(n: number): number {
    const pb = this.session?.part_bytes ?? 0;
    return Math.min(pb, this.input.file.size - (n - 1) * pb);
  }

  /** 开始（或在 failed 后继续）上传；返回的 Promise 在终态（done/failed/cancelled）时 resolve，不抛错。 */
  start(): Promise<void> {
    if (this.running) return this.running;
    this.abort = new AbortController();
    this.running = this.run().finally(() => {
      this.running = null;
    });
    return this.running;
  }

  retry(): Promise<void> {
    if (this.state.phase !== 'failed' && this.state.phase !== 'cancelled')
      return this.running ?? Promise.resolve();
    return this.start();
  }

  cancel(): void {
    this.abort.abort();
    if (this.state.phase !== 'done') this.set({ phase: 'cancelled', error: '已取消上传' });
  }

  private isAborted(): boolean {
    return this.abort.signal.aborted;
  }

  private fail(e: unknown): void {
    if (this.isAborted()) return;
    if (isApiError(e)) {
      this.set({ phase: 'failed', error: e.message, requestId: e.requestId });
    } else if (e instanceof PartPutError) {
      this.set({ phase: 'failed', error: e.message });
    } else {
      this.set({ phase: 'failed', error: e instanceof Error ? e.message : '上传失败，请重试' });
    }
  }

  private async run(): Promise<void> {
    const { file, role, versionOfFileId } = this.input;
    try {
      this.set({ error: null, requestId: null });
      if (file.size < 1 || file.size > MAX_FILE_BYTES) {
        throw new PartPutError(
          0,
          file.size < 1 ? '文件为空，无法上传' : '文件超过 100 MiB 上限，请按分册拆分后上传',
        );
      }
      if (!this.sha256) {
        this.set({ phase: 'hashing', hashedBytes: 0 });
        this.sha256 = await this.hash(file, {
          signal: this.abort.signal,
          onProgress: (h) => this.set({ hashedBytes: h }),
        });
      }
      if (!this.session) {
        this.set({ phase: 'initializing' });
        this.session = await this.deps.init(
          {
            original_name: file.name,
            role,
            byte_size: file.size,
            sha256: this.sha256,
            media_type: file.type || 'application/octet-stream',
            version_of_file_id: versionOfFileId ?? null,
          },
          { idempotencyKey: this.initKey },
        );
        this.set({
          parts: this.session.parts.map((p) => ({
            partNumber: p.part_number,
            status: 'pending',
            attempts: 0,
            etag: null,
            error: null,
          })),
        });
      }
      this.set({ phase: 'uploading' });
      // 失败过的分片重置为 pending 以便续传；已完成分片保留其 ETag。
      for (const p of this.state.parts) {
        if (p.status === 'failed')
          this.patchPart(p.partNumber, { status: 'pending', attempts: 0, error: null });
      }
      await this.uploadPending();
      if (this.isAborted()) return;
      const failed = this.state.parts.filter((p) => p.status !== 'done');
      if (failed.length > 0) {
        const first = failed.find((p) => p.error);
        this.set({
          phase: 'failed',
          error: `${String(failed.length)} 个分片上传失败${first?.error ? `：${first.error}` : ''}。已完成的分片已保留，可点击重试继续。`,
        });
        return;
      }
      this.set({ phase: 'completing' });
      const parts: CompletedPart[] = this.state.parts
        .map((p) => ({ part_number: p.partNumber, etag: p.etag ?? '' }))
        .sort((a, b) => a.part_number - b.part_number);
      const version = await this.deps.complete(
        this.session.upload_id,
        { sha256: this.sha256, parts },
        { idempotencyKey: this.completeKey },
      );
      this.set({ phase: 'done', version });
    } catch (e) {
      this.fail(e);
    }
  }

  private async uploadPending(): Promise<void> {
    const queue = this.state.parts.filter((p) => p.status === 'pending').map((p) => p.partNumber);
    const worker = async (): Promise<void> => {
      for (;;) {
        if (this.isAborted()) return;
        const n = queue.shift();
        if (n === undefined) return;
        try {
          await this.uploadPart(n);
        } catch (e) {
          queue.length = 0; // 不可恢复的错误：其余分片不再启动
          throw e;
        }
      }
    };
    const workers = Array.from({ length: Math.min(MAX_PARALLEL_PARTS, queue.length) }, () =>
      worker(),
    );
    await Promise.all(workers);
  }

  private urlFor(n: number): { url: string; expiresAt: number } {
    const p = this.session?.parts.find((x) => x.part_number === n);
    if (!p) throw new PartPutError(0, `缺少分片 ${String(n)} 的上传地址`);
    return { url: p.url, expiresAt: Date.parse(p.expires_at) };
  }

  private async refresh(): Promise<void> {
    // 并发的多个分片同时发现过期时，只发一次刷新请求。
    this.refreshing ??= (async () => {
      if (this.refreshCount >= MAX_URL_REFRESHES) {
        throw new PartPutError(403, '上传地址多次过期，请重新开始上传');
      }
      this.refreshCount++;
      if (!this.session) return;
      const fresh = await this.deps.refreshUrls(this.session.upload_id);
      this.session = { ...this.session, parts: fresh.parts, expires_at: fresh.expires_at };
    })().finally(() => {
      this.refreshing = null;
    });
    return this.refreshing;
  }

  private async uploadPart(n: number): Promise<void> {
    const pb = this.session?.part_bytes ?? 0;
    const start = (n - 1) * pb;
    const blob = this.input.file.slice(start, start + this.partSize(n));
    this.patchPart(n, { status: 'uploading', error: null });
    let attempts = 0;
    for (;;) {
      if (this.isAborted()) return;
      try {
        let target = this.urlFor(n);
        if (target.expiresAt - this.now() < URL_EXPIRY_MARGIN_MS) {
          await this.refresh();
          target = this.urlFor(n);
        }
        const etag = await this.deps.putPart(target.url, blob, this.abort.signal);
        this.patchPart(n, { status: 'done', etag, attempts: attempts + 1, error: null });
        return;
      } catch (e) {
        if (this.isAborted()) return;
        // 刷新地址本身失败（如 401/404/不可重试）：不再逐片重试，直接抛给整体流程。
        if (e instanceof ApiError && !e.retryable) throw e;
        attempts++;
        const expired = e instanceof PartPutError && e.status === 403;
        const message = e instanceof Error ? e.message : '分片上传失败';
        if (expired && !(e instanceof ApiError)) {
          try {
            await this.refresh();
          } catch (re) {
            if (re instanceof PartPutError || isApiError(re)) {
              this.patchPart(n, { status: 'failed', attempts, error: re.message });
              return;
            }
            throw re;
          }
          // 过期刷新后的重试不消耗普通重试次数，但总刷新次数有上限。
          attempts--;
          continue;
        }
        if (attempts >= MAX_PART_ATTEMPTS) {
          this.patchPart(n, { status: 'failed', attempts, error: message });
          return;
        }
        this.patchPart(n, { attempts, error: message });
        await this.sleep(400 * 2 ** (attempts - 1));
      }
    }
  }
}

/** 浏览器实现：fetch PUT 直传预签名地址并读取 ETag。必须不带 cookie/自定义头，避免预签名校验失败与多余的 CORS 预检。 */
export async function fetchPutPart(
  url: string,
  body: Blob | { arrayBuffer(): Promise<ArrayBuffer> },
  signal: AbortSignal,
  fetchImpl: typeof fetch = (...a) => globalThis.fetch(...a),
): Promise<string> {
  let res: Response;
  try {
    res = await fetchImpl(url, {
      method: 'PUT',
      body: body as Blob,
      signal,
      credentials: 'omit',
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new PartPutError(0, '网络中断，分片未传完');
  }
  if (!res.ok) {
    throw new PartPutError(
      res.status,
      res.status === 403 ? '上传地址已失效' : `存储服务返回 HTTP ${String(res.status)}`,
    );
  }
  const etag = res.headers.get('ETag');
  if (!etag) {
    throw new PartPutError(
      res.status,
      '读不到存储服务返回的 ETag：存储桶跨域配置需要暴露 ETag 响应头，请联系管理员',
    );
  }
  return etag;
}
