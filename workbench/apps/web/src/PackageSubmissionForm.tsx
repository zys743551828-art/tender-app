import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type {
  PackageSubmissionPreview,
  PackageSubmissionRequest,
  PackageSubmissionSelection,
  PackageSubmissionView,
  SubmissionView,
} from "./contracts";
import { ArtifactActions } from "./ArtifactActions";
import { ErrorNotice } from "./components";
import { PackageSubmissionGates } from "./PackageSubmissionGates";
import { PackageSubmissionPreflight } from "./PackageSubmissionPreflight";
import { PackageSubmissionSelection as SelectionEditor } from "./PackageSubmissionSelection";
import { SubmissionDocumentChoices } from "./SubmissionDocuments";
import { useSubmissionDocuments } from "./useSubmissionDocuments";
import {
  packageSubmissionBase,
  sameSubmissionValue,
  submissionTime,
  validatePackageSubmission,
  validatePackageSubmissionPreview,
  validPackageSubmissionRequest,
  type PackageSubmissionScope,
  type PendingPackageSubmission,
} from "./packageSubmissionProtocol";

export function PackageSubmissionForm({
  scope,
  correction,
  restored,
  locked,
  invalidate,
  onBusy,
  onSend,
}: {
  scope: PackageSubmissionScope;
  correction: SubmissionView | null;
  restored: PendingPackageSubmission | null;
  locked: boolean;
  invalidate: number;
  onBusy: (value: boolean) => void;
  onSend: (pending: PendingPackageSubmission) => Promise<void>;
}) {
  const initial =
    correction?.subject_kind === "bid_package" ? correction : null;
  const correctionId = correction?.id ?? restored?.supersedesId ?? null;
  const docs = useSubmissionDocuments(scope.bidId);
  const [selection, setSelection] = useState<PackageSubmissionSelection | null>(
    null,
  );
  const [preview, setPreview] = useState<PackageSubmissionPreview | null>(null);
  const [evidenceId, setEvidenceId] = useState(
    restored?.body.evidence.document_version_id ??
      correction?.evidence_ref ??
      "",
  );
  const [submittedAt, setSubmittedAt] = useState(
    restored?.body.submitted_at ?? correction?.submitted_at ?? "",
  );
  const [explanation, setExplanation] = useState(
    restored?.body.explanation ?? correction?.explanation ?? "",
  );
  const [reason, setReason] = useState(restored?.body.correction_reason ?? "");
  const [acknowledged, setAcknowledged] = useState(false),
    [reading, setReading] = useState(false),
    [error, setError] = useState<unknown>(null);
  const active = useRef(false),
    working = useRef(false),
    currentSelection = useRef(selection);
  currentSelection.current = selection;
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    onBusy(reading);
    return () => onBusy(false);
  }, [reading, onBusy]);
  useEffect(() => {
    setPreview(null);
    setAcknowledged(false);
  }, [invalidate]);
  const changeSelection = useCallback(
    (next: PackageSubmissionSelection | null) => {
      if (sameSubmissionValue(currentSelection.current, next)) return;
      currentSelection.current = next;
      setSelection(next);
      setPreview(null);
      setAcknowledged(false);
      setError(null);
    },
    [],
  );
  const evidence = docs.items.find((d) => d.document_version_id === evidenceId);
  async function observe(chosen: PackageSubmissionSelection) {
    if (correctionId) {
      const { data } = await api<SubmissionView>(
        `/submissions/${correctionId}`,
      );
      if (
        data.id !== correctionId ||
        data.bid_id !== scope.bidId ||
        !data.current
      )
        throw new Error(
          "更正目标已不是当前实交记录。原输入保留，请从统一历史重新选择当前记录。",
        );
      if (data.subject_kind === "bid_package")
        await validatePackageSubmission(data, scope.bidId, data.id);
    }
    const { data } = await api<PackageSubmissionPreview>(
      `${packageSubmissionBase(scope.bidId, chosen)}/submission-preview`,
      { method: "POST", body: chosen },
    );
    await validatePackageSubmissionPreview(data, chosen, scope.bidId);
    if (
      correctionId
        ? data.current_submission_head?.id !== correctionId
        : data.current_submission_head !== null
    )
      throw new Error(
        correctionId
          ? "当前实交头已变化，不能更正其他记录。请保留输入并重新选择。"
          : "此项目已经有当前实交记录，请从统一历史明确选择追加更正。",
      );
    return data;
  }
  async function read() {
    if (!selection || locked || working.current) return;
    const chosen = structuredClone(selection);
    working.current = true;
    setReading(true);
    setError(null);
    setAcknowledged(false);
    setPreview(null);
    try {
      const next = await observe(chosen);
      if (
        active.current &&
        sameSubmissionValue(currentSelection.current, chosen)
      )
        setPreview(next);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      working.current = false;
      if (active.current) setReading(false);
    }
  }
  async function submit() {
    if (locked || working.current || !selection || !preview || !acknowledged)
      return;
    working.current = true;
    setReading(true);
    setError(null);
    try {
      if (
        !evidence ||
        docs.loading ||
        docs.error ||
        !explanation.trim() ||
        (correctionId && !reason.trim())
      )
        throw new Error(
          "请明确选择本项目声明附件、真实提交时间和事实依据；追加更正还需说明更正理由。",
        );
      if (!sameSubmissionValue(selection, preview.selection_request))
        throw new Error("整包选择已变化，请重新读取四类检查。");
      const body: PackageSubmissionRequest = {
        kind: "offline_fact",
        selection: structuredClone(selection),
        input_digest: preview.input_digest,
        evidence: {
          document_version_id: evidence.document_version_id,
          digest: evidence.digest,
          byte_size: evidence.byte_size,
        },
        submitted_at: submissionTime(submittedAt),
        explanation: explanation.trim(),
        expected_head:
          correctionId && preview.current_submission_head
            ? {
                id: preview.current_submission_head.id,
                revision: preview.current_submission_head.revision,
              }
            : null,
        correction_reason: correctionId ? reason.trim() : null,
      };
      if (!validPackageSubmissionRequest(body))
        throw new Error(
          "登记字段不符合协议，请核对固定身份、原件大小、摘要与说明。",
        );
      const fresh = await observe(body.selection);
      if (!active.current) return;
      if (
        fresh.input_digest !== preview.input_digest ||
        fresh.bid_etag !== preview.bid_etag ||
        !sameSubmissionValue(
          fresh.current_submission_head,
          preview.current_submission_head,
        )
      ) {
        setPreview(null);
        setAcknowledged(false);
        throw new Error(
          "保存前项目、来源或实交头发生变化。输入已保留，尚未发送登记；请重新读取并明确核对四类检查。",
        );
      }
      await onSend({
        key: crypto.randomUUID(),
        body,
        etag: preview.bid_etag,
        supersedesId: correctionId,
      });
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      working.current = false;
      if (active.current) setReading(false);
    }
  }
  const disabled = locked || reading;
  return (
    <div className="package-submission-form">
      {correctionId && (
        <div className="notice neutral">
          <strong>追加整包更正</strong>
          <p>
            明确更正
            {correction?.subject_kind === "bid_package"
              ? "整包"
              : correction
                ? "单稿"
                : "原"}
            实交记录 <span className="digest">{correctionId}</span>
            ；原记录及其历史身份继续保留。
          </p>
        </div>
      )}
      <SelectionEditor
        bidId={scope.bidId}
        memberId={scope.memberId}
        initial={initial as PackageSubmissionView | null}
        restoredSelection={restored?.body.selection}
        disabled={disabled}
        onChange={changeSelection}
      />
      <button
        type="button"
        className="button secondary"
        disabled={disabled || !selection}
        onClick={() => void read()}
      >
        {reading ? "正在核对固定输入…" : "读取所选整包的提交检查"}
      </button>
      <p className="small-note">
        读取检查只观察所选输入，不登记提交事实。更改选择后需重新读取。
      </p>
      <ErrorNotice error={error} />
      {preview && (
        <PackageSubmissionGates key={preview.gate.digest} gate={preview.gate} />
      )}
      {preview && (
        <PackageSubmissionPreflight
          key={`${scope.bidId}:${scope.memberId}:${preview.gate.digest}`}
          scope={scope}
          preview={preview}
          disabled={disabled}
        />
      )}
      {preview && (
        <>
          <div className="package-submission-modes">
            <div>
              <h3>标准登记</h3>
              <p>四类检查尚未具备完整放行依据。</p>
              <button type="button" className="button secondary" disabled>
                标准登记不可用
              </button>
            </div>
            <div>
              <h3>线下事实补录</h3>
              <p>
                适用于确实已经发生的提交。此记录保留未通过完整系统检查的标记，关闭或归档项目也不会因此重新开放。
              </p>
            </div>
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
          >
            <h3>3. 据实登记已发生的提交</h3>
            <fieldset disabled={disabled}>
              <label>
                真实提交时间（ISO 格式，含时区）
                <input
                  value={submittedAt}
                  onChange={(e) => {
                    setSubmittedAt(e.target.value);
                    setAcknowledged(false);
                  }}
                  placeholder="例如 2026-10-20T14:30:00+08:00"
                  required
                  inputMode="text"
                />
              </label>
              <p className="small-note">
                明确填写当地时区；支持最多六位小数，保留原有微秒。不会用登记时间替代实际发生时间。
              </p>
              <SubmissionDocumentChoices
                resource={docs}
                value={evidenceId}
                onChange={(id) => {
                  setEvidenceId(id);
                  setAcknowledged(false);
                }}
                label="本项目提交声明附件"
              />
              {evidence && (
                <div className="package-submission-selected">
                  <p>
                    {evidence.original_name} · {evidence.byte_size} 字节
                  </p>
                  <p className="digest">
                    原件版本 {evidence.document_version_id} · SHA256{" "}
                    {evidence.digest}
                  </p>
                  <ArtifactActions
                    bidId={scope.bidId}
                    documentId={evidence.document_version_id}
                    isPdf={evidence.media_type === "application/pdf"}
                    expectedMediaType={evidence.media_type}
                    downloadLabel="下载声明附件核对"
                  />
                </div>
              )}
              <p className="small-note">
                目录提供已登记的原件身份。保存时服务端会重新读取并核验包内原件、附件及来源链字节；元数据匹配不能证明回执真实。
              </p>
              <label>
                未经过完整检查的原因与已发生事实依据
                <textarea
                  rows={4}
                  maxLength={2000}
                  required
                  value={explanation}
                  onChange={(e) => {
                    setExplanation(e.target.value);
                    setAcknowledged(false);
                  }}
                />
              </label>
              {correctionId && (
                <label>
                  本次追加更正理由
                  <textarea
                    rows={3}
                    maxLength={2000}
                    required
                    value={reason}
                    onChange={(e) => {
                      setReason(e.target.value);
                      setAcknowledged(false);
                    }}
                  />
                </label>
              )}
              <label className="package-submission-ack">
                <input
                  type="checkbox"
                  checked={acknowledged}
                  onChange={(e) => setAcknowledged(e.target.checked)}
                />
                <span>
                  我已核对固定整包、真实时间和附件；明确按线下已发生事实保存，不声明交易平台回执已验真或事前系统检查已通过。
                </span>
              </label>
              <button
                type="submit"
                className="button primary"
                disabled={
                  !acknowledged ||
                  !evidence ||
                  !submittedAt ||
                  !explanation.trim() ||
                  (!!correctionId && !reason.trim()) ||
                  docs.loading ||
                  !!docs.error
                }
              >
                {correctionId ? "确认追加整包更正" : "确认登记整包线下事实"}
              </button>
            </fieldset>
          </form>
        </>
      )}
    </div>
  );
}
