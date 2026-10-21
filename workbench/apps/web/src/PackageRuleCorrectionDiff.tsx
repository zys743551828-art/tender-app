import type { PackageRuleCorrectionPreviewView } from "./contracts";
import { PackageRuleCorrectionSource } from "./PackageRuleCorrectionEvidence";
import {
  correctionKindNames,
  correctionOperationNames,
  type CorrectionSemantic,
} from "./packageRuleCorrectionProtocol";
import type {
  CorrectionBase,
  CorrectionScope,
} from "./packageRuleCorrectionRecovery";

const limitationNames: Record<string, string> = {
  INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED:
    "清单是否涵盖全部业务义务尚未测量。",
  HUMAN_INTERPRETATION_NOT_AUTHORITY_AMENDMENT:
    "本次是人工解释修订，不是招标方发布的新补遗。",
  ORIGINAL_BYTES_NOT_VERIFIED_BY_PREVIEW:
    "预览未执行原件字节核验，确认保存时将重新核验。",
  ROOT_EXTRACTION_PARTIAL: "原抽取仍有解析缺口，本次修订保留该状态。",
  ROOT_EXTRACTION_CONFLICT: "原抽取仍有冲突，本次修订不消除该状态。",
};

export function RuleSemanticDetails({
  value,
  label,
}: {
  value: CorrectionSemantic | null;
  label: string;
}) {
  return (
    <section className="rule-correction-semantic" aria-label={label}>
      <h6>{label}</h6>
      {value ? (
        <>
          <p className="small-note">
            {correctionKindNames[value.kind]} ·{" "}
            {value.provenance_status === "effective"
              ? "有效条款"
              : value.provenance_status === "superseded"
                ? "已撤销，保留历史"
                : "来源待重新核验"}
          </p>
          <p className="rule-correction-statement">{value.statement}</p>
          <dl>
            <dt>适用范围</dt>
            <dd>
              {typeof value.applicability_scope.description === "string"
                ? value.applicability_scope.description
                : Object.keys(value.applicability_scope).length
                  ? JSON.stringify(value.applicability_scope)
                  : "未结构化声明，请核对原条款与原页"}
            </dd>
            <dt>满分</dt>
            <dd>{value.max_points ?? "未声明分值"}</dd>
          </dl>
          <strong>条件</strong>
          {value.conditions.length ? (
            <ul>
              {value.conditions.map((text, index) => (
                <li key={index}>{text}</li>
              ))}
            </ul>
          ) : (
            <p className="small-note">未列条件</p>
          )}
          <strong>例外</strong>
          {value.exceptions.length ? (
            <ul>
              {value.exceptions.map((text, index) => (
                <li key={index}>{text}</li>
              ))}
            </ul>
          ) : (
            <p className="small-note">未列例外</p>
          )}
          {value.bands.length > 0 && (
            <div className="rule-correction-table-wrap">
              <table>
                <caption>完整评分分档</caption>
                <thead>
                  <tr>
                    <th scope="col">档次</th>
                    <th scope="col">要求</th>
                    <th scope="col">分值</th>
                  </tr>
                </thead>
                <tbody>
                  {value.bands.map((band, index) => (
                    <tr key={index}>
                      <th scope="row">{band.label}</th>
                      <td>{band.description}</td>
                      <td>{band.points}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <details>
            <summary>条款来源与范围身份</summary>
            <p>依据：{value.evidence_ids.join("；")}</p>
            <pre>{JSON.stringify(value.applicability_scope, null, 2)}</pre>
            {value.bands.map((band, index) => (
              <p key={index}>
                {band.label} 分档依据：{band.evidence_ids.join("；")}
              </p>
            ))}
          </details>
        </>
      ) : (
        <p className="small-note">本次新增条款，没有被替换的旧条款。</p>
      )}
    </section>
  );
}

export function PackageRuleCorrectionDiff({
  scope,
  base,
  preview,
}: {
  scope: CorrectionScope;
  base: CorrectionBase;
  preview: PackageRuleCorrectionPreviewView;
}) {
  const m = preview.manifest;
  return (
    <section className="rule-correction-preview" aria-label="规则修订结果预览">
      <h4>核对修订前后</h4>
      <p>
        预览尚未写入清单。补充和替换会形成新的人工确认；撤销会保留原文与真实否决记录。
      </p>
      <dl className="rule-correction-counts">
        <div>
          <dt>原清单</dt>
          <dd>{m.counts.before} 条</dd>
        </div>
        <div>
          <dt>补充</dt>
          <dd>{m.counts.added} 条</dd>
        </div>
        <div>
          <dt>替换</dt>
          <dd>{m.counts.replaced} 条</dd>
        </div>
        <div>
          <dt>撤销</dt>
          <dd>{m.counts.withdrawn} 条</dd>
        </div>
        <div>
          <dt>修订后有效</dt>
          <dd>{m.counts.active_after} 条</dd>
        </div>
      </dl>
      <p className="notice neutral">
        未改动的 {m.counts.carried}{" "}
        条按原身份承接。补充、替换的检查计划需要重新声明；已有覆盖记录不会成为新清单的检查结果。
      </p>
      {m.changes.map((change, index) => (
        <article className="rule-correction-change" key={index}>
          <h5>
            修订 {index + 1} · {correctionOperationNames[change.op]}
          </h5>
          <div className="rule-correction-comparison">
            <RuleSemanticDetails value={change.before} label="修订前" />
            <RuleSemanticDetails value={change.after} label="修订后" />
          </div>
          <h6>本次采用的冻结原页依据</h6>
          {change.quotes.map((quote, quoteIndex) => (
            <PackageRuleCorrectionSource
              key={`${quote.evidence_id}:${quoteIndex}`}
              scope={scope}
              base={base}
              quote={quote}
            />
          ))}
        </article>
      ))}
      <div className="notice neutral">
        <strong>保留原抽取范围与质量边界</strong>
        <p>
          原抽取范围：
          {m.extraction_basis.extraction_coverage === "complete"
            ? "全部提交范围已解析"
            : m.extraction_basis.extraction_coverage === "partial"
              ? "解析仍有缺口"
              : "抽取存在冲突"}
          ；质量尚未测量。人工补充条数不会证明整包完整，也不会自动取得正式审查或提交资格。
        </p>
      </div>
      {m.limitations.length > 0 && (
        <details>
          <summary>本次预览保留的限制（{m.limitations.length} 项）</summary>
          <ul>
            {m.limitations.map((item) => (
              <li key={item}>{limitationNames[item] ?? item}</li>
            ))}
          </ul>
        </details>
      )}
      <details>
        <summary>预览的清单与摘要</summary>
        <p>基线清单：{m.scope.inventory_id}</p>
        <p>预览摘要：{preview.digest}</p>
        <p>招标／补遗修订：{m.authority.revision_id}</p>
        <p>原件字节将在确认保存时再次核验。</p>
      </details>
    </section>
  );
}
