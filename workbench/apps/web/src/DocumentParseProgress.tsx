import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { DocumentParseView } from "./contracts";
import { ErrorNotice } from "./components";
import {
  assertDocumentParseUpdate,
  documentParseEnded,
  documentParsePath,
  documentParseStateLabels,
  validateDocumentParseView,
} from "./documentParseProtocol";
import type { DocumentParseScope } from "./documentParseProtocol";
import DocumentParseOriginal from "./DocumentParseOriginal";

type Props = {
  scope: DocumentParseScope;
  view: DocumentParseView;
  onChange: (value: DocumentParseView) => void;
  onParsed?: (value: DocumentParseView) => void;
};
export default function DocumentParseProgress({
  scope,
  view,
  onChange,
  onParsed,
}: Props) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null),
    [checkedAt, setCheckedAt] = useState("");
  const active = useRef(false),
    reading = useRef(false),
    ticket = useRef(0),
    current = useRef(view),
    callbacks = useRef({ onChange, onParsed }),
    notified = useRef<string | null>(null);
  current.current = view;
  callbacks.current = { onChange, onParsed };
  const path = `${documentParsePath(scope)}/${view.id}`;
  const read = useCallback(async () => {
    if (!active.current || reading.current) return;
    const request = ++ticket.current;
    reading.current = true;
    setBusy(true);
    setError(null);
    try {
      const received = await validateDocumentParseView(
        (await api<unknown>(path)).data,
        scope,
        current.current.id,
      );
      if (!active.current || request !== ticket.current) return;
      await assertDocumentParseUpdate(current.current, received);
      if (!active.current || request !== ticket.current) return;
      current.current = received;
      callbacks.current.onChange(received);
      setCheckedAt(new Date().toLocaleTimeString());
    } catch (failure) {
      if (active.current && request === ticket.current) setError(failure);
    } finally {
      if (active.current && request === ticket.current) {
        reading.current = false;
        setBusy(false);
      }
    }
  }, [path, scope]);
  useEffect(() => {
    active.current = true;
    // Each selected record is reread once, including a terminal historical ACK.
    reading.current = false;
    void read();
    const requests = ticket,
      timer = window.setInterval(() => {
        if (!documentParseEnded(current.current.operation.state)) void read();
      }, 3000);
    return () => {
      active.current = false;
      requests.current++;
      window.clearInterval(timer);
    };
  }, [read]);
  useEffect(() => {
    if (!view.result || view.operation.state !== "succeeded") return;
    const identity = `${view.id}:${view.result.parse_run_id}:${view.result.parsed_digest}`;
    if (notified.current !== identity) {
      notified.current = identity;
      callbacks.current.onParsed?.(view);
    }
  }, [view]);
  const result = view.result;
  return (
    <section className="document-parse__progress" aria-label="本次解析状态">
      <div className="document-parse__actions">
        <h5>{documentParseStateLabels[view.operation.state]}</h5>
        <button
          type="button"
          className="button secondary"
          disabled={busy}
          onClick={() => void read()}
        >
          刷新本次解析状态
        </button>
      </div>
      {checkedAt && <p className="muted">最近成功读取：{checkedAt}</p>}
      {!documentParseEnded(view.operation.state) && (
        <p>
          解析在服务端进行，每 3
          秒读取一次状态。收起或关闭页面不会取消解析，可从历史继续查看；已记入此浏览器“处理记录”的任务可在那里请求取消。
        </p>
      )}
      {view.operation.error_code && (
        <p className="notice">
          运行错误编号：<code>{view.operation.error_code}</code>
          。请核对原因后重新读取解析条件，再决定是否申请。
        </p>
      )}
      {error !== null && (
        <ErrorNotice error={error} onRetry={() => void read()} />
      )}
      {result && (
        <>
          <p className="notice" role="status">
            {result.coverage === "complete"
              ? "本次解析记录声明覆盖完整；内容准确性仍需核对原页。"
              : result.coverage === "partial"
                ? "本次解析仅形成部分覆盖，仍有内容需要补充核对。"
                : "解析运行已结束，但未形成可用覆盖，请核对缺口。"}
          </p>
          <dl className="document-parse__metrics">
            <div>
              <dt>已记录物理页</dt>
              <dd>{result.page_count}</dd>
            </div>
            <div>
              <dt>证据条数</dt>
              <dd>{result.evidence_count}</dd>
            </div>
            <div>
              <dt>记录缺口</dt>
              <dd>{result.gap_count}</dd>
            </div>
          </dl>
          <p>
            解析记录编号：<code>{result.parse_run_id}</code>
          </p>
          <p>
            本页只展示这次解析记录；需要在包成员中明确选择解析版本及部件范围后，才会改变准备输入。此记录不证明
            Word 原稿覆盖。
          </p>
          {result.gaps.length > 0 && (
            <details open>
              <summary>
                解析缺口（显示 {result.gaps.length} / {result.gap_count} 条）
              </summary>
              <ul>
                {result.gaps.map((gap, index) => (
                  <li key={index}>{gap || "未填写缺口说明"}</li>
                ))}
              </ul>
            </details>
          )}
          <DocumentParseOriginal view={view} />
        </>
      )}
      <details>
        <summary>查看本次申请身份</summary>
        <p>
          解析申请：<code>{view.id}</code>
        </p>
        <p>
          后台任务：<code>{view.operation.id}</code>
        </p>
        <p>
          原申请者：<code>{view.actor_id}</code>
        </p>
        <p>原申请理由：{view.reason}</p>
        <p>
          原件摘要：<code>{view.context.document.sha256}</code>
        </p>
        <p>
          冻结解析条件：<code>{view.context_digest}</code>
        </p>
        {result && (
          <p>
            解析结果摘要：<code>{result.parsed_digest}</code>
          </p>
        )}
      </details>
    </section>
  );
}
