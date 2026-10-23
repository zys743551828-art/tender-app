import { useCallback, useEffect, useRef, useState } from "react";
import "./packageReview.css";
import { api } from "./api";
import { ErrorNotice, Loading } from "./components";
import type {
  PackageExecutionInputView,
  PackageReviewFrozenInputView,
  PackageReviewRunView,
} from "./contracts";
import type { DependencyProps } from "./inputDependencyProtocol";
import { freezePath, validateFrozenInput } from "./packageFrozenInput";
import { executionPath } from "./executionInputRecovery";
import { validateExecutionInput } from "./executionInputValidation";
import { validatePackageReviewRun } from "./packageReviewProtocol";
import type { WorkContextRunSelection } from "./workContextProtocol";
import PackageReviewReport from "./PackageReviewReport";
import PackageReviewInputDetails from "./PackageReviewInputDetails";

export function WorkContextReviewDetails(p: {
  selection: WorkContextRunSelection;
  memberId: string;
  onClose: () => void;
}) {
  return (
    <ReviewDetails
      key={`${p.memberId}:${JSON.stringify(p.selection)}`}
      {...p}
    />
  );
}
function ReviewDetails({
  selection,
  memberId,
  onClose,
}: {
  selection: WorkContextRunSelection;
  memberId: string;
  onClose: () => void;
}) {
  const [read, setRead] = useState<{
      props: DependencyProps;
      run: PackageReviewRunView;
    } | null>(null),
    [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false);
  const active = useRef(false),
    running = useRef(false),
    ticket = useRef(0);
  const load = useCallback(async () => {
    if (running.current || !active.current) return;
    running.current = true;
    const request = ++ticket.current;
    setBusy(true);
    setError(null);
    try {
      const scope = {
        memberId,
        bidId: selection.bid_id,
        packageId: selection.package_id,
        revisionId: selection.revision_id,
        inventoryId: selection.inventory_id,
      };
      const base = `${executionPath(scope, selection.frozen_input_id)}/${selection.execution_input_id}`;
      const [frozenReply, preparedReply, runReply] = await Promise.all([
        api<PackageReviewFrozenInputView>(
          `${freezePath(scope)}/${selection.frozen_input_id}`,
        ),
        api<PackageExecutionInputView>(base),
        api<unknown>(`${base}/review-runs/${selection.run_id}`),
      ]);
      const frozen = frozenReply.data,
        prepared = preparedReply.data;
      await validateFrozenInput(frozen, scope, selection.frozen_input_id);
      await validateExecutionInput(
        prepared,
        scope,
        frozen,
        selection.execution_input_id,
      );
      if (
        frozen.digest !== selection.frozen_input_digest ||
        prepared.digest !== selection.execution_input_digest
      )
        throw new Error("所选核查的原冻结输入与执行准备摘要不一致。");
      const props = { scope, frozen, prepared };
      const run = await validatePackageReviewRun(
        runReply.data,
        props,
        selection.run_id,
      );
      if (
        run.input_digest !== selection.input_digest ||
        run.method_digest !== selection.method_digest ||
        run.dependency_plan_id !== selection.dependency_plan_id ||
        run.dependency_plan_digest !== selection.dependency_plan_digest ||
        (run.result?.digest ?? null) !== selection.result_digest
      )
        throw new Error(
          "此核查的结果或固定输入与原选择不同，请重新读取阶段目录后明确选择。",
        );
      if (active.current && request === ticket.current) setRead({ props, run });
    } catch (failure) {
      if (active.current && request === ticket.current) setError(failure);
    } finally {
      if (active.current && request === ticket.current) {
        running.current = false;
        setBusy(false);
      }
    }
  }, [memberId, selection]);
  useEffect(() => {
    active.current = true;
    void load();
    const requests = ticket;
    return () => {
      active.current = false;
      running.current = false;
      requests.current++;
    };
  }, [load]);
  return (
    <section className="work-context-original" aria-label="所选核查原记录">
      <div className="section-heading">
        <h3>所选核查原记录</h3>
        <button type="button" className="button secondary" onClick={onClose}>
          收起原核查
        </button>
      </div>
      {busy && <Loading text="正在核对原冻结输入、执行准备与核查结果…" />}
      {error != null && (
        <ErrorNotice error={error} onRetry={() => void load()} />
      )}
      {error != null && read && (
        <p className="notice warning">
          本次未能更新，下面保留上次核验的历史记录。
        </p>
      )}
      {read && (
        <>
          <p>
            原核查创建于{" "}
            <time dateTime={read.run.created_at}>{read.run.created_at}</time>。
          </p>
          <PackageReviewInputDetails {...read.props} run={read.run} />
          {read.run.result ? (
            <PackageReviewReport run={read.run} />
          ) : (
            <p className="notice neutral">
              本次选择未包含核查结果。处理状态：
              {read.run.operation.state === "failed"
                ? "失败"
                : read.run.operation.state === "cancelled"
                  ? "已取消"
                  : "尚未完成"}
              。
            </p>
          )}
          <button
            type="button"
            className="text-button"
            disabled={busy}
            onClick={() => void load()}
          >
            重读同一原记录
          </button>
        </>
      )}
    </section>
  );
}
