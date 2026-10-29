import { useRef, useState } from "react";
import type { PackageWorkContext } from "./contracts";
import { Badge } from "./components";
import type { PackageNavigationTarget } from "./packageNavigation";
import { workContextDimensions } from "./workContextProtocol";
import "./WorkContext.css";

const dimensions = {
  identity: "投标主体与工程身份",
  package_head: "投标包当前修订",
  authority_head: "依据包当前修订",
  inventory_head: "要求清单",
  rule_set_head: "规则版本",
  sources: "来源可用性",
  selected_facts: "选定事实",
  executor_method: "核查方法",
  submission_head: "实交记录头",
  review_run_head: "核查轮次当前性",
  bound_run_state: "所绑定核查状态",
};
const statuses = {
  matched: "与本次观察相符",
  changed: "依据已变化",
  unknown: "尚不能判断",
  not_applicable: "此项不适用",
};
const machine = {
  satisfied: "已满足",
  violated: "发现不符",
  not_found: "未找到",
  unable_to_judge: "无法判定",
  not_applicable: "不适用",
};
const human = {
  unreviewed: "尚未复核",
  confirmed: "已确认原判定",
  rejected: "已驳回原判定",
  needs_review: "仍需核对",
};
const operations = {
  queued: "已排队",
  running: "正在处理",
  cancel_requested: "正在等待取消结果",
  succeeded: "处理已完成",
  failed: "处理失败",
  cancelled: "已取消",
};
const time = (value: string) =>
  new Date(value).toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour12: false,
  });

export function WorkContextSummary({
  context,
  onOpenOriginal,
  onOpenPackage,
  emphasizeOriginal = true,
}: {
  context: PackageWorkContext;
  onOpenOriginal: () => void;
  onOpenPackage: (target: PackageNavigationTarget) => void;
  emphasizeOriginal?: boolean;
}) {
  const [basisOpen, setBasisOpen] = useState(false);
  const basis = useRef<HTMLDetailsElement>(null);
  const selected = context.selection,
    review = context.summary.review;
  const changes = workContextDimensions.filter(
    (key) => context.current_observation[key].status === "changed",
  );
  const action = context.summary.primary_action;
  const label =
    action === "inspect_changed_basis"
      ? "核对变化依据"
      : action === "open_selected_submission"
        ? "读取所选实交原记录"
        : action === "view_selected_operation"
          ? "查看此次处理记录"
          : "读取所选核查原记录";
  function primary() {
    if (action !== "inspect_changed_basis") return onOpenOriginal();
    setBasisOpen(true);
    queueMicrotask(() => basis.current?.querySelector("summary")?.focus());
  }
  return (
    <section className="panel work-context-summary" aria-label="所选记录摘要">
      <div className="section-heading">
        <div>
          <span className="eyebrow">所选历史身份已固定</span>
          <h2>
            {selected.kind === "package_review_run"
              ? "整包范围核查"
              : "整包实交记录"}
          </h2>
          <p>
            {context.identity.engineering_title} ·{" "}
            {context.identity.lot ?? "标段尚未登记"} · 第{" "}
            {context.identity.round_no} 轮
          </p>
          <p className="muted">
            {context.identity.bidder_name}
            {context.identity.binding_status === "pending"
              ? " · 身份待确认"
              : ""}
          </p>
        </div>
        <Badge tone={changes.length ? "warning" : "neutral"}>
          {changes.length ? `${changes.length} 项依据已变化` : "已读取历史记录"}
        </Badge>
      </div>
      <p className="small-note">
        读取于 {time(context.observed_at)}
        （北京时间）。当前性按各项依据分别观察。
      </p>
      <div className="work-context-summary__status">
        <article>
          <span>读取时状态</span>
          <strong>
            {context.state.kind === "package_review_run"
              ? operations[context.state.operation_state]
              : context.state.registration_kind === "offline_fact"
                ? "线下事实补录"
                : "标准登记"}
          </strong>
        </article>
        <article>
          <span>整包风险</span>
          <strong>尚未完整评估</strong>
        </article>
        <article>
          <span>正式技术分</span>
          <strong>尚未选择评分范围</strong>
        </article>
      </div>
      {review ? (
        <>
          <h3>所选范围的机器判定</h3>
          <p className="small-note">
            共 {review.requirement_count}{" "}
            条要求，整体覆盖为部分。以下条数按原判定统计。
          </p>
          <dl className="work-context-summary__counts">
            {Object.entries(machine).map(([key, name]) => (
              <div key={key}>
                <dt>{name}</dt>
                <dd>{review.machine_counts[key as keyof typeof machine]}</dd>
              </div>
            ))}
          </dl>
          <details>
            <summary>人工复核记录</summary>
            <dl className="work-context-summary__counts">
              {Object.entries(human).map(([key, name]) => (
                <div key={key}>
                  <dt>{name}</dt>
                  <dd>{review.human_counts[key as keyof typeof human]}</dd>
                </div>
              ))}
            </dl>
            <p className="small-note">
              这是所选结果目前的人工意见，原机器判定继续保留；风险是否解决仍需另行核验。
            </p>
          </details>
        </>
      ) : (
        <p className="notice neutral">
          {context.summary.review_status === "bound_result_missing"
            ? "本次实交登记时未绑定核查结果，后来的结果不会补入此历史摘要。"
            : context.summary.review_status === "not_selected"
              ? "本次实交明确未绑定整包核查。"
              : "此次核查尚无可读取结果，处理记录继续保留。"}
        </p>
      )}
      <div className="work-context-summary__actions">
        <button
          type="button"
          className={emphasizeOriginal ? "button primary" : "button secondary"}
          onClick={primary}
        >
          {label}
        </button>
        {action === "inspect_changed_basis" && (
          <button
            type="button"
            className="button secondary"
            onClick={onOpenOriginal}
          >
            读取所选原记录
          </button>
        )}
        <button
          type="button"
          className="text-button"
          onClick={() =>
            onOpenPackage({
              packageId: selected.package_id,
              revisionId: selected.revision_id,
              inventoryId:
                selected.kind === "package_review_run"
                  ? selected.inventory_id
                  : (selected.inventory?.id ?? null),
            })
          }
        >
          打开此包修订
        </button>
      </div>
      <details
        ref={basis}
        open={basisOpen}
        onToggle={(event) => setBasisOpen(event.currentTarget.open)}
      >
        <summary>当前依据逐项观察</summary>
        <div className="work-context-table">
          <table>
            <thead>
              <tr>
                <th scope="col">依据</th>
                <th scope="col">本次观察</th>
              </tr>
            </thead>
            <tbody>
              {workContextDimensions.map((key) => (
                <tr key={key}>
                  <th scope="row">{dimensions[key]}</th>
                  <td>{statuses[context.current_observation[key].status]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small-note">
          阅读历史记录不会授予新的生成、核查或提交资格；执行时会重新核对条件。
        </p>
      </details>
      <details>
        <summary>固定身份与技术核对信息</summary>
        <dl className="work-context-identity">
          <dt>包修订</dt>
          <dd>{selected.revision_id}</dd>
          <dt>包摘要</dt>
          <dd>{selected.package_digest}</dd>
          <dt>选择摘要</dt>
          <dd>{context.selection_digest}</dd>
          <dt>本次观察摘要</dt>
          <dd>{context.observation_digest}</dd>
          <dt>原件</dt>
          <dd>本次摘要读取未重新校验原字节</dd>
        </dl>
        <pre>
          {JSON.stringify(
            {
              selection: selected,
              current_observation: context.current_observation,
              limitations: context.limitations,
            },
            null,
            2,
          )}
        </pre>
      </details>
    </section>
  );
}
