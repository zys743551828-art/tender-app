import { useEffect, useId, useRef, useState } from "react";
import { api, roleNames, sizeLabel, supportsApi } from "./api";
import type {
  DocumentParseContext,
  DocumentParsePage,
  DocumentParseStarted,
  DocumentParseView,
} from "./contracts";
import { ErrorNotice } from "./components";
import { executionId } from "./executionInputValidation";
import {
  assertDocumentParseUpdate,
  definitelyRejectedDocumentParse,
  documentParseContextPath,
  documentParsePath,
  documentParseStateLabels,
  sameDocumentParseRequest,
  validDocumentParseReason,
  validateDocumentParseContext,
  validateDocumentParsePage,
  validateDocumentParseStarted,
  validateDocumentParseView,
} from "./documentParseProtocol";
import type {
  DocumentParseScope,
  PendingDocumentParse,
} from "./documentParseProtocol";
import {
  loadDocumentParseRecord,
  storeDocumentParseRecord,
} from "./documentParseRecovery";
import type { DocumentParseRecord } from "./documentParseRecovery";
import DocumentParseProgress from "./DocumentParseProgress";
import { rememberOperation } from "./operationStorage";
import "./DocumentParseWorkspace.css";

type Props = DocumentParseScope & {
  disabled?: boolean;
  onParsed?: (value: DocumentParseView) => void;
};
export default function DocumentParseWorkspace(props: Props) {
  if (![props.memberId, props.bidId, props.documentId].every(executionId))
    return (
      <p className="notice error">
        请先选择本项目的已提交原件，再读取解析条件。
      </p>
    );
  return (
    <Workspace
      key={`${props.memberId}:${props.bidId}:${props.documentId}`}
      {...props}
    />
  );
}
function Workspace(props: Props) {
  const [scope] = useState<DocumentParseScope>(() => ({
    memberId: props.memberId,
    bidId: props.bidId,
    documentId: props.documentId,
  }));
  const [loaded] = useState(() => {
    try {
      return { record: loadDocumentParseRecord(scope), error: null };
    } catch (error) {
      return { record: null, error };
    }
  });
  const [record, setRecord] = useState(loaded.record),
    [expanded, setExpanded] = useState(
      !!loaded.record?.pending || loaded.error !== null,
    ),
    [context, setContext] = useState<DocumentParseContext | null>(null),
    [reason, setReason] = useState(loaded.record?.pending?.body.reason ?? ""),
    [view, setView] = useState<DocumentParseView | null>(null),
    [receipt, setReceipt] = useState<DocumentParseStarted | null>(null),
    [page, setPage] = useState<DocumentParsePage | null>(null),
    [error, setError] = useState<unknown>(loaded.error),
    [busy, setBusy] = useState(false);
  const active = useRef(false),
    working = useRef(false),
    ticket = useRef(0),
    recordRef = useRef(record),
    seenCursors = useRef(new Set<string>()),
    seenIds = useRef(new Set<string>()),
    currentView = useRef(view),
    rememberedOperations = useRef(new Set<string>());
  const panelId = useId(),
    reasonId = useId(),
    path = documentParsePath(scope),
    canRead = supportsApi("GET", path),
    canWrite = supportsApi("POST", path),
    canContext = supportsApi("GET", documentParseContextPath(scope));
  useEffect(() => {
    active.current = true;
    const requests = ticket;
    return () => {
      active.current = false;
      requests.current++;
    };
  }, []);
  function persist(next: DocumentParseRecord) {
    storeDocumentParseRecord(next);
    recordRef.current = next;
    setRecord(next);
  }
  function acceptView(value: DocumentParseView) {
    currentView.current = value;
    setView(value);
    if (!rememberedOperations.current.has(value.operation.id)) {
      rememberedOperations.current.add(value.operation.id);
      try {
        rememberOperation(scope.bidId, value.operation.id);
      } catch {
        // This optional task-center index cannot change an accepted parse or its recovery record.
      }
    }
  }
  async function readContext() {
    if (!active.current || working.current || !canContext) return;
    const current = ++ticket.current;
    working.current = true;
    setBusy(true);
    setError(null);
    try {
      const received = await validateDocumentParseContext(
        (await api<unknown>(documentParseContextPath(scope))).data,
        scope,
      );
      if (active.current && current === ticket.current) setContext(received);
    } catch (failure) {
      if (active.current && current === ticket.current) {
        setContext(null);
        setError(failure);
      }
    } finally {
      if (active.current && current === ticket.current) {
        working.current = false;
        setBusy(false);
      }
    }
  }
  async function start(recover = false) {
    const prior = recordRef.current;
    if (!active.current || working.current || !prior || !canWrite) return;
    const pending: PendingDocumentParse | null = recover
      ? prior.pending
      : !props.disabled &&
          !prior.pending &&
          context &&
          validDocumentParseReason(reason.trim())
        ? {
            key: crypto.randomUUID(),
            body: {
              context_digest: context.context_digest,
              reason: reason.trim(),
            },
          }
        : null;
    if (!pending) return;
    const current = ++ticket.current;
    working.current = true;
    setBusy(true);
    setError(null);
    setReceipt(null);
    try {
      // Quota and storage permission failures must happen before the first POST.
      persist({ ...prior, pending });
      let data: unknown;
      try {
        ({ data } = await api<unknown>(path, {
          method: "POST",
          body: pending.body,
          key: pending.key,
        }));
      } catch (failure) {
        if (
          active.current &&
          current === ticket.current &&
          definitelyRejectedDocumentParse(failure)
        ) {
          persist({ ...prior, pending: null });
          setContext(null);
        }
        throw failure;
      }
      const received = await validateDocumentParseStarted(data, scope, pending);
      if (!active.current || current !== ticket.current) return;
      const known = currentView.current;
      if (
        known?.id === received.request.id &&
        !sameDocumentParseRequest(known, received.request)
      )
        throw new Error("解析回执与已读取的原申请身份不符，原请求仍需核对。");
      // Recovering an old ACK must not regress a newer GET result already on screen.
      setReceipt(received);
      acceptView(known?.id === received.request.id ? known : received.request);
      // A stable ACK can still describe an old queued state. Progress rereads the exact request.
      persist({ ...prior, pending: null, lastId: received.request.id });
    } catch (failure) {
      if (active.current && current === ticket.current) setError(failure);
    } finally {
      if (active.current && current === ticket.current) {
        working.current = false;
        setBusy(false);
      }
    }
  }
  async function history(next = false) {
    if (
      !active.current ||
      working.current ||
      !canRead ||
      (next && !page?.next_cursor)
    )
      return;
    const current = ++ticket.current,
      cursor = next ? page!.next_cursor! : null;
    working.current = true;
    setBusy(true);
    setError(null);
    try {
      const received = await validateDocumentParsePage(
        (
          await api<unknown>(
            `${path}?limit=10${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
          )
        ).data,
        scope,
      );
      if (
        next &&
        (seenCursors.current.has(cursor!) ||
          received.next_cursor === cursor ||
          received.items.some((item) => seenIds.current.has(item.id)))
      )
        throw new Error("解析历史返回重复记录或游标，请从首页重新读取。");
      if (!active.current || current !== ticket.current) return;
      if (!next) {
        seenCursors.current.clear();
        seenIds.current.clear();
      } else seenCursors.current.add(cursor!);
      received.items.forEach((item) => seenIds.current.add(item.id));
      setPage(received);
    } catch (failure) {
      if (active.current && current === ticket.current) setError(failure);
    } finally {
      if (active.current && current === ticket.current) {
        working.current = false;
        setBusy(false);
      }
    }
  }
  async function read(id: string) {
    if (!active.current || working.current || !canRead || !executionId(id))
      return;
    const current = ++ticket.current;
    working.current = true;
    setBusy(true);
    setError(null);
    try {
      const received = await validateDocumentParseView(
        (await api<unknown>(`${path}/${id}`)).data,
        scope,
        id,
      );
      if (!active.current || current !== ticket.current) return;
      if (currentView.current?.id === received.id)
        await assertDocumentParseUpdate(currentView.current, received);
      if (!active.current || current !== ticket.current) return;
      acceptView(received);
      setReceipt(null);
      if (recordRef.current)
        persist({ ...recordRef.current, lastId: received.id });
    } catch (failure) {
      if (active.current && current === ticket.current) setError(failure);
    } finally {
      if (active.current && current === ticket.current) {
        working.current = false;
        setBusy(false);
      }
    }
  }
  return (
    <section className="document-parse" aria-label="原件解析">
      <button
        type="button"
        className="button secondary"
        aria-expanded={expanded}
        aria-controls={panelId}
        onClick={() => setExpanded((value) => !value)}
      >
        {expanded ? "收起原件解析" : "解析原件与查看历史"}
        {record?.pending ? " · 有待恢复申请" : ""}
      </button>
      {expanded && (
        <div id={panelId} className="document-parse__body">
          <h4>原件解析</h4>
          <p>
            读取这个文件版本的物理页与可提取内容。解析结果需要另行明确选入包成员，不会自动采用正文或启动核查。
          </p>
          {props.disabled && (
            <p className="notice">
              当前项目为只读状态，可读取历史或恢复原申请；新解析申请已暂停。
            </p>
          )}
          {loaded.error !== null && <ErrorNotice error={loaded.error} />}
          {!canRead && (
            <p className="notice">
              当前服务尚未提供独立原件解析，请等待服务版本就绪。
            </p>
          )}
          {record?.pending && (
            <div className="notice" role="status">
              <p>
                原解析申请尚待核对。恢复会使用相同申请内容和请求编号；当前文件条件变化不会替换原请求。
              </p>
              <p>原申请理由：{record.pending.body.reason}</p>
              <button
                type="button"
                className="button primary"
                disabled={busy || !canWrite}
                onClick={() => void start(true)}
              >
                恢复原解析申请
              </button>
            </div>
          )}
          <div className="document-parse__actions">
            <button
              type="button"
              className="button secondary"
              disabled={busy || !canContext || !!record?.pending}
              onClick={() => void readContext()}
            >
              读取当前解析条件
            </button>
            <button
              type="button"
              className="button secondary"
              disabled={busy || !canRead}
              onClick={() => void history()}
            >
              读取解析历史
            </button>
            {record?.lastId && (
              <button
                type="button"
                className="button secondary"
                disabled={busy || !canRead}
                onClick={() => void read(record.lastId!)}
              >
                继续查看上次解析
              </button>
            )}
          </div>
          {context && (
            <div className="document-parse__context">
              <p>
                <strong>{context.context.document.filename}</strong> ·{" "}
                {roleNames[context.context.document.role]} ·{" "}
                {sizeLabel(context.context.document.byte_size)} · 文件第{" "}
                {context.context.document.file_revision} 版
              </p>
              <p>
                {context.context.qualification.kind === "adopted_generated"
                  ? "生成文件已有明确采用凭证。"
                  : "原件已有上传核验记录。"}
                本轮上限为 100 MiB、1,000 个物理页。
              </p>
              <p className="notice">
                {context.context.method.mode === "physical_text_only"
                  ? "当前仅提取 PDF 物理页文本，不能认定图像、复杂表格或全部内容已完整解析。"
                  : "当前使用已配置的本地解析服务；实际覆盖范围与缺口以本次结果为准。"}
                此入口不证明 Word 原稿覆盖。
              </p>
              <details>
                <summary>查看原件与方法摘要</summary>
                <p>
                  原件摘要：<code>{context.context.document.sha256}</code>
                </p>
                <p>
                  解析条件摘要：<code>{context.context_digest}</code>
                </p>
                <p>
                  方法摘要：
                  <code>{context.context.method.implementation_digest}</code>
                </p>
              </details>
            </div>
          )}
          <label htmlFor={reasonId}>解析理由（必填，最多 1,000 字）</label>
          <input
            id={reasonId}
            value={reason}
            disabled={busy || !!record?.pending || !!props.disabled || !record}
            onChange={(event) => setReason(event.target.value)}
            placeholder="说明这次解析要核对的内容"
          />
          {reason !== "" && !validDocumentParseReason(reason.trim()) && (
            <p className="notice">
              请填写不超过 1,000 字的单行理由，不含控制字符。
            </p>
          )}
          <button
            type="button"
            className="button primary"
            disabled={
              busy ||
              !!props.disabled ||
              !record ||
              !!record.pending ||
              !context ||
              !canWrite ||
              !validDocumentParseReason(reason.trim())
            }
            onClick={() => void start()}
          >
            明确申请解析此文件版本
          </button>
          {receipt && (
            <p className="notice" role="status">
              {receipt.reused
                ? "申请回执已确认，复用相同解析条件下的已有记录。"
                : "解析申请回执已确认，实际运行状态以重读记录为准。"}
              本次申请成员：<code>{receipt.actor_id}</code>；原记录申请者：
              <code>{receipt.request.actor_id}</code>。
            </p>
          )}
          {error !== null && error !== loaded.error && (
            <ErrorNotice error={error} />
          )}
          {view && (
            <DocumentParseProgress
              key={view.id}
              scope={scope}
              view={view}
              onChange={(value) => {
                if (currentView.current?.id === value.id) acceptView(value);
              }}
              onParsed={(value) => {
                if (currentView.current?.id === value.id)
                  props.onParsed?.(value);
              }}
            />
          )}
          {page && (
            <section aria-label="解析历史" className="document-parse__history">
              <h5>解析历史</h5>
              {page.items.length === 0 ? (
                <p>这个文件版本暂无解析申请。</p>
              ) : (
                <ul>
                  {page.items.map((item) => (
                    <li key={item.id}>
                      <div>
                        <strong>
                          {documentParseStateLabels[item.operation.state]}
                        </strong>
                        <p>{item.reason}</p>
                        <small>
                          {new Date(item.created_at).toLocaleString()} ·
                          原申请者 {item.actor_id}
                        </small>
                      </div>
                      <button
                        type="button"
                        className="button secondary"
                        disabled={busy}
                        onClick={() => void read(item.id)}
                      >
                        查看这次解析
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <p className="muted">
                每页最多 10 条，读取历史不会重新发起解析。
              </p>
              <button
                type="button"
                className="button secondary"
                disabled={busy || !page.has_more}
                onClick={() => void history(true)}
              >
                下一页解析历史
              </button>
            </section>
          )}
        </div>
      )}
    </section>
  );
}
