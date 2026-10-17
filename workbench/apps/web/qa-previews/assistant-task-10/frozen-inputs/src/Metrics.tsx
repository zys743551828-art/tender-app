import { useState } from "react";
import type { BusinessMetricsView } from "./contracts";
import { supportsApi } from "./api";
import {
  businessStages,
  businessReason,
  resultVerifications,
} from "./businessNames";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import { useBidChoices } from "./useBidChoices";
import { ErrorNotice } from "./components";

function percent(value: string | null) {
  if (value === null) return "暂无可评价结果";
  // Display only; the authoritative numerator, denominator and Decimal ratio are from the server.
  return `${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(Number(value) * 100)}%`;
}
export function Metrics() {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [scope, setScope] = useState("ledger");
  const [bidIds, setBidIds] = useState<string[]>([]);
  const [path, setPath] = useState("/metrics?verification_scope=ledger");
  const bids = useBidChoices();
  const resource = useResource<BusinessMetricsView>(
    supportsApi("GET", "/metrics") ? path : null,
  );
  const data = resource.data;
  return (
    <div className="page-content metrics-page">
      <header className="page-heading">
        <div>
          <span className="eyebrow">真实实交 · 口径可查</span>
          <h1>业务结果与指标</h1>
          <p className="muted">
            按工程、标段／轮次和投标主体的当前实际提交统计。阶段结果与技术成绩分开，不从分数推断中标。
          </p>
        </div>
      </header>
      <section className="panel">
        <form
          className="metrics-filter"
          onSubmit={(event) => {
            event.preventDefault();
            const params = new URLSearchParams({ verification_scope: scope });
            if (from) params.set("period_from", new Date(from).toISOString());
            if (to) params.set("period_to", new Date(to).toISOString());
            bidIds.forEach((id) => params.append("bid_ids", id));
            const next = `/metrics?${params}`;
            if (next === path) void resource.reload();
            else setPath(next);
          }}
        >
          <label>
            实交时间起
            <input
              type="datetime-local"
              value={from}
              onChange={(event) => setFrom(event.target.value)}
              max={to || undefined}
            />
          </label>
          <label>
            实交时间止
            <input
              type="datetime-local"
              value={to}
              onChange={(event) => setTo(event.target.value)}
              min={from || undefined}
            />
          </label>
          <label>
            统计口径
            <select
              aria-label="统计口径"
              value={scope}
              onChange={(event) => setScope(event.target.value)}
            >
              <option value="ledger">公司台账（含明确标注的未核实报送）</option>
              <option value="verified_only">仅官方依据已人工核实</option>
            </select>
          </label>
          <details className="coverage-details">
            <summary>限定项目（已选{bidIds.length}个，最多20个）</summary>
            <p className="small-note">
              不选择表示全部可读项目，项目目录仍有下一页时可继续加载。
            </p>
            <ResourceState
              {...bids}
              hasData={!!bids.data}
              onRetry={() => void bids.reload()}
            />
            {bids.items.map((bid) => (
              <label className="checkbox-label" key={bid.id}>
                <input
                  type="checkbox"
                  checked={bidIds.includes(bid.id)}
                  disabled={!bidIds.includes(bid.id) && bidIds.length >= 20}
                  onChange={(event) =>
                    setBidIds((old) =>
                      event.target.checked
                        ? [...old, bid.id]
                        : old.filter((id) => id !== bid.id),
                    )
                  }
                />
                {bid.title}
              </label>
            ))}
            <ErrorNotice error={bids.moreError} />
            {bids.hasMore && (
              <button
                type="button"
                className="text-button"
                disabled={bids.moreBusy}
                onClick={() => void bids.loadMore()}
              >
                加载更多项目
              </button>
            )}
          </details>
          <button className="button secondary" disabled={resource.loading}>
            更新统计范围
          </button>
        </form>
      </section>
      <ResourceState
        {...resource}
        hasData={!!data}
        onRetry={() => void resource.reload()}
      />
      {data && (
        <>
          <section className="panel">
            <h2>
              {data.scope.verification_scope === "ledger"
                ? "公司台账 · 含未核实报送"
                : "仅官方依据已人工核实"}
            </h2>
            <p>
              统计范围：
              {data.scope.bid_ids
                ? `明确选择的${data.scope.bid_ids.length}个项目`
                : "全部可读项目"}
              。按实际提交时间：
              {data.scope.period_from
                ? new Date(data.scope.period_from).toLocaleString("zh-CN")
                : "不限起点"}{" "}
              至{" "}
              {data.scope.period_to
                ? new Date(data.scope.period_to).toLocaleString("zh-CN")
                : "不限终点"}
              ；截至 {new Date(data.scope.as_of).toLocaleString("zh-CN")}。
            </p>
            <p className="small-note">{data.scope.scope_note}</p>
            <div className="metric-grid">
              {(
                [
                  ["当前有效实交", data.effective_submissions],
                  ["阶段已知", data.known_outcomes],
                  ["阶段未知", data.unknown_outcomes],
                  ["核验冲突", data.conflicted_outcomes],
                  ["当前不可用", data.unusable_outcomes],
                ] as const
              ).map(([label, count]) => (
                <div className="metric-tile" key={label}>
                  <span>{label}</span>
                  <strong>{count}</strong>
                </div>
              ))}
            </div>
            <div className="metric-grid">
              {(
                [
                  ["技术入围率", data.shortlist_rate],
                  ["最终中标率", data.win_rate],
                ] as const
              ).map(([label, ratio]) => (
                <div className="metric-tile" key={label}>
                  <span>{label}</span>
                  <strong>
                    {ratio.denominator === 0
                      ? "暂无可评价结果"
                      : percent(ratio.value)}
                  </strong>
                  <small>
                    分子 {ratio.numerator} ／ 分母 {ratio.denominator}
                  </small>
                </div>
              ))}
            </div>
            <p className="small-note">
              候选不等于中标；取消、流标、未知与冲突不当作未中标。技术入围率与最终中标率使用各自分母。
            </p>
            <h3>结果核验构成</h3>
            <Counts
              values={data.verification_counts}
              labels={resultVerifications}
            />
            <h3>明确阶段</h3>
            <Counts values={data.stage_counts} labels={businessStages} />
          </section>
          <section className="panel">
            <h2>关键风险闭环</h2>
            <p className="small-note">{data.qualification.scope_note}</p>
            <div className="metric-grid">
              {(
                [
                  ["已识别", data.qualification.identified],
                  ["有效复检已解决", data.qualification.resolved],
                  ["有理由驳回", data.qualification.dismissed],
                  ["当前未解决", data.qualification.open],
                  ["实交时未解决", data.qualification.open_at_submission],
                ] as const
              ).map(([label, count]) => (
                <div className="metric-tile" key={label}>
                  <span>{label}</span>
                  <strong>{count ?? "未知"}</strong>
                </div>
              ))}
            </div>
            <p>
              实交时快照：已知 {data.qualification.known_snapshot_submissions}{" "}
              份 ／ 未知 {data.qualification.unknown_snapshot_submissions}{" "}
              份；当前评审范围已知{" "}
              {data.qualification.known_current_review_submissions} 份 ／ 未知{" "}
              {data.qualification.unknown_current_review_submissions} 份。
            </p>
            <p>
              官方业务结果中的否决 {data.qualification.official_rejections}{" "}
              次。不推断由哪项系统风险导致。
            </p>
          </section>
          <section className="panel">
            <h2>在线预测误差</h2>
            <p>
              有效配对 {data.online_error.prediction_pairs} ／ 展示门槛{" "}
              {data.online_error.needed_pairs}。
            </p>
            {data.online_error.online_error_state === "sufficient" &&
            data.online_error.prediction_pairs >=
              data.online_error.needed_pairs ? (
              <p>
                百分制 MAE：{data.online_error.mae ?? "不可用"}；有符号 bias：
                {data.online_error.bias ?? "不可用"}
              </p>
            ) : (
              <p className="notice neutral">
                尚无足够有效配对，MAE与bias不展示，不将缺失值补成0。
              </p>
            )}
            <p className="small-note">
              {data.online_error.scope_note} 统计门槛不授予模型正式资格。
            </p>
            <Counts values={data.online_error.excluded_pair_counts} />
          </section>
          <details className="panel identity-details">
            <summary>排除范围与统计身份</summary>
            <h3>排除的提交</h3>
            <Counts values={data.scope.excluded_submission_counts} />
            <h3>排除的结果</h3>
            <Counts values={data.excluded_result_counts} />
            <p>
              身份／提交冲突 {data.scope.identity_submission_conflicts.length}{" "}
              组；不会按名称近似或完成时间猜测消重。
            </p>
            <p>
              口径 {data.scope.definition}；有效头摘要{" "}
              {data.scope.effective_head_digest}。
            </p>
            {data.scope.head_authorities.map((head) => (
              <p key={head.submission_id}>
                <a href={`/bids/${head.bid_id}/outcomes`}>查看对应实交与结果</a>{" "}
                · 实交修订 {head.submission_revision} · 结果修订{" "}
                {head.result_head.revision} ·{" "}
                {head.result_exclusions.map(businessReason).join("；") ||
                  "无已报告的结果排除原因"}
              </p>
            ))}
          </details>
        </>
      )}
    </div>
  );
}
function Counts({
  values,
  labels = {},
}: {
  values: Record<string, number>;
  labels?: Record<string, string>;
}) {
  return Object.keys(values).length ? (
    <dl className="metric-counts">
      {Object.entries(values).map(([key, count]) => (
        <div key={key}>
          <dt>{labels[key] ?? businessReason(key)}</dt>
          <dd>{count}</dd>
        </div>
      ))}
    </dl>
  ) : (
    <p className="small-note">当前范围未返回分类计数，不补造统计。</p>
  );
}
