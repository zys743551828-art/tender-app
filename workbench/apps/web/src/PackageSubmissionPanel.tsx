import { useCallback, useEffect, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import type {
  PackageSubmissionAppliedView,
  PackageSubmissionView,
  SubmissionView,
} from "./contracts";
import { ErrorNotice } from "./components";
import { PackageSubmissionForm } from "./PackageSubmissionForm";
import {
  definitelyRejectedPackageSubmission,
  packageSubmissionPath,
  sameSubmissionValue,
  validatePackageSubmissionAck,
  type PendingPackageSubmission,
} from "./packageSubmissionProtocol";
import {
  readPackageSubmissionRecovery,
  writePackageSubmissionRecovery,
  type PackageSubmissionRecovery,
} from "./packageSubmissionRecovery";
import "./PackageSubmission.css";

export type PackageSubmissionOpenRequest = {
  sequence: number;
  correction: SubmissionView;
};
export function PackageSubmissionPanel({
  bidId,
  memberId,
  disabled,
  hasCurrent,
  request,
  onLock,
  onSaved,
}: {
  bidId: string;
  memberId: string;
  disabled: boolean;
  hasCurrent: boolean;
  request: PackageSubmissionOpenRequest | null;
  onLock: (value: boolean) => void;
  onSaved: (record: PackageSubmissionView) => void;
}) {
  const [initial] = useState(() => {
    const scope = { bidId, memberId };
    try {
      return { record: readPackageSubmissionRecovery(scope), error: null };
    } catch (error) {
      return {
        record: {
          version: 1,
          scope,
          pending: null,
          lastId: null,
        } as PackageSubmissionRecovery,
        error,
      };
    }
  });
  const [recovery, setRecovery] = useState(initial.record),
    [opened, setOpened] = useState(!!initial.record.pending || !!initial.error);
  const [busy, setBusy] = useState(false),
    [reading, setReading] = useState(false),
    [error, setError] = useState<unknown>(initial.error),
    [notice, setNotice] = useState("");
  const [correction, setCorrection] = useState<SubmissionView | null>(null),
    [editor, setEditor] = useState(0),
    [invalidate, setInvalidate] = useState(0);
  const [restored, setRestored] = useState(initial.record.pending);
  const active = useRef(false),
    running = useRef(false),
    record = useRef(recovery),
    seenRequest = useRef(0);
  const onReadBusy = useCallback((v: boolean) => setReading(v), []);
  const available = supportsApi(
    "POST",
    `/bids/${bidId}/packages/_/revisions/_/submissions`,
  );
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    onLock(opened || busy || !!recovery.pending || !!initial.error);
    return () => onLock(false);
  }, [opened, busy, recovery.pending, initial.error, onLock]);
  useEffect(() => {
    if (
      !request ||
      request.sequence === seenRequest.current ||
      busy ||
      reading ||
      recovery.pending ||
      initial.error
    )
      return;
    seenRequest.current = request.sequence;
    setCorrection(request.correction);
    setRestored(null);
    setEditor((n) => n + 1);
    setOpened(true);
    setError(null);
    setNotice("");
  }, [request, busy, reading, recovery.pending, initial.error]);
  function remember(next: PackageSubmissionRecovery) {
    writePackageSubmissionRecovery(next);
    record.current = next;
    setRecovery(next);
  }
  async function send(pending: PendingPackageSubmission) {
    if (!available || running.current || initial.error || !active.current)
      return;
    if (
      record.current.pending &&
      !sameSubmissionValue(record.current.pending, pending)
    ) {
      setError(new Error("尚有未核对的整包登记原请求，不能以新的内容替代。"));
      return;
    }
    running.current = true;
    setBusy(true);
    setError(null);
    setNotice("");
    try {
      if (!record.current.pending) remember({ ...record.current, pending });
      const result = await api<PackageSubmissionAppliedView>(
        packageSubmissionPath(bidId, pending),
        {
          method: "POST",
          key: pending.key,
          body: pending.body,
          etag: pending.etag,
        },
      );
      const checked = await validatePackageSubmissionAck(
        result.data,
        result.bidEtag,
        { bidId, memberId },
        pending,
      );
      if (!active.current) return;
      remember({ ...record.current, pending: null, lastId: checked.id });
      setNotice(
        "整包线下实交记录及原件绑定已保存，完整检查未通过的标记保留。统一历史已刷新。",
      );
      setOpened(false);
      setCorrection(null);
      setRestored(null);
      setEditor((n) => n + 1);
      onSaved(checked);
    } catch (failure) {
      if (!active.current) return;
      if (
        record.current.pending &&
        definitelyRejectedPackageSubmission(failure)
      ) {
        try {
          remember({ ...record.current, pending: null });
          setInvalidate((n) => n + 1);
          setNotice(
            "服务已明确拒绝本次登记，尚未写入；输入保留，请重新读取检查后核对。",
          );
        } catch (storageFailure) {
          setError(storageFailure);
          return;
        }
      }
      setError(failure);
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  if (!available) return null;
  return (
    <section
      className="panel package-submission-panel"
      aria-label="整包提交检查与线下事实登记"
    >
      <div className="section-heading">
        <div>
          <h2>整包提交检查与实交登记</h2>
          <p className="small-note">
            固定完整资料包及关联核查，核对四类检查；据实记录已发生的提交与追加更正。
          </p>
        </div>
        {opened ? (
          <button
            type="button"
            className="button secondary"
            disabled={busy || reading || !!recovery.pending || !!initial.error}
            onClick={() => setOpened(false)}
          >
            收起整包登记
          </button>
        ) : (
          <button
            type="button"
            className="button primary"
            disabled={disabled || hasCurrent || busy || !!initial.error}
            onClick={() => {
              setCorrection(null);
              setRestored(null);
              setEditor((n) => n + 1);
              setOpened(true);
              setNotice("");
            }}
          >
            检查并登记整包线下事实
          </button>
        )}
      </div>
      {!opened && hasCurrent && (
        <p className="small-note">
          已有当前实交记录，请在下方统一历史中明确选择追加更正。
        </p>
      )}
      <ErrorNotice error={error} />
      {notice && (
        <p className="notice neutral" role="status">
          {notice}
        </p>
      )}
      {recovery.pending && (
        <div className="notice warning" role="status">
          <div>
            <strong>整包登记结果尚未核对</strong>
            <p>
              保留了原包修订、附件、时间、条件版本与操作身份。读取历史不等于取得原命令回执；恢复会使用完全相同的请求。
            </p>
            <details>
              <summary>核对待恢复的固定请求</summary>
              <dl>
                <dt>包修订</dt>
                <dd className="digest">
                  {recovery.pending.body.selection.revision_id}
                </dd>
                <dt>包摘要</dt>
                <dd className="digest">
                  {recovery.pending.body.selection.package_digest}
                </dd>
                <dt>实际提交时间</dt>
                <dd>{recovery.pending.body.submitted_at}</dd>
                <dt>事实依据</dt>
                <dd>{recovery.pending.body.explanation}</dd>
                <dt>更正目标</dt>
                <dd className="digest">
                  {recovery.pending.supersedesId ?? "首次登记"}
                </dd>
                <dt>声明附件</dt>
                <dd className="digest">
                  {recovery.pending.body.evidence.document_version_id}
                </dd>
              </dl>
            </details>
            <button
              type="button"
              className="button secondary"
              disabled={busy}
              onClick={() => void send(recovery.pending!)}
            >
              {busy ? "正在恢复原登记…" : "恢复原整包登记结果"}
            </button>
          </div>
        </div>
      )}
      {opened && !initial.error && (
        <PackageSubmissionForm
          key={editor}
          scope={initial.record.scope}
          correction={correction}
          restored={restored}
          locked={disabled || busy || !!recovery.pending}
          invalidate={invalidate}
          onBusy={onReadBusy}
          onSend={send}
        />
      )}
    </section>
  );
}
