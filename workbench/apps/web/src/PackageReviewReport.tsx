import { useState } from "react";
import type { ReactNode } from "react";
import type { PackageReviewRunView } from "./contracts";
import { ErrorNotice } from "./components";
import { packageReviewVerdicts } from "./packageReviewProtocol";
import type { PackageReviewRow } from "./packageReviewProtocol";
import PackageReviewEvidence from "./PackageReviewEvidence";

const verdicts = {
  satisfied: "已满足",
  violated: "发现不符",
  not_found: "未找到",
  unable_to_judge: "无法判定",
  not_applicable: "不适用",
};
const kinds = {
  disqualification: "否决要求",
  mandatory: "强制要求",
  scoring: "评分要求",
  advisory: "建议要求",
};
const limitations: Record<string, string> = {
  INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED:
    "尚未证明要求清单涵盖全部招标语义，仍须人工核对遗漏。",
  REQUIREMENT_APPLICABILITY_UNKNOWN: "尚未确认此要求是否适用于本次投标。",
  REQUIREMENT_TARGET_SCOPE_UNDECLARED: "此要求的待核查册页范围尚未声明。",
  FORMAL_SCORING_NOT_AVAILABLE:
    "当前核查不提供正式评分，此项不能据此判定得分。",
  REQUIREMENT_CHECK_UNSUPPORTED: "此要求包含当前核查尚未支持的检查条件。",
  REQUIREMENT_EFFECTIVITY_UNPROVEN: "此要求的生效条件尚未证明。",
  REQUIREMENT_VALIDITY_TIME_UNDECLARED: "此要求的适用时间尚未声明。",
  REQUIREMENT_MINIMUM_COUNT_UNKNOWN: "此要求的最低数量尚未确认。",
};
const limitationText = (code: string) =>
  limitations[code] ?? `仍待核验的限制：${code}`;
type Verdict = PackageReviewRow["verdict"];
export default function PackageReviewReport({
  run,
  renderDecision,
  focusRequirementId,
}: {
  run: PackageReviewRunView;
  renderDecision?: (row: PackageReviewRow) => ReactNode;
  focusRequirementId?: string;
}) {
  const [filter, setFilter] = useState<Verdict | "all">("all"),
    [page, setPage] = useState(0),
    [search, setSearch] = useState(focusRequirementId ?? "");
  const [error, setError] = useState<unknown>(null);
  const result = run.result;
  if (!result) return null;
  const m = result.manifest,
    query = search.trim().toLocaleLowerCase(),
    rows = m.matrix.filter(
      (row) =>
        (filter === "all" || row.verdict === filter) &&
        (!query ||
          row.requirement_id.includes(query) ||
          row.requirement_statement.toLocaleLowerCase().includes(query)),
    );
  const start = page * 20,
    visible = rows.slice(start, start + 20);
  function download() {
    try {
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(run, null, 2)], {
          type: "application/json;charset=utf-8",
        }),
      );
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `package-scope-review-${run.id}.json`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
      setError(null);
    } catch (failure) {
      setError(failure);
    }
  }
  return (
    <section className="package-review__report" aria-label="整包范围核查结果">
      <div className="package-review__heading">
        <div>
          <h4>范围核查结果</h4>
          <p>
            {m.requirement_count} 条要求 ·{" "}
            {m.matrix_coverage === "complete"
              ? "逐条判定矩阵已完成"
              : "逐条判定仍有缺口"}
          </p>
        </div>
        <button type="button" className="button secondary" onClick={download}>
          导出范围核查 JSON
        </button>
      </div>
      <div className="package-review__notice">
        <strong>当前结论仅覆盖已声明范围</strong>
        <p>
          整体覆盖仍为部分。要求清单完整性与真实效果尚未测定，原始逐条结论保留，人工复核记录另列，不形成整包通过、正式评分或投递资格。
        </p>
      </div>
      <dl className="package-review__counts">
        {packageReviewVerdicts.map((verdict) => (
          <div key={verdict} data-verdict={verdict}>
            <dt>{verdicts[verdict]}</dt>
            <dd>{m.counts[verdict]}</dd>
          </div>
        ))}
      </dl>
      <details className="package-review__limitations" open>
        <summary>本次仍需处理的范围限制</summary>
        <ul>
          {m.limitations.map((code) => (
            <li key={code}>{limitationText(code)}</li>
          ))}
        </ul>
      </details>
      <details>
        <summary>
          本次实际输入的资料范围（{m.submitted_documents.length} 份）
        </summary>
        <ul className="package-review__documents">
          {m.submitted_documents.map((doc) => (
            <li key={`${doc.package_role}:${doc.member_id}`}>
              <strong>
                {doc.package_role === "target" ? "投标资料" : "招标依据"} ·{" "}
                {doc.member_id}
              </strong>
              <p>
                {doc.page_count} 个物理页 · {doc.evidence_count} 个证据块
              </p>
              <ul>
                {doc.parts.map((part) => (
                  <li key={part.part_id}>
                    {part.category} · 物理页 {part.first_page}–{part.last_page}
                    {part.shared_attachment ? " · 共享附件" : ""}
                  </li>
                ))}
              </ul>
              <details>
                <summary>文件与解析身份</summary>
                <p>
                  文件版本：<code>{doc.document_version_id}</code>
                </p>
                <p>
                  解析编号：<code>{doc.parse_run_id}</code>
                </p>
                <p>
                  原件摘要：<code>{doc.file_digest}</code>
                </p>
              </details>
            </li>
          ))}
        </ul>
      </details>
      <div className="package-review__matrix-heading">
        <h5>逐条要求与引用</h5>
        <label>
          查找要求编号或内容
          <input
            value={search}
            maxLength={1000}
            placeholder="输入要求编号或原要求中的文字"
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(0);
            }}
          />
        </label>
        <label>
          筛选核查结论
          <select
            value={filter}
            onChange={(event) => {
              setFilter(event.target.value as Verdict | "all");
              setPage(0);
            }}
          >
            <option value="all">全部（{m.requirement_count}）</option>
            {packageReviewVerdicts.map((verdict) => (
              <option key={verdict} value={verdict}>
                {verdicts[verdict]}（{m.counts[verdict]}）
              </option>
            ))}
          </select>
        </label>
      </div>
      {search && (
        <div className="package-review__actions">
          <p className="muted">
            正在定位符合检索条件的原要求；导出 JSON 和报告仍包含本轮全部要求。
          </p>
          <button
            type="button"
            className="text-button"
            onClick={() => {
              setSearch("");
              setPage(0);
            }}
          >
            清除要求检索
          </button>
        </div>
      )}
      {!rows.length && (
        <p className="package-review__empty">
          本次结果中没有符合当前筛选与检索的要求；其他类别与范围限制仍需核对。
        </p>
      )}
      {visible.map((row) => (
        <article
          className="package-review__row"
          key={row.requirement_id}
          aria-label={`要求：${row.requirement_statement}`}
        >
          <div className="package-review__row-heading">
            <span
              className="package-review__verdict"
              data-verdict={row.verdict}
            >
              {verdicts[row.verdict]}
            </span>
            <span className="muted">{kinds[row.rule_kind]} · 机器原结论</span>
          </div>
          <h5>{row.requirement_statement}</h5>
          <p>{row.statement}</p>
          {row.limitations.length > 0 && (
            <ul className="package-review__row-limitations">
              {row.limitations.map((code) => (
                <li key={code}>{limitationText(code)}</li>
              ))}
            </ul>
          )}
          <details>
            <summary>
              已检查的册页范围（{row.inspected_ranges.length} 段）
            </summary>
            {row.inspected_ranges.length ? (
              <ul>
                {row.inspected_ranges.map((range) => (
                  <li key={`${range.member_id}:${range.part_id}`}>
                    <span>
                      {range.member_id} · {range.category} · 物理页{" "}
                      {range.first_page}–{range.last_page}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p>本条尚无已声明并核对的投标资料范围。</p>
            )}
          </details>
          {(["authority", "target"] as const).map((role) => {
            const quotes =
              role === "target" ? row.target_quotes : row.authority_quotes;
            return (
              quotes.length > 0 && (
                <section
                  className="package-review__quotes"
                  key={role}
                  aria-label={
                    role === "target" ? "投标原文引用" : "招标依据引用"
                  }
                >
                  <h6>{role === "target" ? "投标原文" : "招标依据"}</h6>
                  {quotes.map((quote, index) => {
                    const document = m.submitted_documents.find(
                      (doc) =>
                        doc.package_role === role &&
                        doc.member_id === quote.member_id &&
                        doc.document_version_id === quote.document_version_id &&
                        doc.parse_run_id === quote.parse_run_id,
                    );
                    return (
                      <div key={`${quote.evidence_id}:${index}`}>
                        <blockquote>{quote.quote}</blockquote>
                        <p className="muted">
                          {quote.member_id} · 物理页 {quote.physical_page}
                        </p>
                        {document && (
                          <PackageReviewEvidence
                            bidId={run.scope.bid_id}
                            document={document}
                            quote={quote}
                          />
                        )}
                      </div>
                    );
                  })}
                </section>
              )
            );
          })}
          <details>
            <summary>要求与事实身份</summary>
            <p>
              要求编号：<code>{row.requirement_id}</code>
            </p>
            <p>
              要求摘要：<code>{row.requirement_digest}</code>
            </p>
            <p>
              规则摘要：<code>{row.rule_digest}</code>
            </p>
            {row.used_fact_ids.length ? (
              <>
                <p>本条使用的事实编号：</p>
                <ul>
                  {row.used_fact_ids.map((id) => (
                    <li key={id}>
                      <code>{id}</code>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p>本条未引用事实记录。</p>
            )}
          </details>
          {renderDecision?.(row)}
        </article>
      ))}
      {rows.length > 0 && (
        <nav className="package-review__pagination" aria-label="逐条结果分页">
          <span>
            显示 {start + 1}–{Math.min(start + 20, rows.length)} 条，共{" "}
            {rows.length} 条
          </span>
          <div className="package-review__actions">
            <button
              type="button"
              className="button secondary"
              disabled={page === 0}
              onClick={() => setPage((value) => value - 1)}
            >
              上一页要求
            </button>
            <button
              type="button"
              className="button secondary"
              disabled={start + 20 >= rows.length}
              onClick={() => setPage((value) => value + 1)}
            >
              下一页要求
            </button>
          </div>
        </nav>
      )}
      <details>
        <summary>核查结果摘要</summary>
        <p>
          <code>{result.digest}</code>
        </p>
        <p>
          导出文件保留本次完整输入身份、逐条结果和引用，可供核对；它是范围核查记录，不是投递版标书或正式评分报告。
        </p>
      </details>
      {error != null && <ErrorNotice error={error} />}
    </section>
  );
}
