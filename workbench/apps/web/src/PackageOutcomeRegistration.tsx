import { useState } from "react";
import type {
  OutcomeRequest,
  PackageOutcomeContext,
  PackageSubmissionView,
  ResearchOutcomeDetail,
} from "./contracts";
import { ErrorNotice } from "./components";
import { makeOutcomeRequest } from "./packageOutcomeProtocol";

export function PackageOutcomeRegistration({
  submission,
  context,
  base,
  locked,
  onSubmit,
}: {
  submission: PackageSubmissionView;
  context: PackageOutcomeContext;
  base: ResearchOutcomeDetail | null;
  locked: boolean;
  onSubmit: (body: OutcomeRequest) => void;
}) {
  const [scoreKind, setScoreKind] = useState<OutcomeRequest["score_kind"]>(
      base?.score_kind ?? "technical_total",
    ),
    [value, setValue] = useState(base?.value ?? ""),
    [maximum, setMaximum] = useState(base?.maximum ?? ""),
    [sourceId, setSourceId] = useState(base?.source_version_id ?? ""),
    [known, setKnown] = useState(base?.known_at ?? ""),
    [error, setError] = useState<unknown>(null);
  return (
    <form
      className="decision-form package-outcome-form"
      aria-label={base ? "更正整包官方成绩" : "登记整包官方成绩"}
      onSubmit={(event) => {
        event.preventDefault();
        if (locked) return;
        setError(null);
        try {
          onSubmit(
            makeOutcomeRequest(submission, {
              scoreKind,
              value,
              maximum,
              sourceId,
              known,
            }),
          );
        } catch (failure) {
          setError(failure);
        }
      }}
    >
      <fieldset disabled={locked}>
        <legend>
          {base ? "追加更正成绩，原记录保留" : "登记官方成绩原件与数值"}
        </legend>
        <label>
          成绩口径
          <select
            value={scoreKind}
            onChange={(event) =>
              setScoreKind(event.target.value as typeof scoreKind)
            }
          >
            <option value="technical_total">技术总分</option>
            <option value="comprehensive_total">综合总分</option>
            <option value="unknown">成绩口径未知</option>
          </select>
        </label>
        <div className="package-outcome-pair">
          <label>
            得分
            <input
              inputMode="decimal"
              value={value}
              maxLength={100}
              disabled={scoreKind === "unknown"}
              placeholder="未知请留空；零分填 0"
              onChange={(event) => setValue(event.target.value)}
            />
          </label>
          <label>
            满分
            <input
              inputMode="decimal"
              value={maximum}
              maxLength={100}
              disabled={scoreKind === "unknown"}
              placeholder="例如 100"
              onChange={(event) => setMaximum(event.target.value)}
            />
          </label>
        </div>
        <p className="small-note">
          分数按原件的十进制数值保存。综合总分不会作为技术评分误差的标签；未知不会补为零。
        </p>
        <label>
          官方成绩来源原件
          <select
            required
            value={sourceId}
            onChange={(event) => setSourceId(event.target.value)}
          >
            <option value="">请选择已上传并标为官方结果的原件</option>
            {context.source_candidates.map((source) => (
              <option key={source.id} value={source.id}>
                {source.original_name} · {source.id.slice(0, 8)}
              </option>
            ))}
            {sourceId &&
              !context.source_candidates.some(
                (source) => source.id === sourceId,
              ) && (
                <option value={sourceId}>
                  原记录来源（当前目录未列出，请核对）
                </option>
              )}
          </select>
        </label>
        {!context.source_candidates.length && (
          <p className="notice neutral">
            请先在资料中上传官方结果原件并声明用途，再重新读取此处。未上传的成绩可继续保留在输入框。
          </p>
        )}
        <label>
          成绩取得时间（含时区）
          <input
            required
            type="text"
            value={known}
            maxLength={40}
            placeholder="2026-10-21T14:30:00+08:00"
            onChange={(event) => setKnown(event.target.value)}
          />
        </label>
        <p className="small-note">
          请填写实际取得时间。实际提交时间：{submission.submitted_at}。
        </p>
        <button type="submit" className="button primary">
          {base ? "保存成绩更正" : "保存成绩登记"}
        </button>
      </fieldset>
      <ErrorNotice error={error} />
    </form>
  );
}
