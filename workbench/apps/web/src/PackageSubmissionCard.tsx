import { useEffect, useState } from "react";
import type { PackageSubmissionView } from "./contracts";
import { Badge, ErrorNotice } from "./components";
import { ArtifactActions } from "./ArtifactActions";
import { BusinessResults } from "./BusinessResults";
import { PackageOfficialOutcomes } from "./PackageOfficialOutcomes";
import { PackageSubmissionGates } from "./PackageSubmissionGates";
import { validatePackageSubmission } from "./packageSubmissionProtocol";
import { PackageSubmissionReviewActions } from "./PackageSubmissionReviewActions";
import type { PackageNavigationTarget } from "./packageNavigation";

const roles = {
  target: "实际投标包原件",
  authority: "依据包原件",
  submission_attachment: "提交声明附件",
  source_ancestor: "来源链原件",
};
export function PackageSubmissionCard({
  record,
  bidId,
  memberId,
  disabled,
  onCorrect,
  onOpenPackage,
  onOpenRules,
}: {
  record: PackageSubmissionView;
  bidId: string;
  memberId: string;
  disabled: boolean;
  onCorrect: () => void;
  onOpenPackage?: (target: PackageNavigationTarget) => void;
  onOpenRules?: () => void;
}) {
  const [checked, setChecked] = useState<PackageSubmissionView | null>(null),
    [error, setError] = useState<unknown>(null),
    [showGate, setShowGate] = useState(false),
    [shown, setShown] = useState(20);
  useEffect(() => {
    let active = true;
    setChecked(null);
    setError(null);
    void validatePackageSubmission(record, bidId, record.id)
      .then((v) => {
        if (active) setChecked(v);
      })
      .catch((failure) => {
        if (active) setError(failure);
      });
    return () => {
      active = false;
    };
  }, [record, bidId]);
  if (checked !== record)
    return (
      <article className="submission-card package-submission-card">
        <h3>整包实交记录</h3>
        <ErrorNotice error={error} />
        {!error && <p role="status">正在核对整包记录与固定来源…</p>}
      </article>
    );
  const m = record.package_binding.manifest;
  return (
    <article className="submission-card package-submission-card">
      <div className="section-heading">
        <h3>整包实际提交 · 修订 {m.selection.target.manifest.revision}</h3>
        <Badge tone="warning">{record.checks_label}</Badge>
        <Badge>{record.current ? "当前实交记录" : "已留存的历史记录"}</Badge>
      </div>
      <p>
        实际提交于{" "}
        <time dateTime={record.submitted_at}>{record.submitted_at}</time>
        ；登记于 <time dateTime={record.recorded_at}>{record.recorded_at}</time>
        。
      </p>
      <p>
        {record.identity.bidder_name} · {record.identity.engineering_title} · 第{" "}
        {record.identity.round_no} 轮
        {record.identity.binding_status === "pending"
          ? " · 登记身份待确认"
          : ""}
      </p>
      <p className="small-note">
        这是用户声明的线下提交事实。原件字节已核验，交易平台回执真实性与事前系统检查未获验证。
      </p>
      <p>{record.explanation}</p>
      <PackageSubmissionReviewActions
        record={checked}
        memberId={memberId}
        disabled={disabled}
        onOpenPackage={onOpenPackage}
        onOpenRules={onOpenRules}
      />
      {record.supersedes_id && (
        <p className="small-note digest">
          追加更正自 {record.supersedes_id}，原记录继续保留。
        </p>
      )}
      {record.correction_reason && <p>更正理由：{record.correction_reason}</p>}
      <details>
        <summary>固定包、清单与身份</summary>
        <dl>
          <dt>投标包</dt>
          <dd className="digest">{m.subject.package_id}</dd>
          <dt>包修订</dt>
          <dd className="digest">{m.subject.revision_id}</dd>
          <dt>包摘要</dt>
          <dd className="digest">{m.subject.package_digest}</dd>
          <dt>需求清单</dt>
          <dd className="digest">
            {m.selection_request.inventory?.id ?? "明确未关联"}
          </dd>
          <dt>范围声明</dt>
          <dd className="digest">
            {m.selection_request.coverage?.id ?? "明确未关联"}
          </dd>
          <dt>整包核查</dt>
          <dd className="digest">
            {m.selection_request.review_run?.id ?? "明确未关联"}
          </dd>
          <dt>包内冻结身份</dt>
          <dd>
            {m.package_identity.bidder_name} ·{" "}
            {m.package_identity.engineering_title}
            <span className="digest">{m.package_identity.digest}</span>
          </dd>
          <dt>登记时当前身份</dt>
          <dd>
            {m.recorded_identity.bidder_name} ·{" "}
            {m.recorded_identity.engineering_title}
            <span className="digest">{m.recorded_identity.digest}</span>
          </dd>
          <dt>登记绑定摘要</dt>
          <dd className="digest">{record.package_binding.digest}</dd>
        </dl>
      </details>
      <details>
        <summary>核对 {m.originals.length} 份实际原件、附件与来源</summary>
        <ul className="package-submission-originals">
          {m.originals.slice(0, shown).map((o) => (
            <li key={o.document_version_id}>
              <strong>{o.original_name || o.document_version_id}</strong>
              <p>
                {o.roles.map((r) => roles[r]).join(" · ")} · {o.byte_size} 字节
              </p>
              <p className="digest">
                版本 {o.document_version_id} · SHA256 {o.digest}
              </p>
              <ArtifactActions
                bidId={bidId}
                documentId={o.document_version_id}
                isPdf={o.media_type === "application/pdf"}
                downloadLabel={`下载已登记原件 ${o.original_name || o.document_version_id.slice(0, 8)}`}
                expectedMediaType={o.media_type}
              />
            </li>
          ))}
        </ul>
        {shown < m.originals.length && (
          <button
            type="button"
            className="text-button"
            onClick={() => setShown((n) => n + 20)}
          >
            加载更多原件与来源
          </button>
        )}
        <p className="small-note">
          这些身份固定在本次登记中；下载当前取回的原版本不会修改历史记录。
        </p>
      </details>
      <button
        type="button"
        className="text-button"
        aria-expanded={showGate}
        onClick={() => setShowGate((v) => !v)}
      >
        {showGate ? "收起登记时检查与风险" : "查看登记时四类检查与历史风险"}
      </button>
      {showGate && <PackageSubmissionGates gate={m.gate} historical />}
      <BusinessResults bidId={bidId} memberId={memberId} submission={record} />
      <PackageOfficialOutcomes
        bidId={bidId}
        memberId={memberId}
        submission={record}
      />
      {record.current && (
        <button
          type="button"
          className="button secondary"
          disabled={disabled}
          onClick={onCorrect}
        >
          追加更正此整包实交记录
        </button>
      )}
    </article>
  );
}
