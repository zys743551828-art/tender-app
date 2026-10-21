import { useEffect, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import type { PackageReviewRunView } from "./contracts";
import { ErrorNotice } from "./components";
import type { DependencyProps } from "./inputDependencyProtocol";
import {
  packageReviewEnded,
  validPackageReviewOperation,
} from "./packageReviewProtocol";
import {
  loadPackageReviewCancel,
  storePackageReviewCancel,
  definitelyRejectedPackageReview,
} from "./packageReviewRecovery";
import type { PendingPackageReviewCancel } from "./packageReviewRecovery";

type Props = DependencyProps & {
  run: PackageReviewRunView;
  onReload: () => Promise<void>;
};
export default function PackageReviewCancel(props: Props) {
  const { run } = props;
  const [loaded] = useState(() => {
    try {
      return { pending: loadPackageReviewCancel(props, run), error: null };
    } catch (error) {
      return { pending: null, error };
    }
  });
  const [pending, setPending] = useState(loaded.pending);
  const pendingRef = useRef(pending),
    active = useRef(false),
    writing = useRef(false);
  const [open, setOpen] = useState(!!loaded.pending),
    [busy, setBusy] = useState(false);
  const [reason, setReason] = useState(loaded.pending?.body.reason ?? "");
  const [error, setError] = useState<unknown>(loaded.error),
    [notice, setNotice] = useState("");
  const path = `/operations/${run.operation.id}`,
    available =
      supportsApi("GET", path) && supportsApi("POST", `${path}/cancel`);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  function persist(next: PendingPackageReviewCancel | null) {
    storePackageReviewCancel(props, run, next);
    pendingRef.current = next;
    setPending(next);
  }
  async function cancel(recover: boolean) {
    if (
      !active.current ||
      writing.current ||
      !available ||
      loaded.error ||
      (!recover && pendingRef.current)
    )
      return;
    if (
      !recover &&
      (!reason.trim() ||
        Array.from(reason.trim()).length > 2000 ||
        packageReviewEnded(run.operation.state))
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
        const { data: operation, etag } = await api<unknown>(path);
        if (!active.current) return;
        if (!validPackageReviewOperation(operation, run) || !etag)
          throw new Error("任务身份或状态版本不符，未请求取消其他任务。");
        if (packageReviewEnded(operation.state)) {
          setNotice("任务已经结束，未再发送取消请求。已重新读取本次核查状态。");
          setOpen(false);
          await props.onReload();
          return;
        }
        request = {
          key: crypto.randomUUID(),
          etag,
          body: { reason: reason.trim(), cancel_pending_same_input: false },
        };
        persist(request);
      }
      let response: unknown;
      try {
        ({ data: response } = await api<unknown>(`${path}/cancel`, {
          method: "POST",
          body: request.body,
          etag: request.etag,
          key: request.key,
        }));
      } catch (failure) {
        if (active.current && definitelyRejectedPackageReview(failure))
          persist(null);
        throw failure;
      }
      if (!validPackageReviewOperation(response, run))
        throw new Error("取消回执与本次核查任务不符，原取消请求仍保留。");
      if (!active.current) return;
      persist(null);
      setOpen(false);
      setNotice("取消请求已确认，最终状态以重新读取的本次核查记录为准。");
      await props.onReload();
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      writing.current = false;
      if (active.current) setBusy(false);
    }
  }
  if (!available && !loaded.error && !pending) return null;
  return (
    <div className="package-review__cancel">
      {!packageReviewEnded(run.operation.state) && !pending && (
        <button
          type="button"
          className="text-button"
          disabled={busy || !!loaded.error}
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          取消本次核查
        </button>
      )}
      {pending ? (
        <div className="package-review__notice">
          <strong>原取消请求尚未确认</strong>
          <p>取消理由：{pending.body.reason}</p>
          <p>恢复只重放这次任务的原请求和状态版本，不会取消其他核查。</p>
          <button
            type="button"
            className="button secondary"
            disabled={busy || !available}
            onClick={() => void cancel(true)}
          >
            {busy ? "正在恢复取消回执…" : "恢复原取消请求"}
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
              取消本次核查的理由
              <textarea
                rows={2}
                maxLength={2000}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                required
                disabled={busy}
              />
            </label>
            <p className="muted">
              仅取消这次任务。已完成的记录保留，外部调用可能已经产生费用。
            </p>
            <button
              className="button secondary"
              disabled={
                busy ||
                !available ||
                !!loaded.error ||
                !reason.trim() ||
                packageReviewEnded(run.operation.state)
              }
            >
              {busy ? "正在核对取消结果…" : "确认请求取消"}
            </button>
          </form>
        )
      )}
      {notice && <p role="status">{notice}</p>}
      {error != null && <ErrorNotice error={error} />}
    </div>
  );
}
