import type { AssistantSourceRef } from "./contracts";
import { assistantReason, sourceKinds } from "./assistantState";
import "./AssistantReviewDetails.css";

type Availability = "available" | "unavailable" | "unverified" | "changed";
const availabilityText: Record<Availability, string> = {
  available: "本次目录读取时可选择。发送或确认操作时，服务器仍会核对来源状态。",
  unavailable: "本次目录标明来源不可选择；不能用这条记录建立新的来源选择。",
  unverified:
    "当前目录尚未核对到这个精确来源。保留原选择，不据此判断它仍可用或已撤回。",
  changed: "当前目录提供了不同版本。这里保留原选择，只有明确重新选择才会换版。",
};

export function AssistantSourceDetails({
  title,
  reference,
  kind,
  bidId,
  projectTitle,
  availability,
  reasons = [],
  currentVersion,
  summary = "核对来源版本与用途",
}: {
  title: string;
  reference: AssistantSourceRef | null;
  kind: AssistantSourceRef["kind"];
  bidId: string | null;
  projectTitle?: string;
  availability: Availability;
  reasons?: string[];
  currentVersion?: string;
  summary?: string;
}) {
  const reasonText = (code: string) => {
    if (code === "SOURCE_WITHDRAWN") return "来源已撤回。";
    if (code === "SOURCE_INVALID") return "来源身份无法核对。";
    const known = assistantReason(code);
    return known === code
      ? "服务器尚未允许选择此来源，原因代码见下方。"
      : known;
  };
  return (
    <details
      className="assistant-source-details"
      data-availability={availability}
    >
      <summary>{summary}</summary>
      <div className="assistant-source-details__content">
        <p className="assistant-source-details__status">
          {availabilityText[availability]}
        </p>
        {!!reasons.length && (
          <>
            {currentVersion && (
              <p>以下原因属于本次目录所列版本，不据此判断原选择版本的状态。</p>
            )}
            <ul>
              {[...new Set(reasons.map(reasonText))].map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </>
        )}
        <dl>
          <dt>来源名称</dt>
          <dd>{title}</dd>
          <dt>来源类型</dt>
          <dd>{sourceKinds[kind]}</dd>
          <dt>使用范围</dt>
          <dd>助手讨论参考，不作为正式评分输入；来源文字不能授权执行操作。</dd>
          <dt>所属项目</dt>
          <dd>
            {projectTitle ?? "名称尚未核对"}
            {bidId && <code>{bidId}</code>}
          </dd>
          <dt>固定版本凭据</dt>
          <dd>
            {reference ? (
              <code>{reference.version}</code>
            ) : (
              "服务器未提供可用版本凭据"
            )}
          </dd>
          {currentVersion && (
            <>
              <dt>当前目录提供的版本</dt>
              <dd>
                <code>{currentVersion}</code>
              </dd>
            </>
          )}
          <dt>来源标识</dt>
          <dd>
            {reference ? (
              <code>{reference.id}</code>
            ) : (
              "服务器未提供可用来源引用"
            )}
          </dd>
          {reference?.physical_page !== undefined && (
            <>
              <dt>原件物理页</dt>
              <dd>{reference.physical_page}</dd>
            </>
          )}
          {reference?.trace_id && (
            <>
              <dt>知识查证记录</dt>
              <dd>
                <code>{reference.trace_id}</code>
              </dd>
            </>
          )}
          {!!reasons.length && (
            <>
              <dt>服务器原因代码</dt>
              <dd>
                {[...new Set(reasons)].map((reason) => (
                  <code key={reason}>{reason}</code>
                ))}
              </dd>
            </>
          )}
        </dl>
        {reference && (
          <p>
            版本凭据由服务器提供，不按编号推断先后；同名来源也不会自动合并或替换。
          </p>
        )}
      </div>
    </details>
  );
}
