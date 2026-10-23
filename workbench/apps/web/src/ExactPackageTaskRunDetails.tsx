import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { ErrorNotice } from "./components";
import type {
  PackageExecutionInputView,
  PackageReviewFrozenInputView,
  PackageReviewRunView,
} from "./contracts";
import type { DependencyProps } from "./inputDependencyProtocol";
import { executionPath } from "./executionInputRecovery";
import { validateExecutionInput } from "./executionInputValidation";
import { freezePath, validateFrozenInput } from "./packageFrozenInput";
import { validatePackageReviewRun } from "./packageReviewProtocol";
import PackageReviewProgress from "./PackageReviewProgress";
import type { TaskPackageRunView } from "./taskPackageProtocol";

/** Load the original native run, not an input selected from the current project head. */
export default function ExactPackageTaskRunDetails({
  memberId,
  task,
  onClose,
}: {
  memberId: string;
  task: TaskPackageRunView;
  onClose: () => void;
}) {
  const [openedTask] = useState(task);
  const [ready, setReady] = useState<{
    props: DependencyProps;
    run: PackageReviewRunView;
  } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  const updateRun = useCallback(
    (run: PackageReviewRunView) =>
      setReady((value) => (value ? { ...value, run } : value)),
    [],
  );
  useEffect(() => {
    let active = true;
    setReady(null);
    setError(null);
    void (async () => {
      try {
        const selection = openedTask.frozen_manifest.context.selection;
        const native = openedTask.frozen_manifest.package_review;
        const scope = {
          memberId,
          bidId: openedTask.bid_id,
          packageId: selection.package_id,
          revisionId: selection.revision_id,
          inventoryId: selection.inventory_id,
        };
        const [frozenReply, preparedReply, nativeReply] = await Promise.all([
          api<PackageReviewFrozenInputView>(
            `${freezePath(scope)}/${selection.frozen_input_id}`,
          ),
          api<PackageExecutionInputView>(
            `${executionPath(scope, selection.frozen_input_id)}/${selection.execution_input_id}`,
          ),
          api<unknown>(native.run_ref.slice("/api/v1".length)),
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
          throw new Error("任务绑定的原输入摘要不一致，未打开其他核查。");
        const props = { scope, frozen, prepared };
        const run = await validatePackageReviewRun(
          nativeReply.data,
          props,
          native.run_id,
        );
        if (
          run.operation.id !== native.operation_id ||
          run.input_digest !== native.input_digest ||
          run.method_digest !== selection.method_digest ||
          run.dependency_plan_id !== selection.dependency_plan_id ||
          run.dependency_plan_digest !== selection.dependency_plan_digest ||
          (openedTask.result &&
            run.result?.digest !== openedTask.result.result_digest)
        )
          throw new Error(
            "原生核查的操作、计划或结果摘要与任务不符，未采用其他结果。",
          );
        if (active) setReady({ props, run });
      } catch (failure) {
        if (active) setError(failure);
      }
    })();
    return () => {
      active = false;
    };
  }, [openedTask, memberId, attempt]);
  return (
    <section
      className="package-review__original exact-package-task-result"
      aria-label="任务绑定的原生整包核查"
    >
      <div className="section-title">
        <h4>任务绑定的原生整包核查</h4>
        <button type="button" className="text-button" onClick={onClose}>
          收起原生核查详情
        </button>
      </div>
      <p className="small-note">
        按这次任务的原冻结输入、执行准备和原生运行读取；人工核对状态可以在任务受理之后继续更新。
      </p>
      {!ready && !error && (
        <p role="status">正在核对原冻结输入与完整核查记录…</p>
      )}
      <ErrorNotice
        error={error}
        onRetry={() => setAttempt((value) => value + 1)}
      />
      {ready && (
        <PackageReviewProgress
          {...ready.props}
          run={ready.run}
          onChange={updateRun}
          showComparison={false}
        />
      )}
    </section>
  );
}
