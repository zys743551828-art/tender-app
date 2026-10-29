import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { ArtifactActions } from "./ArtifactActions";
import { ErrorNotice, Loading } from "./components";
import type { PackageSubmissionView, WorkContextSelection } from "./contracts";
import { validatePackageSubmission } from "./packageSubmissionProtocol";
import { PackageSubmissionGates } from "./PackageSubmissionGates";
import "./PackageSubmission.css";
import { PackageSubmissionReviewActions } from "./PackageSubmissionReviewActions";
import type { PackageNavigationTarget } from "./packageNavigation";

type Selection = Extract<WorkContextSelection, { kind: "package_submission" }>;
export function WorkContextSubmissionDetails(p: {
  selection: Selection;
  onClose: () => void;
  memberId?: string;
  onOpenPackage?: (target: PackageNavigationTarget) => void;
  onOpenRules?: () => void;
}) {
  return <SubmissionDetails key={JSON.stringify(p.selection)} {...p} />;
}
function SubmissionDetails({
  selection,
  onClose,
  memberId,
  onOpenPackage,
  onOpenRules,
}: {
  selection: Selection;
  onClose: () => void;
  memberId?: string;
  onOpenPackage?: (target: PackageNavigationTarget) => void;
  onOpenRules?: () => void;
}) {
  const [record, setRecord] = useState<PackageSubmissionView | null>(null),
    [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false),
    [shown, setShown] = useState(20);
  const active = useRef(false),
    running = useRef(false),
    ticket = useRef(0);
  const load = useCallback(async () => {
    if (running.current || !active.current) return;
    running.current = true;
    const request = ++ticket.current;
    setBusy(true);
    setError(null);
    try {
      const response = await api<PackageSubmissionView>(
        `/submissions/${selection.submission_id}`,
      );
      const checked = await validatePackageSubmission(
        response.data,
        selection.bid_id,
        selection.submission_id,
      );
      const subject = checked.package_binding.manifest.subject;
      if (
        checked.package_binding.digest !== selection.package_binding_digest ||
        subject.package_id !== selection.package_id ||
        subject.revision_id !== selection.revision_id ||
        subject.package_digest !== selection.package_digest
      )
        throw new Error("实交原记录与所选固定包身份不一致，请重新核对原选择。");
      if (active.current && request === ticket.current) setRecord(checked);
    } catch (failure) {
      if (active.current && request === ticket.current) setError(failure);
    } finally {
      if (active.current && request === ticket.current) {
        running.current = false;
        setBusy(false);
      }
    }
  }, [selection]);
  useEffect(() => {
    active.current = true;
    void load();
    const requests = ticket;
    return () => {
      active.current = false;
      running.current = false;
      requests.current++;
    };
  }, [load]);
  const m = record?.package_binding.manifest;
  return (
    <section className="work-context-original" aria-label="所选实交原记录">
      <div className="section-heading">
        <h3>所选实交原记录</h3>
        <button type="button" className="button secondary" onClick={onClose}>
          收起原实交
        </button>
      </div>
      {busy && <Loading text="正在核对实交原记录及完整冻结绑定…" />}
      {error != null && (
        <ErrorNotice error={error} onRetry={() => void load()} />
      )}
      {error != null && record && (
        <p className="notice warning">
          本次未能更新，下面保留上次核验的历史记录。
        </p>
      )}
      {record && m && (
        <>
          <p>
            实际提交于{" "}
            <time dateTime={record.submitted_at}>{record.submitted_at}</time>
            ，登记于{" "}
            <time dateTime={record.recorded_at}>{record.recorded_at}</time>。
          </p>
          <p>{record.explanation}</p>
          {memberId && (
            <PackageSubmissionReviewActions
              record={record}
              memberId={memberId}
              onOpenPackage={onOpenPackage}
              onOpenRules={onOpenRules}
            />
          )}
          <p className="small-note">
            该记录保留用户登记的提交事实。登记时原件核验与本次历史阅读分别记录；交易平台回执和事前系统检查真实性仍未验证。
          </p>
          {record.supersedes_id && (
            <details>
              <summary>追加更正关系</summary>
              <p>
                更正自 <span className="digest">{record.supersedes_id}</span>。
              </p>
              <p>{record.correction_reason}</p>
            </details>
          )}
          <details>
            <summary>登记时的检查与风险</summary>
            <PackageSubmissionGates gate={m.gate} historical />
          </details>
          <details>
            <summary>{m.originals.length} 份登记原件与来源</summary>
            <ul className="package-submission-originals">
              {m.originals.slice(0, shown).map((original) => (
                <li key={original.document_version_id}>
                  <strong>{original.original_name || "未命名原件"}</strong>
                  <p>{original.byte_size} 字节</p>
                  <ArtifactActions
                    bidId={selection.bid_id}
                    documentId={original.document_version_id}
                    isPdf={original.media_type === "application/pdf"}
                    expectedMediaType={original.media_type}
                    downloadLabel={`下载 ${original.original_name || "原件"}`}
                  />
                  <details>
                    <summary>原件固定身份</summary>
                    <p className="digest">
                      版本 {original.document_version_id}
                    </p>
                    <p className="digest">SHA256 {original.digest}</p>
                  </details>
                </li>
              ))}
            </ul>
            {shown < m.originals.length && (
              <button
                type="button"
                className="text-button"
                onClick={() => setShown((value) => value + 20)}
              >
                显示更多原件
              </button>
            )}
          </details>
          <button
            type="button"
            className="text-button"
            disabled={busy}
            onClick={() => void load()}
          >
            重读同一实交原记录
          </button>
        </>
      )}
    </section>
  );
}
