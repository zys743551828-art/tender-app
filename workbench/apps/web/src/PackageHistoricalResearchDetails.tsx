import { useState } from "react";
import type {
  PackageHistoricalAdmissionView,
  PackageHistoricalCohort,
  PackageHistoricalJobView,
  PackageHistoricalProtocol,
} from "./contracts";
import { Badge } from "./components";

import { historyTime, historyPurposeNames } from "./packageHistoryPresentation";

export function HistoryOrigin({ origin }: { origin: string }) {
  return (
    <Badge tone={origin === "synthetic" ? "warning" : ""}>
      {origin === "synthetic" ? "合成机制资料" : "外部证据资料"}
    </Badge>
  );
}

export function HistoryIdentity({
  values,
}: {
  values: Record<string, string>;
}) {
  return (
    <details className="package-history-identity">
      <summary>查看确切版本与来源标识</summary>
      <dl>
        {Object.entries(values).map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

export function HistoryAdmissionDetails({
  value,
  onOpenBid,
}: {
  value: PackageHistoricalAdmissionView;
  onOpenBid?: (bidId: string) => void;
}) {
  const a = value.admission;
  return (
    <div className="package-history-details">
      <div className="package-history-badges">
        <HistoryOrigin origin={a.origin} />
        <Badge tone={value.current ? "" : "warning"}>
          {value.current ? "本次读取时依据有效" : "当前依据已变化"}
        </Badge>
      </div>
      {!value.current && (
        <p className="notice warning">
          原准入记录保留；当前来源、官方结果或关联关系已变化，不能据此开始新的研究用途。
        </p>
      )}
      <dl className="package-history-facts">
        <div>
          <dt>已核对的官方技术分</dt>
          <dd>
            {a.official_technical_value} / {a.technical_maximum}
          </dd>
        </div>
        <div>
          <dt>分数口径</dt>
          <dd>公布的最终技术总分</dd>
        </div>
        <div>
          <dt>确切实交时点</dt>
          <dd>{historyTime(a.historical_as_of)}</dd>
        </div>
        <div>
          <dt>技术范围冻结</dt>
          <dd>{historyTime(a.scope_frozen_at)}</dd>
        </div>
        <div>
          <dt>标签知悉</dt>
          <dd>{historyTime(a.label_known_at)}</dd>
        </div>
        <div>
          <dt>证据核验</dt>
          <dd>{historyTime(a.evidence_verified_at)}</dd>
        </div>
        <div>
          <dt>准入登记</dt>
          <dd>{historyTime(a.admitted_at)}</dd>
        </div>
      </dl>
      <p className="small-note">
        准入仅供回溯研究，不授予事前预测、在线指标或正式模型资格。
      </p>
      {onOpenBid && (
        <button
          type="button"
          className="text-button"
          onClick={() => onOpenBid(a.bid_id)}
        >
          查看所属项目与成绩
        </button>
      )}
      <HistoryIdentity
        values={{
          准入记录: a.id,
          项目: a.bid_id,
          技术范围: a.scope_id,
          实交: a.submission_id,
          官方结果: a.outcome_id,
          独立核验回执: a.proof_id,
          准入摘要: a.digest,
        }}
      />
    </div>
  );
}

export function HistoryProtocolDetails({
  value,
}: {
  value: PackageHistoricalProtocol;
}) {
  return (
    <div className="package-history-details">
      <dl className="package-history-facts">
        <div>
          <dt>候选方法</dt>
          <dd>项目等权平均值 / 中位数</dd>
        </div>
        <div>
          <dt>开发集选择</dt>
          <dd>按项目平均绝对误差；并列时优先平均值</dd>
        </div>
        <div>
          <dt>随机种子</dt>
          <dd>{value.document.seed}</dd>
        </div>
        <div>
          <dt>组级重采样次数</dt>
          <dd>{value.document.bootstrap_iterations}</dd>
        </div>
        <div>
          <dt>外部模型请求</dt>
          <dd>0 次</dd>
        </div>
      </dl>
      <p className="small-note">
        拟合后不混入开发集重新拟合。区间仅在独立校准组足够时提供；此处是常数基线研究，不是三评特征校准或正式发布。
      </p>
      <HistoryIdentity
        values={{
          协议: value.id,
          协议摘要: value.digest,
          "CPU 方法摘要": value.document.method.digest,
        }}
      />
    </div>
  );
}

export function HistoryCohortDetails({
  value,
}: {
  value: PackageHistoricalCohort;
}) {
  const [page, setPage] = useState(0);
  const visible = value.members.slice(page * 20, page * 20 + 20);
  return (
    <div className="package-history-details">
      <HistoryOrigin origin={value.origin} />
      <dl className="package-history-facts">
        <div>
          <dt>实交分界</dt>
          <dd>{historyTime(value.timing.submission_split_at)}</dd>
        </div>
        <div>
          <dt>标签可用截止</dt>
          <dd>{historyTime(value.timing.label_available_as_of)}</dd>
        </div>
        <div>
          <dt>训练冻结</dt>
          <dd>{historyTime(value.timing.training_frozen_at)}</dd>
        </div>
        <div>
          <dt>研究类型</dt>
          <dd>按确切实交时间留出的回溯研究</dd>
        </div>
      </dl>
      <p>
        本组 {value.members.length}{" "}
        份准入记录。跨实交分界的关联组整体排除；迟到标签保留为未知，不补零。
      </p>
      <div
        className="package-history-table-wrap"
        tabIndex={0}
        aria-label="研究组实际成员"
      >
        <table>
          <thead>
            <tr>
              <th>记录</th>
              <th>请求用途</th>
              <th>实际用途</th>
              <th>原实交时点</th>
              <th>分组与排除说明</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((member, index) => (
              <tr key={member.admission_id}>
                <td>
                  记录 {page * 20 + index + 1}
                  <small>{member.admission_id}</small>
                </td>
                <td>{historyPurposeNames[member.requested_purpose]}</td>
                <td>{historyPurposeNames[member.purpose]}</td>
                <td>{historyTime(member.submitted_at)}</td>
                <td>
                  {member.exclusion_reason === "group_spans_submission_split"
                    ? "关联组跨越实交分界，整组排除"
                    : member.exclusion_reason === "label_after_available_cutoff"
                      ? "标签晚于截止时点，保留未知"
                      : "按服务端完整关联组冻结"}
                  <small>
                    关联记录 {member.closure_ids.length} 份 · 组{" "}
                    {member.group_id}
                  </small>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {value.members.length > 20 && (
        <div className="package-history-toolbar">
          <button
            type="button"
            className="text-button"
            disabled={page === 0}
            onClick={() => setPage(page - 1)}
          >
            上一页成员
          </button>
          <span>
            第 {page + 1} / {Math.ceil(value.members.length / 20)} 页
          </span>
          <button
            type="button"
            className="text-button"
            disabled={(page + 1) * 20 >= value.members.length}
            onClick={() => setPage(page + 1)}
          >
            下一页成员
          </button>
        </div>
      )}
      <HistoryIdentity
        values={{
          研究组: value.id,
          协议: value.protocol_id,
          协议摘要: value.protocol_digest,
          成员摘要: value.membership_digest,
          研究组摘要: value.digest,
        }}
      />
    </div>
  );
}

type Evaluation = Extract<
  NonNullable<PackageHistoricalJobView["result"]>,
  { schema: "package-history-independent-evaluation/1" }
>;
function Metrics({
  report,
  title,
}: {
  report: Evaluation["report"];
  title: string;
}) {
  const rows: [string, string | number | null][] = [
    ["总分母", report.denominator],
    ["独立关联组", report.independent_groups],
    ["工程项目", report.projects],
    ["成功", report.counts.succeeded],
    ["失败", report.counts.failed],
    ["拒绝", report.counts.rejected],
    ["未标注", report.counts.unlabeled],
    ["成功覆盖比例（0—1）", report.success_coverage],
    ["样本平均绝对误差", report.sample_mae],
    ["项目等权平均绝对误差", report.project_mae],
    ["原量尺项目误差", report.original_scale_project_mae],
    ["绝对误差 P90", report.p90_absolute_error],
    ["项目等权 ±3 分内比例（0—1）", report.project_within_three],
    ["项目等权偏差", report.project_bias],
    ["同输入独立复跑极差 P90", report.stability_range_p90],
  ];
  return (
    <section className="package-history-metrics" aria-label={title}>
      <h4>{title}</h4>
      <dl className="package-history-facts">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value === null ? "未取得" : value}</dd>
          </div>
        ))}
      </dl>
      <p className="small-note">
        组级重采样项目误差 95% 区间：
        {report.group_bootstrap_project_mae_95?.join(" — ") ??
          "独立组或标签不足，未取得"}
      </p>
      <div className="package-history-table-wrap">
        <table>
          <thead>
            <tr>
              <th>预测区间</th>
              <th>实际覆盖比例</th>
              <th>区间宽度</th>
            </tr>
          </thead>
          <tbody>
            {(["0.8", "0.9"] as const).map((level) => (
              <tr key={level}>
                <td>{level === "0.8" ? "80%" : "90%"}</td>
                <td>{report.intervals[level].coverage ?? "未取得"}</td>
                <td>{report.intervals[level].width ?? "未取得"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <details>
        <summary>查看配对基线与分层统计</summary>
        {(["mean", "median"] as const).map((name) => {
          const baseline = report.paired_baselines[name];
          return (
            <p key={name}>
              {name === "mean" ? "平均值" : "中位数"}基线增益：
              {baseline?.gain ?? "未取得"}
              {baseline && "paired_count" in baseline
                ? `；配对 ${baseline.paired_count}；组级 95% 区间 ${baseline.group_bootstrap_gain_95?.join(" — ") ?? "未取得"}`
                : "；缺少配对基线"}
            </p>
          );
        })}
        {(["method", "maximum", "engineering_type"] as const).map((kind) => (
          <div key={kind}>
            <h5>
              {
                {
                  method: "方法",
                  maximum: "满分量尺",
                  engineering_type: "工程类型",
                }[kind]
              }
            </h5>
            {Object.entries(report.strata[kind]).length ? (
              Object.entries(report.strata[kind]).map(([name, item]) => (
                <p key={name}>
                  {name}：{item.count} 份；项目误差{" "}
                  {item.project_mae ?? "未取得"}
                </p>
              ))
            ) : (
              <p>未取得可分层记录。</p>
            )}
          </div>
        ))}
      </details>
    </section>
  );
}

export function HistoryJobResult({
  value,
}: {
  value: PackageHistoricalJobView;
}) {
  const result = value.result;
  if (!result)
    return (
      <p className="small-note">
        此任务尚无已发布结果。等待状态、执行失败或取消均不计为研究通过。
      </p>
    );
  return (
    <div className="package-history-details">
      <HistoryOrigin origin={result.origin} />
      <p className="notice warning">
        {result.origin === "synthetic"
          ? "以下结果来自合成机制资料，只证明软件执行与统计流程，不代表真实模型准确率。"
          : "以下为这一冻结研究组的回溯结果，尚未取得业务验收和正式发布资格。"}
      </p>
      {result.schema === "package-history-training-result/1" ? (
        <>
          {result.complete_feature_training && (
            <section aria-label="特征研究候选">
              <h4>完整材料六特征岭回归候选</h4>
              <p className="notice warning">
                此训练记录不包含最终测试，请查看独立评估任务。研究候选不代表正式预测或真实效果通过。
              </p>
              <p>
                拟合组 {result.complete_feature_training.groups.fit}；开发组{" "}
                {result.complete_feature_training.groups.development}；校准组{" "}
                {result.complete_feature_training.groups.calibration}。
              </p>
              {result.complete_feature_training.status ===
              "research_candidate" ? (
                <p>
                  特征已参与候选拟合。开发集选定正则化参数 α：
                  {result.complete_feature_training.selection.selected_alpha}
                  。预处理仅使用拟合集，未用开发集重新拟合。
                </p>
              ) : (
                <p>
                  候选不可用：缺少足够独立组、有效数值档位或可变化的拟合特征。未生成候选模型或区间。
                </p>
              )}
              <HistoryIdentity
                values={{
                  候选方法版本: result.complete_feature_training.version,
                  候选方法摘要: result.complete_feature_training.method_digest,
                  特征投影摘要:
                    result.complete_feature_training.projection_digest,
                }}
              />
            </section>
          )}
          <h4>CPU 基线训练结果</h4>
          {result.complete_material_consumer && (
            <>
              <p className="notice warning">
                已核对 {result.complete_material_consumer.receipts.length}{" "}
                份完整材料。
                {result.complete_feature_training?.status ===
                "research_candidate"
                  ? "以下常数基线仍按原方法；另存的特征候选未取得正式评分资格。"
                  : "当前仍为常数基线，材料特征未参与拟合，不具备正式评分资格。"}
              </p>
              <HistoryIdentity
                values={{
                  材料引用摘要:
                    result.complete_material_consumer.reference_digest,
                  原生绑定摘要:
                    result.complete_material_consumer.bindings_digest,
                  消费方法摘要: result.complete_material_consumer.method_digest,
                }}
              />
            </>
          )}
          <dl className="package-history-facts">
            <div>
              <dt>开发集选择的方法</dt>
              <dd>
                {result.model.family === "mean"
                  ? "项目等权平均值"
                  : "项目等权中位数"}
              </dd>
            </div>
            <div>
              <dt>固定常数（百分制）</dt>
              <dd>{result.model.constant}</dd>
            </div>
            <div>
              <dt>平均值基线</dt>
              <dd>{result.baselines.mean}</dd>
            </div>
            <div>
              <dt>中位数基线</dt>
              <dd>{result.baselines.median}</dd>
            </div>
            <div>
              <dt>平均值开发集项目误差</dt>
              <dd>{result.selection.development_project_mae.mean}</dd>
            </div>
            <div>
              <dt>中位数开发集项目误差</dt>
              <dd>{result.selection.development_project_mae.median}</dd>
            </div>
          </dl>
          {(["0.8", "0.9"] as const).map((level) => (
            <p className="small-note" key={level}>
              {level === "0.8" ? "80%" : "90%"} 区间半径：
              {result.intervals[level].radius ?? "独立校准组不足，未取得"}
              ；校准组 {result.intervals[level].groups}。
            </p>
          ))}
        </>
      ) : (
        <>
          <h4>独立最终评估记录</h4>
          {result.feature_final_evaluation ? (
            <section aria-label="冻结特征候选独立评价">
              <h4>冻结特征候选独立评价</h4>
              <p className="small-note">
                以下结果来自曝光前冻结的特征候选；未重新拟合或选择模型。研究机制结果不代表真实精度通过，正式预测资格仍未取得。
              </p>
              <Metrics
                report={result.feature_final_evaluation.report}
                title="特征候选最终评估记录"
              />
              <HistoryIdentity
                values={{
                  特征候选摘要:
                    result.feature_final_evaluation.candidate_digest,
                  特征模型摘要: result.feature_final_evaluation.model_digest,
                  特征预测摘要:
                    result.feature_final_evaluation.predictions_digest,
                  冻结输入摘要: result.feature_final_evaluation.input_digest,
                  曝光记录: result.feature_final_evaluation.exposure_id,
                  特征评价方法: result.feature_final_evaluation.method_digest,
                }}
              />
              <p className="small-note">
                以下另列原常数基线，使用相同 final 标签与原始分母。
              </p>
            </section>
          ) : (
            <p className="small-note">
              此评估使用已冻结的常数基线，不评价特征研究候选。
            </p>
          )}
          <p>
            原选择 {result.selection_denominator.selected_submissions} 份；排除{" "}
            {result.selection_denominator.excluded_submissions}{" "}
            份；最终评估一侧候选{" "}
            {result.selection_denominator.final_side_candidates} 份。
          </p>
          <Metrics report={result.report} title="全部最终评估记录" />
          <Metrics
            report={result.official_source_subset.report}
            title="有证据核对的官方来源子集"
          />
          <p className="small-note">
            排名、入围概率、评委分歧和同输入独立复跑稳定性均未取得相应标签或实验。正式质量验收、事前业务认证及观察发布仍未完成。
            {!result.feature_final_evaluation &&
              "本常数基线未消费完整三评特征。"}
          </p>
        </>
      )}
      <p className="small-note">
        本次记录：外部供应商请求 {result.provider_requests} 次，付费调用{" "}
        {result.paid_calls} 次。正式预测资格：未取得。
      </p>
      <HistoryIdentity
        values={{
          任务: value.job_id,
          研究组: result.cohort_id,
          模型摘要: result.model_digest,
          协议摘要: result.protocol_digest,
          成员摘要: result.membership_digest,
          结果摘要: value.result_digest ?? "未提供",
        }}
      />
    </div>
  );
}
