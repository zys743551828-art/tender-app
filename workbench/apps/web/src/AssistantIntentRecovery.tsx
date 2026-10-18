import { useEffect, useState } from "react";
import type {
  AssistantJob,
  AssistantTurnRequest,
  Bid,
  FindingPage,
  RuleSetView,
} from "./contracts";
import type { SelectedAssistantSource } from "./assistantState";
import { useResource } from "./useResource";
import { ResourceState } from "./ResourceState";

export type AssistantRecoveryIntent =
  | { request_mode: "continue"; related_job_id: string }
  | {
      request_mode: "new_question";
      target: NonNullable<AssistantTurnRequest["target"]>;
      intent_purpose: NonNullable<AssistantTurnRequest["intent_purpose"]>;
    };
export type AssistantRecoverySelection = {
  active: boolean;
  intent: AssistantRecoveryIntent | null;
};

const purposes = {
  project: { value: "project_reference", label: "项目参考解释" },
  rule: { value: "rule_explanation", label: "要求条款解释" },
  finding: { value: "finding_explanation", label: "评审问题解释" },
  section: { value: "section_reference", label: "已保存章节参考" },
} as const;
type Kind = keyof typeof purposes;

export function AssistantIntentRecovery({
  bidId,
  jobs,
  sources,
  disabled,
  onInteract,
  onChange,
}: {
  bidId: string | null;
  jobs: AssistantJob[];
  sources: SelectedAssistantSource[];
  disabled: boolean;
  onInteract: () => void;
  onChange: (value: AssistantRecoverySelection) => void;
}) {
  const [mode, setMode] = useState<"" | "continue" | "new_question">("");
  const [originalId, setOriginalId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [kind, setKind] = useState<Kind | "">("");
  const [objectId, setObjectId] = useState("");
  const ownProject = useResource<Bid>(bidId ? `/bids/${bidId}` : null);
  const projectSources = sources.filter(
    (source) =>
      source.reference.kind === "project" &&
      source.bidId === source.reference.id,
  );
  const projectAllowed =
    !!projectId &&
    (bidId
      ? projectId === bidId
      : projectSources.some((s) => s.reference.id === projectId));
  const project = useResource<Bid>(
    mode === "new_question" && projectAllowed ? `/bids/${projectId}` : null,
  );
  const current =
    project.data?.id === projectId && !project.loading && !project.error
      ? project.data
      : null;
  const rules = useResource<RuleSetView>(
    current && kind === "rule" ? `/bids/${projectId}/rules` : null,
  );
  const findings = useResource<FindingPage>(
    current?.current_review_id && kind === "finding"
      ? `/reviews/${current.current_review_id}/findings?limit=50`
      : null,
  );
  const options =
    kind === "rule"
      ? rules.data?.bid_id === projectId && !rules.error && !rules.loading
        ? rules.data.rules
            .filter((rule) => rule.scope.bid_id === projectId)
            .map((rule) => ({ id: rule.id, title: rule.statement }))
        : []
      : kind === "finding"
        ? findings.data && !findings.error && !findings.loading
          ? findings.data.items
              .filter(
                (finding) => finding.review_id === current?.current_review_id,
              )
              .map((finding) => ({ id: finding.id, title: finding.statement }))
          : []
        : kind === "section"
          ? sources
              .filter(
                (s) => s.reference.kind === "section" && s.bidId === projectId,
              )
              .map((s) => ({ id: s.reference.id, title: s.title }))
          : [];
  let intent: AssistantRecoveryIntent | null = null;
  if (mode === "continue" && jobs.some((job) => job.id === originalId)) {
    intent = { request_mode: "continue", related_job_id: originalId };
  } else if (
    mode === "new_question" &&
    current &&
    projectAllowed &&
    kind &&
    (kind === "project" || options.some((option) => option.id === objectId))
  ) {
    intent = {
      request_mode: "new_question",
      target: { kind, id: kind === "project" ? projectId : objectId },
      intent_purpose: purposes[kind].value,
    };
  }
  const serialized = JSON.stringify({ active: mode !== "", intent });
  useEffect(() => {
    onChange(JSON.parse(serialized) as AssistantRecoverySelection);
  }, [serialized, onChange]);

  function editing() {
    onInteract();
    onChange({ active: true, intent: null });
  }
  return (
    <details
      className="coverage-details"
      open={jobs.length > 0 ? true : undefined}
    >
      <summary>
        {jobs.length
          ? "费用待核对：关联原任务或明确新问题"
          : "明确新问题的业务对象与用途"}
      </summary>
      {jobs.length > 0 && (
        <p className="notice warning">
          原调用及未知费用仍保留，不能普通重发。关联原任务只回读既有处理；新对象是否独立仍由服务端核验。
        </p>
      )}
      <fieldset disabled={disabled}>
        <label>
          本次请求方式
          <select
            aria-label="本次请求方式"
            value={mode}
            onChange={(event) => {
              editing();
              setMode(event.target.value as typeof mode);
              setOriginalId("");
              setProjectId("");
              setKind("");
              setObjectId("");
            }}
          >
            <option value="">先明确本次处理方式</option>
            {jobs.length > 0 && (
              <option value="continue">关联原任务，查看既有状态</option>
            )}
            <option value="new_question">明确新的业务对象与用途</option>
          </select>
        </label>
        {mode === "continue" && (
          <>
            <label>
              原待核对任务
              <select
                aria-label="原待核对任务"
                value={originalId}
                onChange={(event) => {
                  editing();
                  setOriginalId(event.target.value);
                }}
              >
                <option value="">请选择原任务</option>
                {jobs.map((job, index) => (
                  <option key={job.id} value={job.id}>
                    {job.logical_intent?.normalized_question.slice(0, 80) ||
                      `待核对处理 ${index + 1}`}
                  </option>
                ))}
              </select>
            </label>
            <p className="small-note">
              此操作只引用原任务，不创建新任务，不自动重发模型请求，也不核清费用。下方草稿保留。
            </p>
          </>
        )}
        {mode === "new_question" && (
          <>
            {!bidId && projectSources.length === 0 && (
              <p className="small-note">
                先用“选择可信来源”明确选择目标项目的结构化记忆；仅选原件或章节不能代替项目身份。
              </p>
            )}
            <label>
              新问题所属项目
              <select
                aria-label="新问题所属项目"
                value={projectId}
                onChange={(event) => {
                  editing();
                  setProjectId(event.target.value);
                  setKind("");
                  setObjectId("");
                }}
              >
                <option value="">请选择实际项目</option>
                {bidId
                  ? ownProject.data?.id === bidId &&
                    !ownProject.error && (
                      <option value={bidId}>{ownProject.data.title}</option>
                    )
                  : projectSources.map((s) => (
                      <option key={s.reference.id} value={s.reference.id}>
                        {s.title}
                      </option>
                    ))}
              </select>
            </label>
            {bidId && (
              <>
                <ResourceState
                  {...ownProject}
                  hasData={!!ownProject.data}
                  onRetry={() => void ownProject.reload()}
                />
                <p className="small-note">
                  本会话只接受本项目对象。其他工程可
                  <a href="/assistant">前往全局助手明确选择</a>
                  ，草稿不会自动跨项目发送。
                </p>
              </>
            )}
            <ResourceState
              {...project}
              hasData={!!current}
              onRetry={() => void project.reload()}
            />
            {current?.identity && (
              <p className="small-note">
                登记关联：{current.identity.engineering_title} ·{" "}
                {current.identity.lot ?? "未登记标段"} · 第
                {current.identity.round_no}轮 · {current.identity.bidder_name}
                。原页编号与独立性仍由服务端核验。
              </p>
            )}
            <label>
              新问题作用对象
              <select
                aria-label="新问题作用对象"
                value={kind}
                disabled={!current}
                onChange={(event) => {
                  editing();
                  setKind(event.target.value as Kind | "");
                  setObjectId("");
                }}
              >
                <option value="">请选择对象类型</option>
                <option value="project">该项目</option>
                <option value="rule">真实要求条款</option>
                <option value="finding">实际评审问题</option>
                <option value="section">已选的保存章节</option>
              </select>
            </label>
            {kind && kind !== "project" && (
              <>
                {kind === "rule" && (
                  <ResourceState
                    {...rules}
                    hasData={!!rules.data}
                    onRetry={() => void rules.reload()}
                  />
                )}
                {kind === "finding" && (
                  <ResourceState
                    {...findings}
                    hasData={!!findings.data}
                    onRetry={() => void findings.reload()}
                  />
                )}
                <label>
                  具体业务对象
                  <select
                    aria-label="具体业务对象"
                    value={objectId}
                    onChange={(event) => {
                      editing();
                      setObjectId(event.target.value);
                    }}
                  >
                    <option value="">请选择实际对象</option>
                    {options.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.title}
                      </option>
                    ))}
                  </select>
                </label>
                {kind === "section" && (
                  <p className="small-note">
                    仅列本次已选的可信保存章节，请先从可信来源选择。
                  </p>
                )}
                {kind === "finding" && !current?.current_review_id && (
                  <p className="small-note">
                    该项目没有当前评审，未提供问题对象。
                  </p>
                )}
                {kind === "finding" && findings.data?.has_more && (
                  <p className="small-note">
                    仅列当前返回的前50项；其他问题请先到评审工作面核对。
                  </p>
                )}
              </>
            )}
            {kind && (
              <p>
                本次用途：{purposes[kind].label}
                。不在此生成章节稿或执行正式决定。
              </p>
            )}
            <p className="small-note">
              选择对象只是提交核验，不能证明独立。相同业务身份的新项目壳、换措辞、来源或模型配置均不能绕过原待核清请求；原未知费用继续占用预算。
            </p>
          </>
        )}
      </fieldset>
    </details>
  );
}
