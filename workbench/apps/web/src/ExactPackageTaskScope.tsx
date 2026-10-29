import type { PackageReviewSelection } from "./contracts";
import {
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
import { packageLocation } from "./packageNavigation";
import "./ExactPackageTask.css";

/** Display the selected immutable scope; it never resolves a current input. */
export function ExactPackageTaskScope({
  bidId,
  selection,
}: {
  bidId: string;
  selection: PackageReviewSelection;
}) {
  if (
    !recordObject(selection) ||
    !executionId(bidId) ||
    ![
      selection.package_id,
      selection.revision_id,
      selection.inventory_id,
      selection.frozen_input_id,
      selection.execution_input_id,
      selection.dependency_plan_id,
    ].every(executionId) ||
    ![
      selection.frozen_input_digest,
      selection.execution_input_digest,
      selection.dependency_plan_digest,
      selection.method_digest,
    ].every(executionSha)
  )
    return (
      <p className="notice error">精确整包身份或摘要不完整，未链接其他输入。</p>
    );
  return (
    <section className="exact-package-task-scope" aria-label="任务固定整包来源">
      <h4>固定的整包来源</h4>
      <p className="small-note">
        保留选择时的包修订与核查范围，不会自动使用最新资料。
      </p>
      <a
        className="text-link"
        href={packageLocation(bidId, {
          packageId: selection.package_id,
          revisionId: selection.revision_id,
          inventoryId: selection.inventory_id,
        })}
      >
        查看这份包修订与清单
      </a>
      <details className="identity-details">
        <summary>核对完整来源身份与摘要</summary>
        <dl>
          <div>
            <dt>投标包</dt>
            <dd>{selection.package_id}</dd>
          </div>
          <div>
            <dt>不可变包修订</dt>
            <dd>{selection.revision_id}</dd>
          </div>
          <div>
            <dt>需求清单</dt>
            <dd>{selection.inventory_id}</dd>
          </div>
          <div>
            <dt>冻结输入</dt>
            <dd>{selection.frozen_input_id}</dd>
          </div>
          <div>
            <dt>执行准备</dt>
            <dd>{selection.execution_input_id}</dd>
          </div>
          <div>
            <dt>依赖计划</dt>
            <dd>{selection.dependency_plan_id}</dd>
          </div>
        </dl>
        <p>冻结输入：{selection.frozen_input_digest}</p>
        <p>执行准备：{selection.execution_input_digest}</p>
        <p>依赖计划：{selection.dependency_plan_digest}</p>
        <p>核查方法：{selection.method_digest}</p>
      </details>
    </section>
  );
}
