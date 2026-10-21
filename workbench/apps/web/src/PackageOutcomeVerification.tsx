import { useState } from "react";
import type {
  DocumentEvidenceView,
  PackageOutcomeContext,
  PackageOutcomeVerificationRequest,
  PackageSubmissionView,
  ResearchOutcomeDetail,
} from "./contracts";
import { Badge, ErrorNotice } from "./components";
import { EvidenceLinks } from "./EvidenceLinks";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import { historicalDateTime } from "./historicalImportProtocol";
import {
  outcomeAuthority,
  outcomeIdentity,
  outcomeInstant,
  packageOutcomeReason,
  validOutcomeVerification,
} from "./packageOutcomeProtocol";

export function PackageOutcomeVerification({
  submission,
  context,
  base,
  locked,
  onSubmit,
}: {
  submission: PackageSubmissionView;
  context: PackageOutcomeContext;
  base: ResearchOutcomeDetail;
  locked: boolean;
  onSubmit: (body: PackageOutcomeVerificationRequest) => void;
}) {
  const [state, setState] =
      useState<PackageOutcomeVerificationRequest["state"]>("pending"),
    [reason, setReason] = useState(""),
    [aggregation, setAggregation] = useState(""),
    [published, setPublished] = useState(""),
    [refs, setRefs] = useState<
      PackageOutcomeVerificationRequest["evidence_refs"]
    >([]),
    [error, setError] = useState<unknown>(null),
    [acknowledged, setAcknowledged] = useState(false);
  const source = useResource<DocumentEvidenceView>(
    `/documents/${base.source_version_id}/evidence`,
  );
  const validSource =
    source.data?.document_version_id === base.source_version_id &&
    source.data.items.every(
      (item) =>
        item.document_version_id === base.source_version_id &&
        item.parse_run_id === source.data!.parse_run_id,
    );
  const positiveAllowed =
    context.identity_ready &&
    context.authority !== null &&
    !context.verification_blockers.length;
  return (
    <form
      className="decision-form package-outcome-form"
      aria-label="核验整包官方成绩"
      onSubmit={(event) => {
        event.preventDefault();
        if (locked) return;
        setError(null);
        try {
          const body: PackageOutcomeVerificationRequest = {
            version: "package-outcome-verification/1",
            subject_kind: "bid_package",
            state,
            reason: reason.trim(),
            identity: outcomeIdentity(submission),
            authority: outcomeAuthority(submission),
            aggregation: aggregation.trim(),
            published_at: published.trim()
              ? historicalDateTime(published.trim(), "成绩公布时间")
              : null,
            evidence_refs: refs,
          };
          if (
            !validOutcomeVerification(body, submission, base.source_version_id)
          )
            throw new Error(
              "请填写核验说明；确认核验还需要原提交绑定的依据包、公布时间、聚合方式和成绩原页引文。",
            );
          if (
            refs.length &&
            (!validSource ||
              refs.some(
                (ref) =>
                  !source.data!.items.some(
                    (item) =>
                      item.id === ref.evidence_id &&
                      item.document_version_id === ref.document_version_id &&
                      item.physical_page === ref.physical_page &&
                      item.kind === "text" &&
                      item.quote.includes(ref.quote),
                  ),
              ))
          )
            throw new Error(
              "所选摘录必须逐字来自这一份成绩原件的对应原页，不能改写或拼接。",
            );
          if (state === "verified") {
            const at = outcomeInstant(body.published_at)!;
            if (
              !positiveAllowed ||
              !acknowledged ||
              !validSource ||
              at < outcomeInstant(submission.submitted_at)! ||
              at > outcomeInstant(base.known_at)! ||
              refs.some(
                (ref) =>
                  !source.data!.items.some(
                    (item) =>
                      item.id === ref.evidence_id &&
                      item.document_version_id === ref.document_version_id &&
                      item.physical_page === ref.physical_page &&
                      item.quote.includes(ref.quote) &&
                      item.kind === "text" &&
                      item.source_status === "published",
                  ),
              )
            )
              throw new Error(
                "请核对原提交身份、当前有效原页和时间顺序，并明确确认逐项核验；不能以当前正文代替原整包。",
              );
          }
          onSubmit(body);
        } catch (failure) {
          setError(failure);
        }
      }}
    >
      <fieldset disabled={locked}>
        <legend>记录对这一版成绩的人工核验</legend>
        <p>
          原整包身份：{context.display.project_title} ·{" "}
          {context.display.lot ?? "未声明标段"} · 第 {context.display.round_no}{" "}
          轮 · {context.display.bidder_name}
        </p>
        <Badge>仅关联官方成绩</Badge>
        <p className="small-note">
          核验通过不授予正式研究样本资格，也不产生事前评分或提交许可。
        </p>
        {!positiveAllowed && (
          <div className="notice warning">
            当前不能确认核验：
            {[context.identity_reason, ...context.verification_blockers]
              .filter(Boolean)
              .map((reason) => packageOutcomeReason(reason!))
              .join("；") || "原依据包或身份不可用"}
            。仍可登记待核验、冲突或驳回意见。
          </div>
        )}
        <label>
          核验结论
          <select
            value={state}
            onChange={(event) => {
              setState(event.target.value as typeof state);
              setAcknowledged(false);
            }}
          >
            <option value="pending">待核验</option>
            <option value="verified" disabled={!positiveAllowed}>
              确认已核验
            </option>
            <option value="conflict">存在冲突</option>
            <option value="rejected">驳回此成绩核验</option>
          </select>
        </label>
        <label>
          核验说明
          <textarea
            required
            maxLength={4000}
            rows={3}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="说明工程、标段、轮次、投标主体与此成绩的对应关系"
          />
        </label>
        <label>
          成绩公布时间（含时区）
          <input
            type="text"
            required={state === "verified"}
            value={published}
            maxLength={40}
            placeholder="2026-10-21T12:00:00+08:00"
            onChange={(event) => setPublished(event.target.value)}
          />
        </label>
        <label>
          成绩聚合方式
          <input
            required={state === "verified"}
            value={aggregation}
            maxLength={200}
            onChange={(event) => setAggregation(event.target.value)}
            placeholder="例如：公示的技术总分，未进行推算"
          />
        </label>
        <div className="package-outcome-evidence">
          <h4>这一份官方成绩原件的原页引文</h4>
          <ResourceState
            {...source}
            hasData={!!source.data}
            onRetry={() => void source.reload()}
          />
          {source.data && !validSource && (
            <p role="alert" className="notice error">
              引文响应与成绩来源身份不一致，未提供选择。
            </p>
          )}
          {source.data?.gaps.map((gap, index) => (
            <p className="small-note" key={index}>
              {gap}
            </p>
          ))}
          {validSource &&
            source
              .data!.items.filter((item) => item.kind === "text")
              .map((item) => {
                const selected = refs.some(
                  (ref) => ref.evidence_id === item.id,
                );
                return (
                  <div key={item.id}>
                    <label className="evidence-select-item">
                      <input
                        type="checkbox"
                        checked={selected}
                        disabled={
                          !selected &&
                          (item.source_status !== "published" ||
                            refs.length >= 100)
                        }
                        onChange={(event) => {
                          setAcknowledged(false);
                          setRefs(
                            event.target.checked
                              ? [
                                  ...refs,
                                  {
                                    document_version_id:
                                      item.document_version_id,
                                    evidence_id: item.id,
                                    physical_page: item.physical_page,
                                    quote:
                                      Array.from(item.quote).length <= 4000
                                        ? item.quote
                                        : "",
                                  },
                                ]
                              : refs.filter(
                                  (ref) => ref.evidence_id !== item.id,
                                ),
                          );
                        }}
                      />
                      <span>
                        物理页 {item.physical_page} · {item.quote}
                        {item.source_status !== "published" &&
                          "（来源当前不可用）"}
                      </span>
                    </label>
                    {selected && (
                      <label>
                        物理页 {item.physical_page} 的逐字摘录（最多 4000 字）
                        <textarea
                          required
                          rows={3}
                          maxLength={4000}
                          value={
                            refs.find((ref) => ref.evidence_id === item.id)!
                              .quote
                          }
                          onChange={(event) => {
                            setAcknowledged(false);
                            setRefs(
                              refs.map((ref) =>
                                ref.evidence_id === item.id
                                  ? { ...ref, quote: event.target.value }
                                  : ref,
                              ),
                            );
                          }}
                        />
                        {Array.from(item.quote).length > 4000 && (
                          <span className="small-note">
                            原段超过 4000
                            字。请从上方完整原文选择连续摘录粘贴到这里；系统不会自动截断或改写原文。
                          </span>
                        )}
                      </label>
                    )}
                  </div>
                );
              })}
          {validSource && source.data!.items.length === 0 && (
            <p className="small-empty">
              尚无可核对的成绩原页，请先解析这份官方结果原件。
            </p>
          )}
          <EvidenceLinks ids={refs.map((ref) => ref.evidence_id)} />
        </div>
        {state === "verified" && (
          <label className="checkbox-row">
            <input
              type="checkbox"
              required
              checked={acknowledged}
              onChange={(event) => setAcknowledged(event.target.checked)}
            />
            我已逐项核对原实交身份、原招标依据及所选成绩原页。
          </label>
        )}
        <button type="submit" className="button primary">
          保存这一版核验意见
        </button>
      </fieldset>
      <ErrorNotice error={error} />
    </form>
  );
}
