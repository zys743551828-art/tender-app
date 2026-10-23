import { useEffect, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import type {
  PackageReviewReportView,
  PackageReviewRunView,
} from "./contracts";
import { ErrorNotice } from "./components";
import { packageReviewEnded } from "./packageReviewProtocol";
import { definitelyRejectedPackageReview } from "./packageReviewRecovery";
import { usePackageScopeGuard } from "./packageScopeGuard";
import type { PendingPackageReviewCancel } from "./packageReviewRecovery";
import { validPackageReviewReportOperation } from "./packageReviewReportProtocol";
import {
  loadPackageReviewReportCancel,
  storePackageReviewReportCancel,
} from "./packageReviewReportRecovery";
type Props = {
  memberId: string;
  run: PackageReviewRunView;
  report: PackageReviewReportView;
  onReload: () => Promise<void>;
};
export default function PackageReviewReportCancel({
  memberId,
  run,
  report,
  onReload,
}: Props) {
  const [loaded] = useState(() => {
    try {
      return {
        pending: loadPackageReviewReportCancel(memberId, run, report),
        error: null,
      };
    } catch (error) {
      return { pending: null, error };
    }
  });
  const [pending, setPending] = useState(loaded.pending),
    [reason, setReason] = useState(loaded.pending?.body.reason ?? ""),
    [open, setOpen] = useState(!!loaded.pending),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(loaded.error),
    [notice, setNotice] = useState("");
  const pendingRef = useRef(pending),
    active = useRef(false),
    writing = useRef(false);
  const path = `/operations/${report.operation.id}`,
    available =
      supportsApi("GET", path) && supportsApi("POST", `${path}/cancel`);
  usePackageScopeGuard(`cancel-report:${memberId}:${report.id}`, {
    busy,
    pending: !!pending || !!loaded.error,
    dirty: !!reason && !pending,
  });
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  function persist(value: PendingPackageReviewCancel | null) {
    storePackageReviewReportCancel(memberId, run, report, value);
    pendingRef.current = value;
    setPending(value);
  }
  async function cancel(recover: boolean) {
    if (
      !active.current ||
      writing.current ||
      !available ||
      loaded.error ||
      (!recover &&
        (pendingRef.current ||
          !reason.trim() ||
          Array.from(reason.trim()).length > 2000 ||
          packageReviewEnded(report.operation.state)))
    )
      return;
    let request = recover ? pendingRef.current : null;
    if (recover && !request) return;
    writing.current = true;
    setBusy(true);
    setError(null);
    setNotice("");
    try {
      if (!request) {
        const { data, etag } = await api<unknown>(path);
        if (!active.current) return;
        if (!validPackageReviewReportOperation(data, report) || !etag)
          throw new Error("报告任务身份或状态版本不符，未请求取消其他任务。");
        if (packageReviewEnded(data.state)) {
          setOpen(false);
          setReason("");
          setNotice("报告任务已经结束，未发送新的取消请求。已重新读取原报告。");
          await onReload();
          return;
        }
        request = {
          key: crypto.randomUUID(),
          etag,
          body: { reason: reason.trim(), cancel_pending_same_input: false },
        };
        persist(request);
      }
      let data: unknown;
      try {
        ({ data } = await api<unknown>(`${path}/cancel`, {
          method: "POST",
          body: request.body,
          key: request.key,
          etag: request.etag,
        }));
      } catch (failure) {
        if (active.current && definitelyRejectedPackageReview(failure))
          persist(null);
        throw failure;
      }
      if (!validPackageReviewReportOperation(data, report))
        throw new Error("取消回执与此份报告任务不符，原请求仍保留。");
      if (!active.current) return;
      setNotice("报告取消回执已确认，最终生成状态以重读报告为准。");
      persist(null);
      setOpen(false);
      setReason("");
      await onReload();
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      writing.current = false;
      if (active.current) setBusy(false);
    }
  }
  if (!available && !pending && !loaded.error) return null;
  return (
    <div className="package-review__cancel">
      {!packageReviewEnded(report.operation.state) && !pending && (
        <button
          type="button"
          className="text-button"
          disabled={busy || !!loaded.error}
          onClick={() => setOpen(!open)}
          aria-expanded={open}
        >
          取消此份报告生成
        </button>
      )}
      {pending ? (
        <div className="package-review__notice">
          <strong>原报告取消请求尚未确认</strong>
          <p>{pending.body.reason}</p>
          <button
            type="button"
            className="button secondary"
            disabled={busy || !available}
            onClick={() => void cancel(true)}
          >
            恢复原报告取消请求
          </button>
        </div>
      ) : (
        open && (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void cancel(false);
            }}
          >
            <label>
              取消报告生成的理由
              <textarea
                rows={2}
                value={reason}
                maxLength={2000}
                disabled={busy}
                onChange={(event) => setReason(event.target.value)}
              />
            </label>
            <p className="muted">
              仅取消这份报告转换，原机器核查结果和人工记录保留。
            </p>
            <button
              className="button secondary"
              disabled={
                busy ||
                !available ||
                !!loaded.error ||
                !reason.trim() ||
                packageReviewEnded(report.operation.state)
              }
            >
              确认取消此份报告
            </button>
          </form>
        )
      )}
      {!pending && !!reason && (
        <button
          type="button"
          className="text-button"
          disabled={busy}
          onClick={() => {
            setReason("");
            setOpen(false);
          }}
        >
          放弃未发送的报告取消理由
        </button>
      )}
      {notice && <p role="status">{notice}</p>}
      {error != null && <ErrorNotice error={error} />}
    </div>
  );
}
