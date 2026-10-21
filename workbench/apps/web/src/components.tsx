import type { ReactNode } from "react";
import { ApiError } from "./api";
import "./ResourceFeedback.css";

export function Brand() {
  return (
    <div className="brand">
      <span className="brand-mark" aria-hidden="true">
        投
      </span>
      <span>
        投标工作台<small>整份标书 · AI 辅助</small>
      </span>
    </div>
  );
}
export function Icon({
  name,
}: {
  name:
    | "grid"
    | "briefcase"
    | "archive"
    | "flask"
    | "book"
    | "chart"
    | "assistant"
    | "file"
    | "upload"
    | "arrow"
    | "check"
    | "clock"
    | "back";
}) {
  const paths = {
    briefcase: (
      <>
        <rect x="3" y="7" width="18" height="14" rx="2" />
        <path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12a22 22 0 0 0 18 0M12 12v3" />
      </>
    ),
    archive: (
      <>
        <rect x="3" y="3" width="18" height="5" rx="1" />
        <path d="M5 8v12a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8M9 12h6" />
      </>
    ),
    flask: (
      <>
        <path d="M9 3h6M10 3v6l-5.8 9.7A1.5 1.5 0 0 0 5.5 21h13a1.5 1.5 0 0 0 1.3-2.3L14 9V3M7 14h10" />
        <path d="M10 17h.01M14 18h.01" />
      </>
    ),
    book: (
      <>
        <path d="M12 6c-3-2-6-2-10-1v15c4-1 7-1 10 1 3-2 6-2 10-1V5c-4-1-7-1-10 1Z" />
        <path d="M12 6v15M5 9h3M5 13h3M16 9h3M16 13h3" />
      </>
    ),
    chart: (
      <>
        <path d="M3 3v18h18M8 16v-5M13 16V7M18 16V4" />
      </>
    ),
    assistant: (
      <>
        <path d="M21 13a4 4 0 0 1-4 4h-5l-5 4v-4H6a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3h11a4 4 0 0 1 4 4Z" />
        <path d="m12 6 .9 2.6L15.5 9.5l-2.6.9L12 13l-.9-2.6L8.5 9.5l2.6-.9Z" />
      </>
    ),
    grid: (
      <>
        <rect x="3" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" />
        <rect x="14" y="14" width="7" height="7" rx="1" />
      </>
    ),
    file: (
      <>
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <path d="M14 2v6h6M8 13h8M8 17h5" />
      </>
    ),
    upload: (
      <>
        <path d="M12 16V3m-5 5 5-5 5 5M3 15v5a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1v-5" />
      </>
    ),
    arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
    check: <path d="m5 12 4 4L19 6" />,
    clock: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    back: <path d="M19 12H5m6-6-6 6 6 6" />,
  };
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}
export function ErrorNotice({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  if (!error) return null;
  return (
    <div className="notice error" role="alert">
      <div>
        <strong>本次操作未完成</strong>
        <p>{error instanceof Error ? error.message : String(error)}</p>
        {error instanceof ApiError && (
          <details className="error-details">
            <summary>查看错误详情</summary>
            <dl className="error-reference">
              <dt>错误代码</dt>
              <dd>{error.code}</dd>
              {error.requestId && (
                <>
                  <dt>排查编号</dt>
                  <dd>{error.requestId}</dd>
                </>
              )}
            </dl>
            {error.details !== null &&
              typeof error.details === "object" &&
              Object.keys(error.details).length > 0 && (
                <pre>{JSON.stringify(error.details, null, 2)}</pre>
              )}
          </details>
        )}
      </div>
      {onRetry && (
        <button type="button" className="button secondary" onClick={onRetry}>
          重试
        </button>
      )}
    </div>
  );
}
export function Badge({
  children,
  tone = "",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
export function Loading({ text = "正在读取…" }: { text?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden="true" />
      {text}
    </div>
  );
}

export function LoadingSkeleton({
  text = "正在读取…",
  rows = 3,
}: {
  text?: string;
  rows?: number;
}) {
  return (
    <div className="resource-skeleton" role="status" aria-live="polite">
      <span className="resource-skeleton-label">{text}</span>
      <div className="resource-skeleton-rows" aria-hidden="true">
        {Array.from({ length: Math.max(1, Math.min(6, rows)) }, (_, index) => (
          <div className="resource-skeleton-row" key={index}>
            <span className="resource-skeleton-icon" />
            <span className="resource-skeleton-lines">
              <span />
              <span />
            </span>
            <span className="resource-skeleton-badge" />
          </div>
        ))}
      </div>
    </div>
  );
}
