import type { ErrorBody } from './types';

/** 前端按"类别"分支，而不是到处比较错误码字符串。 */
export type ErrorKind =
  | 'auth' // 401：回登录
  | 'forbidden' // 403
  | 'not_found' // 404（不泄漏其他项目是否存在）
  | 'stale' // 412 STALE_VERSION：保留输入并提示刷新
  | 'precondition' // 428
  | 'validation' // 422：字段错误，显示 message
  | 'conflict' // 409
  | 'rate_limit' // 429
  | 'unavailable' // 503 / 网络失败：可重试
  | 'other';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly retryable: boolean;
  readonly details: Record<string, unknown>;
  readonly kind: ErrorKind;

  constructor(init: {
    status: number;
    code: string;
    message: string;
    requestId?: string | null;
    retryable?: boolean;
    details?: Record<string, unknown>;
  }) {
    super(init.message);
    this.name = 'ApiError';
    this.status = init.status;
    this.code = init.code;
    this.requestId = init.requestId ?? null;
    this.details = init.details ?? {};
    this.kind = classify(init.status, init.code);
    this.retryable = init.retryable ?? (this.kind === 'unavailable' || this.kind === 'rate_limit');
  }

  /** 错误码比较不区分大小写（契约写 STALE_VERSION，部分文档写 stale_version）。 */
  is(code: string): boolean {
    return this.code.toUpperCase() === code.toUpperCase();
  }
}

function classify(status: number, code: string): ErrorKind {
  const c = code.toUpperCase();
  if (status === 401 || c === 'AUTH_REQUIRED') return 'auth';
  if (status === 412 || c === 'STALE_VERSION') return 'stale';
  if (status === 428 || c === 'PRECONDITION_REQUIRED') return 'precondition';
  if (status === 403) return 'forbidden';
  if (status === 404) return 'not_found';
  if (status === 422) return 'validation';
  if (status === 429) return 'rate_limit';
  if (status === 409) return 'conflict';
  if (status === 503 || status === 502 || status === 504 || status === 0) return 'unavailable';
  return 'other';
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

const FALLBACK_MESSAGES: Partial<Record<number, string>> = {
  400: '请求内容无法处理，请检查后重试',
  401: '请先登录',
  403: '没有执行该操作的权限',
  404: '对象不存在，或你无权访问',
  412: '内容已被他人修改，请刷新后重试',
  429: '请求过于频繁，请稍后再试',
  502: '服务暂时不可用，请稍后重试',
  503: '服务暂时不可用，请稍后重试',
  504: '服务响应超时，请稍后重试',
};

/** 把非 2xx 响应转成 ApiError；响应体不是契约 Error 结构时按状态码给中文兜底，不展示原始 HTML。 */
export function errorFromResponse(
  status: number,
  body: unknown,
  headerRequestId: string | null,
): ApiError {
  if (isRecord(body) && typeof body.code === 'string' && typeof body.message === 'string') {
    const parsed = body as Partial<ErrorBody> & { code: string; message: string };
    return new ApiError({
      status,
      code: parsed.code,
      message: parsed.message,
      requestId: typeof parsed.request_id === 'string' ? parsed.request_id : headerRequestId,
      retryable: typeof parsed.retryable === 'boolean' ? parsed.retryable : undefined,
      details: isRecord(parsed.details) ? parsed.details : {},
    });
  }
  return new ApiError({
    status,
    code: `HTTP_${String(status)}`,
    message: FALLBACK_MESSAGES[status] ?? `请求失败（HTTP ${String(status)}）`,
    requestId: headerRequestId,
  });
}

export function networkError(cause: unknown): ApiError {
  const err = new ApiError({
    status: 0,
    code: 'NETWORK_ERROR',
    message: '无法连接服务器，请检查网络后重试',
    retryable: true,
  });
  if (cause instanceof Error) err.cause = cause;
  return err;
}

/** 供页面展示：标题、正文、请求编号、是否值得提供"重试"。 */
export function describeError(e: unknown): {
  message: string;
  requestId: string | null;
  retryable: boolean;
  kind: ErrorKind;
} {
  if (isApiError(e)) {
    const message =
      e.kind === 'stale'
        ? `${e.message}。你输入的内容已保留，刷新后可对照新版本再提交。`
        : e.message;
    return { message, requestId: e.requestId, retryable: e.retryable, kind: e.kind };
  }
  return {
    message: e instanceof Error && e.message ? e.message : '发生未知错误，请重试',
    requestId: null,
    retryable: true,
    kind: 'other',
  };
}
