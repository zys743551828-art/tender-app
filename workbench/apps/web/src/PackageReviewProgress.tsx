import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { api } from "./api";
import type { PackageReviewRunView } from "./contracts";
import { ErrorNotice } from "./components";
import type { DependencyProps } from "./inputDependencyProtocol";
import {
  packageReviewEnded,
  packageReviewPath,
  validatePackageReviewRun,
} from "./packageReviewProtocol";
import PackageReviewCancel from "./PackageReviewCancel";
import PackageReviewHumanDecisions from "./PackageReviewHumanDecisions";
import PackageReviewInputDetails from "./PackageReviewInputDetails";

const PackageReviewComparisonWorkspace = lazy(
  () => import("./PackageReviewComparisonWorkspace"),
);
const PackageReviewReportExports = lazy(
  () => import("./PackageReviewReportExports"),
);

type Props = DependencyProps & {
  run: PackageReviewRunView;
  onChange: (run: PackageReviewRunView) => void;
  onRequestRerun?: () => void;
  showComparison?: boolean;
  focusRequirementId?: string;
};
const states = {
  queued: "已受理，等待核查",
  running: "正在核查已声明范围",
  cancel_requested: "已请求取消，等待最终状态",
  succeeded: "核查执行已结束",
  failed: "核查执行失败",
  cancelled: "本次核查已取消",
};
function sameRun(before: PackageReviewRunView, after: PackageReviewRunView) {
  const fields = [
    "id",
    "actor_id",
    "created_at",
    "frozen_input_id",
    "frozen_input_digest",
    "execution_input_id",
    "execution_input_digest",
    "execution_digest",
    "dependency_plan_id",
    "dependency_plan_digest",
    "input_digest",
    "method_digest",
  ] as const;
  return (
    fields.every((key) => before[key] === after[key]) &&
    before.operation.id === after.operation.id &&
    before.operation.created_at === after.operation.created_at
  );
}
export default function PackageReviewProgress({
  scope,
  frozen,
  prepared,
  run,
  onChange,
  onRequestRerun,
  showComparison = true,
  focusRequirementId,
}: Props) {
  const [reading, setReading] = useState(false),
    [error, setError] = useState<unknown>(null);
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const active = useRef(false),
    readingRef = useRef(false),
    ticket = useRef(0),
    current = useRef(run),
    initial = useRef(run);
  current.current = run;
  const runId = run.id,
    path = `${packageReviewPath({ scope, frozen, prepared })}/${runId}`;
  const read = useCallback(
    async (force = false) => {
      if (!active.current || (readingRef.current && !force)) return;
      const request = ++ticket.current;
      readingRef.current = true;
      setReading(true);
      setError(null);
      try {
        const { data } = await api<unknown>(path);
        const received = await validatePackageReviewRun(
          data,
          { scope, frozen, prepared },
          runId,
        );
        if (!sameRun(initial.current, received))
          throw new Error("本次核查的不可变身份发生变化，未采用其他任务状态。");
        if (!active.current || ticket.current !== request) return;
        if (
          (packageReviewEnded(current.current.operation.state) &&
            received.operation.state !== current.current.operation.state) ||
          (current.current.result &&
            received.result?.digest !== current.current.result.digest)
        )
          throw new Error(
            "本次核查已确认的终态或结果发生变化，保留原核查记录，请重读核对。",
          );
        current.current = received;
        onChange(received);
        setCheckedAt(new Date().toLocaleTimeString());
      } catch (failure) {
        if (active.current && ticket.current === request) setError(failure);
      } finally {
        if (active.current && ticket.current === request) {
          readingRef.current = false;
          setReading(false);
        }
      }
    },
    [path, scope, frozen, prepared, runId, onChange],
  );
  const reload = useCallback(() => read(true), [read]);
  useEffect(() => {
    active.current = true;
    const requests = ticket;
    void read(true);
    const timer = window.setInterval(() => {
      if (!packageReviewEnded(current.current.operation.state)) void read();
    }, 3000);
    return () => {
      active.current = false;
      requests.current++;
      window.clearInterval(timer);
    };
  }, [read]);
  return (
    <section className="package-review__progress" aria-label="本次整包范围核查">
      <div className="package-review__heading">
        <div>
          <h4>本次整包范围核查</h4>
          <p role="status">{states[run.operation.state]}</p>
        </div>
        <button
          type="button"
          className="button secondary"
          disabled={reading}
          onClick={() => void reload()}
        >
          {reading ? "正在重读…" : "刷新本次核查状态"}
        </button>
      </div>
      {checkedAt && <p className="muted">最近成功读取：{checkedAt}</p>}
      {!packageReviewEnded(run.operation.state) && (
        <p>
          任务在服务端执行，关闭页面不会自动取消。处理状态每 3
          秒重读一次，结果只在验证其输入身份后显示。
        </p>
      )}
      {run.operation.state === "succeeded" && !run.result && (
        <p className="package-review__notice">
          执行已结束，范围核查结果尚未取回。请刷新本次核查状态；当前不能据此判断任何要求已通过。
        </p>
      )}
      {run.operation.state === "failed" && (
        <p className="package-review__notice">
          本次未取得可用核查结果。请处理失败原因，再通过“准备复检”生成新的执行准备输入。
          {run.operation.error_code && (
            <>
              错误编号：<code>{run.operation.error_code}</code>。
            </>
          )}
        </p>
      )}
      {run.operation.state === "cancelled" && (
        <p>本次任务已停止，未形成整包通过结论。已有记录保留在历史中。</p>
      )}
      {error != null && (
        <ErrorNotice error={error} onRetry={() => void reload()} />
      )}
      <details>
        <summary>本次核查的输入与执行身份</summary>
        <dl className="package-review__identity">
          <dt>核查编号</dt>
          <dd>
            <code>{run.id}</code>
          </dd>
          <dt>执行准备编号</dt>
          <dd>
            <code>{run.execution_input_id}</code>
          </dd>
          <dt>依赖计划编号</dt>
          <dd>
            <code>{run.dependency_plan_id}</code>
          </dd>
          <dt>输入摘要</dt>
          <dd>
            <code>{run.input_digest}</code>
          </dd>
          <dt>方法摘要</dt>
          <dd>
            <code>{run.method_digest}</code>
          </dd>
          <dt>任务编号</dt>
          <dd>
            <code>{run.operation.id}</code>
          </dd>
        </dl>
      </details>
      <PackageReviewInputDetails
        scope={scope}
        frozen={frozen}
        prepared={prepared}
        run={run}
      />
      <PackageReviewCancel
        scope={scope}
        frozen={frozen}
        prepared={prepared}
        run={run}
        onReload={reload}
      />
      {run.result && (
        <PackageReviewHumanDecisions
          scope={scope}
          frozen={frozen}
          prepared={prepared}
          run={run}
          focusRequirementId={focusRequirementId}
        />
      )}
      {run.result && showComparison && (
        <Suspense fallback={<p role="status">正在打开两轮对比入口…</p>}>
          <PackageReviewComparisonWorkspace
            memberId={scope.memberId}
            bidId={scope.bidId}
            currentRun={run}
          />
        </Suspense>
      )}
      {run.result && (
        <Suspense fallback={<p role="status">正在打开报告副本入口…</p>}>
          <PackageReviewReportExports
            scope={scope}
            frozen={frozen}
            prepared={prepared}
            run={run}
          />
        </Suspense>
      )}
      {packageReviewEnded(run.operation.state) && onRequestRerun && (
        <div className="package-review__rerun">
          <p>
            修订资料或确认新的事实后，需要重新核对输入并生成带复检理由的新准备记录。本次结果继续保留，不会因编辑自动消除风险。
          </p>
          <button
            type="button"
            className="button primary"
            onClick={onRequestRerun}
          >
            准备复检
          </button>
        </div>
      )}
    </section>
  );
}
