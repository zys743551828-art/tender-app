import { lazy, Suspense, useRef, useState } from "react";
import type {
  PackageReviewComparisonPage,
  PackageReviewComparisonRow,
  PackageReviewComparisonRowSide,
} from "./contracts";
import {
  packageReviewComparisonChanges,
  packageReviewComparisonTotal,
} from "./packageReviewComparisonProtocol";
import { packageReviewDecisionLabels } from "./packageReviewDecisionProtocol";
import type { PackageReviewHistoricalReference } from "./packageReviewHistoricalRun";
import { packageReviewHistoricalComparison } from "./packageReviewHistoricalRun";
const OriginalRunDetails = lazy(
  () => import("./PackageReviewOriginalRunDetails"),
);
const verdicts = {
  satisfied: "已满足",
  violated: "发现不符",
  not_found: "未找到",
  unable_to_judge: "无法判定",
  not_applicable: "不适用",
};
const definitions = {
  added: "仅右侧新增",
  removed: "仅左侧存在",
  changed: "要求定义变化",
  unchanged: "要求定义相同",
};
const changeLabels = {
  run_input: "完整执行输入",
  scope: "标段与轮次范围",
  frozen_input: "冻结资料输入",
  prepared_input: "执行准备记录",
  rerun_intent: "复检意图",
  requirements: "要求定义",
  submitted_documents: "提交资料范围",
  selected_facts: "已选事实",
  fact_admission: "事实采纳依据",
  dependency_plan: "依赖计划",
  inventory_proof: "清单证明",
  method: "核查方法",
};
const methodLabels: Record<string, string> = {
  engine: "核查引擎",
  purpose: "核查用途",
  assessment: "判断方式",
  input_scope: "输入范围",
  model_json_encoding: "模型数据格式",
  model: "模型",
  endpoint: "服务地址",
  source_digest: "方法代码",
  batch_rule_limit: "单批要求上限",
  batch_limit: "批次数上限",
  output_tokens_per_batch: "单批输出预算",
  input_character_limit: "输入字符上限",
  semantic_quality: "效果测量状态",
  formal_scoring_eligible: "正式评分资格",
  submission_eligible: "投递资格",
};

function Side({
  label,
  row,
  human,
}: {
  label: string;
  row: PackageReviewComparisonRowSide | null;
  human: PackageReviewComparisonRow["left_human"];
}) {
  return (
    <section className="package-review-comparison__side" aria-label={label}>
      <h6>{label}</h6>
      {row ? (
        <>
          <h5>{row.requirement_statement}</h5>
          <p>
            <strong>{verdicts[row.verdict]}</strong>
          </p>
          <p>{row.statement}</p>
          {row.limitations.length > 0 && (
            <p className="muted">仍有限制：{row.limitations.join("、")}</p>
          )}
          <p className="muted">
            已声明册页范围：
            {row.target_part_ids.length
              ? row.target_part_ids.join("、")
              : "未声明"}
          </p>
          <div className="package-review-comparison__human">
            <strong>此侧当时的人工记录</strong>
            {human ? (
              <>
                <p>
                  {packageReviewDecisionLabels[human.state]} · 第{" "}
                  {human.sequence_no} 版
                </p>
                <p>{human.reason}</p>
                <p className="muted">{human.created_at}</p>
              </>
            ) : (
              <p className="muted">对比形成时暂无人工记录。</p>
            )}
          </div>
          <details>
            <summary>此侧要求与机器行摘要</summary>
            <p>
              要求摘要：<code>{row.requirement_digest}</code>
            </p>
            <p>
              规则摘要：<code>{row.rule_digest}</code>
            </p>
            <p>
              机器行摘要：<code>{row.row_digest}</code>
            </p>
          </details>
        </>
      ) : (
        <p className="muted">
          此侧没有相同编号的要求；不以文本相似度认定为同一条。
        </p>
      )}
    </section>
  );
}
type Props = {
  memberId: string;
  page: PackageReviewComparisonPage;
  pageIndex: number;
  complete: boolean;
  previousDisabled: boolean;
  nextDisabled: boolean;
  onPrevious: () => void;
  onNext: () => void;
};
export default function PackageReviewComparisonView({
  memberId,
  page,
  pageIndex,
  complete,
  previousDisabled,
  nextDisabled,
  onPrevious,
  onNext,
}: Props) {
  const [original, setOriginal] = useState<{
      reference: PackageReviewHistoricalReference;
      label: string;
      requirement?: { id: string; rowDigest: string };
    } | null>(null),
    opener = useRef<HTMLElement | null>(null);
  return (
    <>
      <div className="package-review__notice">
        <strong>对比不判定风险已经解决</strong>
        <p>
          整体覆盖仍为部分。要求新增、移除或判定变化均需回到各轮原文核实；本页不授予清单完整性、正式评分或投递资格。
        </p>
      </div>
      {Date.parse(page.left.created_at) > Date.parse(page.right.created_at) && (
        <p className="muted">
          右侧创建时间早于左侧。本页按当前选择顺序比较，可交换两侧再读取。
        </p>
      )}
      <div className="package-review-comparison__columns">
        {(["left", "right"] as const).map((side) => {
          const r = page[side],
            label = side === "left" ? "左侧原核查" : "右侧原核查";
          return (
            <section
              className="package-review-comparison__side"
              key={side}
              aria-label={label}
            >
              <h5>{label}</h5>
              <p>
                {r.created_at} · {r.requirement_count} 条要求
              </p>
              <p>
                {r.matrix_coverage === "complete"
                  ? "逐条矩阵完成"
                  : "逐条矩阵仍有缺口"}{" "}
                · 整体部分覆盖
              </p>
              <p>
                核查编号：<code>{r.id}</code>
              </p>
              <button
                type="button"
                className="button secondary"
                onClick={(event) => {
                  opener.current = event.currentTarget;
                  setOriginal({
                    reference: packageReviewHistoricalComparison(r),
                    label: `${label}详情`,
                  });
                }}
              >
                查看{side === "left" ? "左侧" : "右侧"}原结果与引用
              </button>
              <details>
                <summary>此侧输入与人工快照摘要</summary>
                <p>
                  输入：<code>{r.input_digest}</code>
                </p>
                <p>
                  结果：<code>{r.result_digest}</code>
                </p>
                <p>
                  人工状态：<code>{r.human_heads_digest}</code>
                </p>
              </details>
            </section>
          );
        })}
      </div>
      {original && (
        <Suspense fallback={<p role="status">正在打开原核查…</p>}>
          <OriginalRunDetails
            memberId={memberId}
            {...original}
            onClose={() => {
              setOriginal(null);
              opener.current?.focus();
            }}
          />
        </Suspense>
      )}
      <details>
        <summary>两轮输入有哪些变化</summary>
        <dl className="package-review-comparison__changes">
          {packageReviewComparisonChanges.map((key) => (
            <div key={key}>
              <dt>{changeLabels[key]}</dt>
              <dd>{page.input_changes[key] ? "有变化" : "相同"}</dd>
            </div>
          ))}
        </dl>
        {page.input_changes.method_fields.length > 0 && (
          <p>
            方法变化项：
            {page.input_changes.method_fields
              .map((field) => methodLabels[field] ?? field)
              .join("、")}
          </p>
        )}
      </details>
      <dl className="package-review-comparison__counts">
        {(["added", "removed", "changed", "unchanged"] as const).map((key) => (
          <div key={key}>
            <dt>{definitions[key]}</dt>
            <dd>{page.counts[key]}</dd>
          </div>
        ))}
        <div>
          <dt>机器行有变化</dt>
          <dd>{page.counts.machine_row_changed}</dd>
        </div>
        <div>
          <dt>机器判定类别有变化</dt>
          <dd>{page.counts.verdict_changed}</dd>
        </div>
      </dl>
      <p className="muted">
        要求按精确编号及要求、规则摘要匹配。定义相同也可能存在引用或机器判断变化，人工意见分别保留。
      </p>
      {page.items.map((row) => (
        <article
          className="package-review-comparison__row"
          key={row.requirement_id}
          aria-label={`对比要求：${row.requirement_id}`}
        >
          <div className="package-review__heading">
            <strong>{definitions[row.definition_change]}</strong>
            <code>{row.requirement_id}</code>
          </div>
          <p>
            {row.verdict_transition
              ? `机器判定：${verdicts[row.verdict_transition.from]} → ${verdicts[row.verdict_transition.to]}${row.verdict_transition.changed ? "（类别有变化）" : "（类别相同）"}`
              : "只有单侧要求，不比较判定变化。"}
          </p>
          {row.machine_row_changed === true && (
            <p className="muted">
              原机器行有变化，具体引用与判断依据请分别查看两侧原结果。
            </p>
          )}
          <div className="package-review-comparison__columns">
            <Side
              label="左侧要求与判断"
              row={row.left}
              human={row.left_human}
            />
            <Side
              label="右侧要求与判断"
              row={row.right}
              human={row.right_human}
            />
          </div>
          <div className="package-review__actions">
            {(["left", "right"] as const).map(
              (side) =>
                row[side] && (
                  <button
                    key={side}
                    type="button"
                    className="button secondary"
                    onClick={(event) => {
                      opener.current = event.currentTarget;
                      setOriginal({
                        reference: packageReviewHistoricalComparison(
                          page[side],
                        ),
                        label: `${side === "left" ? "左侧" : "右侧"}此项原结果与引用`,
                        requirement: {
                          id: row.requirement_id,
                          rowDigest: row[side]!.row_digest,
                        },
                      });
                    }}
                  >
                    查看此项{side === "left" ? "左侧" : "右侧"}原结果与引用
                  </button>
                ),
            )}
          </div>
        </article>
      ))}
      <nav className="package-review__pagination" aria-label="两轮要求对比分页">
        <span>
          第 {pageIndex + 1} 页 · 当前 {page.items.length} 条 · 共{" "}
          {packageReviewComparisonTotal(page)} 条
        </span>
        <div className="package-review__actions">
          <button
            type="button"
            className="button secondary"
            disabled={previousDisabled}
            onClick={onPrevious}
          >
            上一页对比
          </button>
          <button
            type="button"
            className="button secondary"
            disabled={nextDisabled}
            onClick={onNext}
          >
            下一页对比
          </button>
        </div>
      </nav>
      <details>
        <summary>本次对比摘要与核对范围</summary>
        <p>
          <code>{page.comparison_digest}</code>
        </p>
        <p>
          {complete
            ? "所有分页的条数、变化分类与完整对比摘要已核对。"
            : "当前显示已读取的分页；读取所有分页后核对完整对比摘要。"}
        </p>
        <p>人工状态是对比形成时的快照，其他成员后续更新后须重新读取对比。</p>
      </details>
    </>
  );
}
