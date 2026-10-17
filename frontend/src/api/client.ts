import { errorFromResponse, networkError, ApiError } from './errors';
import { newIdempotencyKey } from '../lib/uuid';
import type { Me, Page } from './types';

export const API_PREFIX = '/api/v1';
const WRITE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

export interface RequestOptions {
  query?: Record<string, string | number | undefined | null>;
  body?: unknown;
  rawBody?: Blob;
  /** If-Match：更新项目与授权时传对象 revision（字符串）。 */
  ifMatch?: string | number;
  /** 同一次用户动作重试时传入同一个键；不传则每次请求生成新键。 */
  idempotencyKey?: string;
  signal?: AbortSignal;
  /** 登录等接口：401 是正常业务结果，不触发全局"回登录"。 */
  skipAuthRedirect?: boolean;
  /** 登录前没有会话，也就没有 CSRF 令牌可取：登录请求不预取 /me。 */
  noCsrf?: boolean;
}

export interface ApiClientOptions {
  fetchImpl?: typeof fetch;
  baseUrl?: string;
  /** 收到 401 AUTH_REQUIRED 时调用（路由层据此清理缓存并跳转登录页）。 */
  onUnauthorized?: () => void;
}

/**
 * 集中处理：路径前缀、JSON、CSRF（仅内存）、Idempotency-Key、If-Match、错误解析、401 跳转。
 * 组件不得直接 fetch；一律经本客户端（PDF.js 原件读取是明确例外，见各自模块）。
 */
export class ApiClient {
  private csrf: string | null = null;
  private csrfPending: Promise<void> | null = null;
  private readonly fetchImpl: typeof fetch;
  private readonly baseUrl: string;
  onUnauthorized: (() => void) | undefined;

  constructor(opts: ApiClientOptions = {}) {
    // 不直接保存 window.fetch 的引用，避免 "Illegal invocation"，且便于测试时替换 globalThis.fetch。
    this.fetchImpl = opts.fetchImpl ?? ((...a: Parameters<typeof fetch>) => globalThis.fetch(...a));
    this.baseUrl = opts.baseUrl ?? '';
    this.onUnauthorized = opts.onUnauthorized;
  }

  setCsrfToken(token: string | null): void {
    this.csrf = token;
  }

  get hasCsrfToken(): boolean {
    return this.csrf !== null;
  }

  url(path: string, query?: RequestOptions['query']): string {
    const u = `${this.baseUrl}${API_PREFIX}${path}`;
    if (!query) return u;
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
    }
    const s = qs.toString();
    return s ? `${u}?${s}` : u;
  }

  async request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
    return (await readBody(await this.requestResponse(method, path, opts))) as T;
  }

  async putBytes(path: string, body: Blob, signal: AbortSignal): Promise<Response> {
    return this.requestResponse('PUT', path, { rawBody: body, signal });
  }

  private async requestResponse(
    method: string,
    path: string,
    opts: RequestOptions,
  ): Promise<Response> {
    const m = method.toUpperCase();
    const isWrite = WRITE_METHODS.has(m);
    // 写请求的幂等键在重试（含 CSRF 刷新后的自动重发）时必须保持不变。
    const idemKey = isWrite ? (opts.idempotencyKey ?? newIdempotencyKey()) : undefined;
    if (isWrite && this.csrf === null && !opts.noCsrf) await this.refreshCsrf();

    for (let attempt = 0; ; attempt++) {
      const res = await this.send(m, path, opts, idemKey);
      if (res.ok) return res;

      const err = errorFromResponse(
        res.status,
        await readBody(res).catch(() => undefined),
        res.headers.get('X-Request-ID'),
      );
      // CSRF 令牌失效（例如会话轮换）：重取 /me 后用同一幂等键自动重发一次。
      if (
        isWrite &&
        !opts.noCsrf &&
        attempt === 0 &&
        err.status === 403 &&
        /CSRF/i.test(err.code)
      ) {
        this.csrf = null;
        await this.refreshCsrf();
        continue;
      }
      if (err.kind === 'auth' && !opts.skipAuthRedirect) {
        this.csrf = null;
        this.onUnauthorized?.();
      }
      throw err;
    }
  }

  private async send(
    method: string,
    path: string,
    opts: RequestOptions,
    idemKey: string | undefined,
  ): Promise<Response> {
    const headers: Record<string, string> = { Accept: 'application/json' };
    let body: string | Blob | undefined = opts.rawBody;
    if (opts.rawBody !== undefined) {
      headers['Content-Type'] = 'application/octet-stream';
    } else if (opts.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(opts.body);
    }
    if (idemKey) {
      headers['Idempotency-Key'] = idemKey;
      if (this.csrf) headers['X-CSRF-Token'] = this.csrf;
    }
    if (opts.ifMatch !== undefined) headers['If-Match'] = String(opts.ifMatch);
    try {
      return await this.fetchImpl(this.url(path, opts.query), {
        method,
        headers,
        body,
        credentials: 'same-origin',
        signal: opts.signal,
      });
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') throw e;
      throw networkError(e);
    }
  }

  /** 取 /me 以获得（或刷新）内存中的 CSRF 令牌；并发调用合并为一次。 */
  private refreshCsrf(): Promise<void> {
    this.csrfPending ??= this.request<Me>('GET', '/me', { skipAuthRedirect: false })
      .then((me) => {
        this.csrf = me.csrf_token;
      })
      .finally(() => {
        this.csrfPending = null;
      });
    return this.csrfPending;
  }

  get<T>(path: string, opts?: RequestOptions): Promise<T> {
    return this.request<T>('GET', path, opts);
  }
  post<T>(path: string, body?: unknown, opts?: RequestOptions): Promise<T> {
    return this.request<T>('POST', path, { ...opts, body });
  }
  put<T>(path: string, body?: unknown, opts?: RequestOptions): Promise<T> {
    return this.request<T>('PUT', path, { ...opts, body });
  }
  patch<T>(path: string, body?: unknown, opts?: RequestOptions): Promise<T> {
    return this.request<T>('PATCH', path, { ...opts, body });
  }
}

async function readBody(res: Response): Promise<unknown> {
  if (res.status === 204 || res.status === 205) return undefined;
  const text = await res.text();
  if (!text) return undefined;
  const ct = res.headers.get('Content-Type') ?? '';
  if (!ct.includes('json')) {
    if (res.ok) return text;
    return undefined;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    if (res.ok)
      throw new ApiError({
        status: res.status,
        code: 'BAD_RESPONSE',
        message: '服务器返回了无法解析的内容',
      });
    return undefined;
  }
}

/** 分页信封：只有问题列表分页，形如 {items, next_cursor}；其余列表接口直接返回数组。 */
export function toPage<T>(raw: { items: T[]; next_cursor: string | null }): Page<T> {
  return { items: raw.items, nextCursor: raw.next_cursor };
}

export const apiClient = new ApiClient();
