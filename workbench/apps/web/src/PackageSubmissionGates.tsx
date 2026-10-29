import { useState } from "react";
import type { PackageSubmissionPreview } from "./contracts";
import { Badge } from "./components";

const names: Record<string, string> = {
  ORIGINAL_BYTES_NOT_CHECKED: "当前检查尚未读取原件字节",
  ORIGINAL_BYTES_VERIFICATION_FAILED: "原件字节核验未通过",
  REVIEW_RUNTIME_DEPENDENCIES_NOT_CHECKED: "核查运行依赖尚未完成当前核验",
  CURRENT_METADATA_NOT_OBSERVED: "当前资料状态尚未核对",
  CURRENT_IDENTITY_UNCONFIRMED: "当前投标身份尚未确认",
  PACKAGE_BIDDER_UNCONFIRMED: "包内投标主体尚未确认",
  PACKAGE_IDENTITY_STALE: "包内身份与当前身份不同",
  PACKAGE_REVISION_STALE: "所选包已不是当前修订",
  PACKAGE_INVENTORY_STALE: "需求清单已不是当前清单",
  PACKAGE_RULE_SET_STALE: "关联规则集已变化",
  PACKAGE_MEMBERS_UNPROVEN: "包成员来源尚未完整证明",
  PACKAGE_PARSE_UNPROVEN: "原件解析身份尚未完整证明",
  PACKAGE_GENERATED_OUTPUT_UNPROVEN: "生成原件的入包依据尚未完整证明",
  PACKAGE_SOURCES_CHANGED: "来源状态已经变化",
  PACKAGE_SOURCES_UNPROVEN: "来源身份尚未完整证明",
  PACKAGE_SOURCE_NOT_EFFECTIVE: "存在当前未生效的来源",
  PACKAGE_PHYSICAL_RANGE_GAP: "投标包存在未覆盖的物理页",
  AUTHORITY_DECLARED_PAGE_GAP: "依据包存在未声明的物理页",
  AUTHORITY_PACKAGE_NOT_SELECTED: "未关联确切依据包",
  REQUIREMENT_INVENTORY_NOT_SELECTED: "未关联需求清单",
  REQUIREMENT_INVENTORY_EMPTY: "需求清单为空",
  ACTIVE_CORE_REQUIREMENTS_NOT_ESTABLISHED: "有效核心要求尚未建立",
  INVENTORY_EXTRACTION_INCOMPLETE: "原清单抽取范围不完整",
  INVENTORY_EXTRACTION_PROOF_NOT_OBSERVED: "未取得原抽取证明",
  INVENTORY_EXTRACTION_RECEIPT_UNPROVEN: "原抽取回执尚未匹配",
  INVENTORY_HUMAN_DERIVATION_UNPROVEN: "人工更正来源链尚未证明",
  INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED: "需求清单的语义完整性尚未测量",
  INVENTORY_SOURCE_EVIDENCE_INCOMPLETE: "清单来源证据不完整",
  PACKAGE_REVIEW_NOT_SELECTED: "未关联整包核查",
  PACKAGE_REVIEW_NOT_SUCCEEDED: "所选核查尚未成功结束",
  PACKAGE_REVIEW_OVERALL_COVERAGE_PARTIAL: "核查的整体覆盖仍为部分范围",
  PACKAGE_REVIEW_QUALITY_NOT_MEASURED: "核查质量尚未测量",
  KNOWN_CORE_JUDGMENTS_INCOMPLETE: "已知核心要求仍有未判定项",
  CORE_REQUIREMENT_NEEDS_REVALIDATION: "存在待重新核验的核心要求",
  CORE_REQUIREMENT_SCOPE_UNPROVEN: "核心要求的适用范围尚未证明",
  CORE_REQUIREMENT_SOURCE_UNBOUND: "核心要求缺少绑定来源",
  CORE_RULE_CONFIRMATION_NOT_OBSERVED: "未取得核心条款的当前确认意见",
  CORE_RULE_NOT_CONFIRMED: "核心条款尚未逐项确认",
  HISTORICAL_CORE_JUDGMENTS_UNKNOWN: "历史核心判断仍有未知项",
  HISTORICAL_RUN_RESULT_UNAVAILABLE: "存在无法读取结果的历史核查",
  KNOWN_BLOCKING_RISKS_UNRESOLVED: "已知阻断风险尚无有效复检解决依据",
  RISK_HISTORY_INCOMPLETE: "历史风险未完整读取",
  RISK_HISTORY_NOT_OBSERVED: "尚未取得历史风险观察",
  SELECTED_RUN_MISSING_FROM_HISTORY: "所选运行未匹配到风险历史",
  HUMAN_OPINION_IS_NOT_RECHECK_RESOLUTION: "人工意见不等于有效复检解决",
  PROJECT_WORK_CLOSED: "项目当前已关闭或归档",
  METADATA_OBSERVATION_IS_NOT_ORIGINAL_BYTE_VERIFICATION:
    "资料状态观察不代表原件字节已经核验",
  REGISTRATION_IS_NOT_PLATFORM_SUBMISSION:
    "登记事实不代表向交易平台提交或验真回执",
};
const stateNames = {
  pass: "此项已满足",
  blocked: "存在阻断",
  unknown: "仍有未知",
};
function Codes({ codes }: { codes: string[] }) {
  return codes.length ? (
    <ul className="package-submission-codes">
      {codes.map((code) => (
        <li key={code}>
          {names[code] ?? code}
          <span className="small-note digest">
            {names[code] ? code : "服务返回的检查原因，未推断通过"}
          </span>
        </li>
      ))}
    </ul>
  ) : (
    <p className="small-note">此项没有额外阻断原因；仍需结合其他三项检查。</p>
  );
}
export function PackageSubmissionGates({
  gate,
  historical = false,
}: {
  gate: PackageSubmissionPreview["gate"];
  historical?: boolean;
}) {
  const m = gate.manifest,
    g = m.gates;
  const [risksShown, setRisksShown] = useState(20),
    [decisionsShown, setDecisionsShown] = useState(20);
  return (
    <section
      className="package-submission-gates"
      aria-label={historical ? "登记时四类整包检查" : "四类整包提交检查"}
    >
      <h3>
        {historical ? "登记时保存的四类整包检查" : "2. 核对四类整包提交检查"}
      </h3>
      <p className="notice warning">
        <strong>标准登记仍未获准。</strong>{" "}
        完整性与核查质量尚未证明，单项满足或人工勾选不会授予完整提交资格。
      </p>
      <p className="small-note">
        {historical
          ? "这是登记时冻结的观察，不会用当前状态覆盖。"
          : "这是当前选择的观察，保存时还会重新核对。"}{" "}
        检查时点 {m.checked_at}
      </p>
      <div className="package-submission-gate-grid">
        <article>
          <header>
            <h4>当前输入与来源</h4>
            <Badge tone={g.current_input.state === "pass" ? "" : "warning"}>
              {stateNames[g.current_input.state]}
            </Badge>
          </header>
          <p>
            观察 {g.current_input.member_count} 个原件成员；未覆盖物理页段{" "}
            {g.current_input.physical_page_gaps.length} 处。
          </p>
          <p className="small-note">
            本门原件检查：
            {g.current_input.original_verification === "failed"
              ? "未通过"
              : "尚未执行字节核验"}
            。
          </p>
          <Codes codes={g.current_input.codes} />
          {!!g.current_input.physical_page_gaps.length && (
            <details>
              <summary>查看缺失物理页范围</summary>
              <ul>
                {g.current_input.physical_page_gaps.map((p, i) => (
                  <li key={i}>
                    {p.role === "target" ? "投标包" : "依据包"} · {p.member_id}{" "}
                    · 物理页 {p.first_page}—{p.last_page}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </article>
        <article>
          <header>
            <h4>已知核心要求覆盖</h4>
            <Badge tone={g.core_coverage.state === "pass" ? "" : "warning"}>
              {stateNames[g.core_coverage.state]}
            </Badge>
          </header>
          <dl className="package-submission-counts">
            <dt>有效核心要求</dt>
            <dd>{g.core_coverage.active_core_count}</dd>
            <dt>已有判断</dt>
            <dd>{g.core_coverage.judged_core_count}</dd>
            <dt>未知判断</dt>
            <dd>{g.core_coverage.unknown_core_count}</dd>
            <dt>不利判断</dt>
            <dd>{g.core_coverage.unfavorable_core_count}</dd>
          </dl>
          <p className="small-note">
            整体覆盖：
            {g.core_coverage.overall_coverage === "partial"
              ? "部分范围"
              : "未知"}
            。
            {g.core_coverage.extraction_range_proven
              ? "抽取输入范围已有证明，"
              : "抽取输入范围仍待证明，"}
            不代表清单语义完整；质量尚未测量。
          </p>
          <Codes codes={g.core_coverage.codes} />
        </article>
        <article>
          <header>
            <h4>核心条款逐项确认</h4>
            <Badge
              tone={g.mandatory_confirmation.state === "pass" ? "" : "warning"}
            >
              {stateNames[g.mandatory_confirmation.state]}
            </Badge>
          </header>
          <p>
            已确认 {g.mandatory_confirmation.confirmed_count} /{" "}
            {g.mandatory_confirmation.core_rule_count} 项；待确认{" "}
            {g.mandatory_confirmation.pending_rule_ids.length} 项，待重核{" "}
            {g.mandatory_confirmation.needs_revalidation_rule_ids.length} 项。
          </p>
          <Codes codes={g.mandatory_confirmation.codes} />
          {!!g.mandatory_confirmation.decisions.length && (
            <details>
              <summary>查看当时条款意见</summary>
              <ul>
                {g.mandatory_confirmation.decisions
                  .slice(0, decisionsShown)
                  .map((d) => (
                    <li key={d.rule_id}>
                      <span className="digest">条款 {d.rule_id}</span> ·{" "}
                      {d.decision ?? "尚无意见"}
                      {d.decision_id && (
                        <span className="small-note digest">
                          意见 {d.decision_id}
                        </span>
                      )}
                    </li>
                  ))}
              </ul>
              {decisionsShown < g.mandatory_confirmation.decisions.length && (
                <button
                  type="button"
                  className="text-button"
                  onClick={() => setDecisionsShown((n) => n + 20)}
                >
                  加载更多条款意见
                </button>
              )}
            </details>
          )}
        </article>
        <article>
          <header>
            <h4>全项目已知阻断风险</h4>
            <Badge
              tone={g.known_blocking_risks.state === "pass" ? "" : "warning"}
            >
              {stateNames[g.known_blocking_risks.state]}
            </Badge>
          </header>
          <p>
            已知阻断 {g.known_blocking_risks.blocked_count} 项；未知{" "}
            {g.known_blocking_risks.unknown_count} 项。
          </p>
          <p className="small-note">
            读取 {g.known_blocking_risks.runs_read} 次历史核查、
            {g.known_blocking_risks.result_rows_read} 条结果；
            {g.known_blocking_risks.history_complete
              ? "此观察范围的历史已读取"
              : "历史仍不完整"}
            。人工驳回不自动消除风险。
          </p>
          <Codes codes={g.known_blocking_risks.codes} />
        </article>
      </div>
      {!!g.known_blocking_risks.risks.length && (
        <details className="package-submission-risk-list">
          <summary>
            查看 {g.known_blocking_risks.risks.length} 项保留的历史风险
          </summary>
          {g.known_blocking_risks.risks
            .slice(0, risksShown)
            .map((risk, index) => (
              <article key={index}>
                <p>
                  <strong>
                    {risk.kind === "package_core_requirement"
                      ? risk.statement
                      : risk.finding.statement}
                  </strong>
                </p>
                {risk.kind === "package_core_requirement" ? (
                  <>
                    <p>
                      整包核心判断：{risk.verdict} ·{" "}
                      {risk.state === "blocked" ? "存在阻断" : "未知"}
                    </p>
                    <p className="digest">
                      核查 {risk.run_id} · 条款 {risk.requirement_id}
                    </p>
                    {risk.human_decision && (
                      <p>
                        保留人工意见：{risk.human_decision.state}；
                        {risk.human_decision.reason}
                      </p>
                    )}
                  </>
                ) : (
                  <>
                    <p>
                      单稿历史问题：{risk.finding.verdict} ·{" "}
                      {risk.finding.lifecycle}
                    </p>
                    <p className="digest">
                      原问题 {risk.finding.origin_id} · 评审{" "}
                      {risk.finding.review_id}
                    </p>
                  </>
                )}
                <p className="small-note">
                  尚无可验证的复检解决依据，不按人工意见归零。
                </p>
              </article>
            ))}
          {risksShown < g.known_blocking_risks.risks.length && (
            <button
              type="button"
              className="text-button"
              onClick={() => setRisksShown((n) => n + 20)}
            >
              加载更多历史风险
            </button>
          )}
        </details>
      )}
      <details>
        <summary>检查边界与固定摘要</summary>
        <Codes codes={m.limitations} />
        <p className="digest">观察摘要 {gate.digest}</p>
        <p className="digest">规则方法 {m.policy_digest}</p>
      </details>
    </section>
  );
}
