import { useEffect, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import type {
  PackageReviewReportContext,
  PackageReviewReportPage,
  PackageReviewReportView,
  PackageReviewRunView,
} from "./contracts";
import { ErrorNotice } from "./components";
import { executionId } from "./executionInputValidation";
import type { DependencyProps } from "./inputDependencyProtocol";
import { definitelyRejectedPackageReview } from "./packageReviewRecovery";
import {
  packageReviewReportPath,
  validatePackageReviewReport,
  validatePackageReviewReportContext,
  validatePackageReviewReportPage,
} from "./packageReviewReportProtocol";
import type { PendingPackageReviewReport } from "./packageReviewReportProtocol";
import {
  loadPackageReviewReportRecord,
  packageReviewReportScope,
  storePackageReviewReportRecord,
} from "./packageReviewReportRecovery";
import type { PackageReviewReportRecord } from "./packageReviewReportRecovery";
import PackageReviewReportProgress from "./PackageReviewReportProgress";
import { usePackageScopeGuard } from "./packageScopeGuard";

type Props = DependencyProps & { run: PackageReviewRunView };
export default function PackageReviewReportExports(p: Props) {
  return p.run.result && p.run.operation.state === "succeeded" ? (
    <Exports
      key={JSON.stringify(packageReviewReportScope(p.scope.memberId, p.run))}
      {...p}
    />
  ) : null;
}
function Exports(p: Props) {
  const [loaded] = useState(() => {
    try {
      return {
        record: loadPackageReviewReportRecord(p.scope.memberId, p.run),
        error: null,
      };
    } catch (error) {
      return { record: null, error };
    }
  });
  const [record, setRecord] = useState(loaded.record),
    [context, setContext] = useState<PackageReviewReportContext | null>(null),
    [format, setFormat] = useState<"docx" | "pdf">("docx"),
    [report, setReport] = useState<PackageReviewReportView | null>(null),
    [page, setPage] = useState<PackageReviewReportPage | null>(null),
    [reportId, setReportId] = useState(loaded.record?.lastId ?? ""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(loaded.error),
    [receipt, setReceipt] = useState(false);
  const recordRef = useRef(record),
    active = useRef(false),
    working = useRef(false),
    ticket = useRef(0),
    seenCursors = useRef(new Set<string>()),
    seenIds = useRef(new Set<string>());
  const path = packageReviewReportPath(p, p.run),
    contextPath = path.replace(/\/report-exports$/, "/report-context"),
    writable = supportsApi("POST", path),
    readable = supportsApi("GET", path);
  usePackageScopeGuard(
    `report:${JSON.stringify(packageReviewReportScope(p.scope.memberId, p.run))}`,
    { busy, pending: !!record?.pending || !!loaded.error },
  );
  useEffect(() => {
    active.current = true;
    const requests = ticket;
    return () => {
      active.current = false;
      requests.current++;
    };
  }, []);
  function persist(next: PackageReviewReportRecord) {
    storePackageReviewReportRecord(p.scope.memberId, p.run, next);
    recordRef.current = next;
    setRecord(next);
  }
  async function readContext() {
    if (!active.current || working.current) return;
    const request = ++ticket.current;
    working.current = true;
    setBusy(true);
    setError(null);
    try {
      const { data } = await api<unknown>(contextPath),
        received = validatePackageReviewReportContext(data, p.run);
      if (!active.current || request !== ticket.current) return;
      setContext(received);
      if (!received.formats.includes(format)) setFormat("docx");
    } catch (failure) {
      if (active.current && request === ticket.current) {
        setError(failure);
        setContext(null);
      }
    } finally {
      if (active.current && request === ticket.current) {
        working.current = false;
        setBusy(false);
      }
    }
  }
  async function start(recover: boolean) {
    const current = recordRef.current;
    if (!active.current || working.current || !current || !writable) return;
    const pending: PendingPackageReviewReport | null = recover
      ? current.pending
      : !current.pending && context?.formats.includes(format)
        ? {
            key: crypto.randomUUID(),
            body: { context_digest: context.context_digest, format },
          }
        : null;
    if (!pending) return;
    const request = ++ticket.current;
    working.current = true;
    setBusy(true);
    setError(null);
    setReceipt(false);
    try {
      persist({ ...current, pending });
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
          request === ticket.current &&
          definitelyRejectedPackageReview(failure)
        ) {
          persist({ ...current, pending: null });
          setContext(null);
        }
        throw failure;
      }
      const received = validatePackageReviewReport(data, p.run, pending);
      if (!active.current || request !== ticket.current) return;
      // The original ACK can predate today's terminal state; the detail component rereads it.
      setReport(received);
      setReportId(received.id);
      setReceipt(true);
      persist({ ...current, pending: null, lastId: received.id });
    } catch (failure) {
      if (active.current && request === ticket.current) setError(failure);
    } finally {
      if (active.current && request === ticket.current) {
        working.current = false;
        setBusy(false);
      }
    }
  }
  async function list(next = false) {
    if (
      !active.current ||
      working.current ||
      !readable ||
      (next && !page?.next_cursor)
    )
      return;
    const request = ++ticket.current,
      cursor = next ? page!.next_cursor! : null;
    working.current = true;
    setBusy(true);
    setError(null);
    try {
      const { data } = await api<unknown>(
          `${path}?limit=10${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        ),
        received = validatePackageReviewReportPage(data, p.run);
      if (
        next &&
        (seenCursors.current.has(cursor!) ||
          received.next_cursor === cursor ||
          received.items.some((item) => seenIds.current.has(item.id)))
      )
        throw new Error("报告历史返回重复游标或记录，请从首页重新读取。");
      if (!active.current || request !== ticket.current) return;
      if (!next) {
        seenCursors.current.clear();
        seenIds.current.clear();
      } else seenCursors.current.add(cursor!);
      received.items.forEach((item) => seenIds.current.add(item.id));
      setPage(received);
    } catch (failure) {
      if (active.current && request === ticket.current) setError(failure);
    } finally {
      if (active.current && request === ticket.current) {
        working.current = false;
        setBusy(false);
      }
    }
  }
  async function read(id: string) {
    if (!active.current || working.current || !readable || !executionId(id))
      return;
    const request = ++ticket.current;
    working.current = true;
    setBusy(true);
    setError(null);
    setReceipt(false);
    try {
      const { data } = await api<unknown>(`${path}/${id}`),
        received = validatePackageReviewReport(data, p.run, id);
      if (!active.current || request !== ticket.current) return;
      setReport(received);
      setReportId(id);
      if (recordRef.current) persist({ ...recordRef.current, lastId: id });
    } catch (failure) {
      if (active.current && request === ticket.current) setError(failure);
    } finally {
      if (active.current && request === ticket.current) {
        working.current = false;
        setBusy(false);
      }
    }
  }
  return (
    <section
      className="package-review__exports"
      aria-label="整包范围核查报告副本"
    >
      <h4>生成报告副本</h4>
      <p>
        报告包含本轮全部已列要求、机器判断、原引用，以及申请时的人工意见。后续人工更新不会回写已生成副本。生成报告不执行新核查，也不授予正式评分或投递资格。
      </p>
      {!writable && (
        <p className="package-review__notice">
          当前服务尚未提供整包报告生成接口。
        </p>
      )}
      {!record && (
        <p className="package-review__notice">
          浏览器原申请无法核验，新申请已暂停；仍可读取报告历史。
        </p>
      )}
      <button
        type="button"
        className="button secondary"
        disabled={busy || !supportsApi("GET", contextPath)}
        onClick={() => void readContext()}
      >
        读取报告生成依据
      </button>
      {context && (
        <div className="package-review__selected">
          <strong>已读取生成依据</strong>
          <p>
            人工意见按这份依据冻结；如果其他成员更新，申请会要求重新读取并由你确认。
          </p>
          <label>
            报告格式
            <select
              value={format}
              disabled={busy || !!record?.pending}
              onChange={(event) =>
                setFormat(event.target.value as "docx" | "pdf")
              }
            >
              <option value="docx">Word 文档（.docx）</option>
              {context.formats.includes("pdf") && (
                <option value="pdf">PDF 文档（.pdf）</option>
              )}
            </select>
          </label>
          {!context.formats.includes("pdf") && (
            <p className="muted">当前未配置 PDF 转换能力，可生成 Word 报告。</p>
          )}
          <details>
            <summary>核对报告生成依据</summary>
            <p>
              依据摘要：<code>{context.context_digest}</code>
            </p>
            <p>
              人工意见摘要：<code>{context.human_decisions_digest}</code>
            </p>
            <p>
              报告方法摘要：<code>{context.method_digest}</code>
            </p>
          </details>
        </div>
      )}
      {record?.pending ? (
        <div className="package-review__notice">
          <strong>原报告申请尚未确认</strong>
          <p>
            恢复使用原格式、原人工意见快照和同一幂等键，当前新读取的依据不会替换原申请。
          </p>
          <button
            type="button"
            className="button primary"
            disabled={busy || !writable}
            onClick={() => void start(true)}
          >
            恢复原报告申请
          </button>
        </div>
      ) : (
        <button
          type="button"
          className="button primary"
          disabled={busy || !writable || !record || !context}
          onClick={() => void start(false)}
        >
          申请生成{format === "docx" ? " Word " : " PDF "}报告
        </button>
      )}
      {busy && <p role="status">正在核对报告记录…</p>}
      {receipt && (
        <p role="status">报告申请回执已确认，实际生成状态以重读记录为准。</p>
      )}
      {error != null && <ErrorNotice error={error} />}
      {report && (
        <PackageReviewReportProgress
          key={`${report.id}:${report.report_input_digest}`}
          {...p}
          report={report}
          onChange={setReport}
        />
      )}
      <details className="package-review__history">
        <summary>本轮报告副本历史</summary>
        <p>历史副本保留申请时的人工意见；读取不会生成新副本。</p>
        <div className="package-review__actions">
          <button
            type="button"
            className="button secondary"
            disabled={busy || !readable}
            onClick={() => void list()}
          >
            读取报告历史
          </button>
          {page?.has_more && (
            <button
              type="button"
              className="button secondary"
              disabled={busy}
              onClick={() => void list(true)}
            >
              下一页报告历史
            </button>
          )}
        </div>
        {page?.items.length === 0 && <p>本轮尚无已受理的报告副本。</p>}
        {page && (
          <ul className="package-review__history-list">
            {page.items.map((item) => (
              <li key={item.id}>
                <div>
                  <strong>
                    {item.format === "docx" ? "Word" : "PDF"} 报告 ·{" "}
                    {new Date(item.created_at).toLocaleString()}
                  </strong>
                  <p className="muted">
                    编号：<code>{item.id}</code>
                  </p>
                </div>
                <button
                  type="button"
                  className="button secondary"
                  disabled={busy}
                  onClick={() => void read(item.id)}
                >
                  查看此份报告
                </button>
              </li>
            ))}
          </ul>
        )}
        <form
          className="package-review__lookup"
          onSubmit={(event) => {
            event.preventDefault();
            void read(reportId.trim());
          }}
        >
          <label>
            原报告编号
            <input
              value={reportId}
              onChange={(event) => setReportId(event.target.value)}
              spellCheck={false}
              autoComplete="off"
            />
          </label>
          <button
            className="button secondary"
            disabled={busy || !readable || !executionId(reportId.trim())}
          >
            重读原报告
          </button>
        </form>
      </details>
    </section>
  );
}
