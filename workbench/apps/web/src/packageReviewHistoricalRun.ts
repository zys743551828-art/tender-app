import type {
  PackageReviewComparisonRun,
  PackageReviewRunSummary,
  PackageReviewRunView,
} from "./contracts";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
import { packageReviewStates } from "./packageReviewProtocol";

const identityFields = [
  "id",
  "actor_id",
  "created_at",
  "scope",
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
export type PackageReviewHistoricalReference = Pick<
  PackageReviewRunView,
  (typeof identityFields)[number]
> & { operation_id?: string; result: PackageReviewRunSummary["result"] };
const time = (v: unknown) =>
  typeof v === "string" &&
  /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z$/.test(v) &&
  Number.isFinite(Date.parse(v)) &&
  new Date(v).toISOString().slice(0, 19) === v.slice(0, 19);
const positive = (v: unknown, max: number): v is number =>
  Number.isSafeInteger(v) && Number(v) > 0 && Number(v) <= max;
function identity(
  value:
    | PackageReviewRunView
    | PackageReviewRunSummary
    | PackageReviewComparisonRun,
) {
  return Object.fromEntries(
    identityFields.map((key) => [key, value[key]]),
  ) as Pick<PackageReviewRunView, (typeof identityFields)[number]>;
}
/** This reference only authorizes a historical GET; the original frozen/prepared/run packets are still verified before display. */
export function packageReviewHistoricalSummary(
  value: unknown,
  bidId: string,
): PackageReviewHistoricalReference | null {
  if (
    !recordObject(value) ||
    !exactKeys(value, ["kind", ...identityFields, "operation", "result"]) ||
    value.kind !== "package_review_run" ||
    ![
      value.id,
      value.actor_id,
      value.frozen_input_id,
      value.execution_input_id,
      value.dependency_plan_id,
    ].every(executionId) ||
    !time(value.created_at) ||
    !recordObject(value.scope) ||
    !exactKeys(value.scope, [
      "bid_id",
      "package_id",
      "revision_id",
      "inventory_id",
    ]) ||
    value.scope.bid_id !== bidId ||
    !Object.values(value.scope).every(executionId) ||
    ![
      value.frozen_input_digest,
      value.execution_input_digest,
      value.execution_digest,
      value.dependency_plan_digest,
      value.input_digest,
      value.method_digest,
    ].every(executionSha) ||
    !recordObject(value.operation) ||
    !exactKeys(value.operation, [
      "id",
      "kind",
      "state",
      "input_digest",
      "handler_version",
      "error_code",
      "created_at",
      "finished_at",
    ])
  )
    return null;
  const op = value.operation;
  if (
    !executionId(op.id) ||
    op.kind !== "package-scope-review" ||
    !packageReviewStates.includes(
      op.state as (typeof packageReviewStates)[number],
    ) ||
    op.input_digest !== value.input_digest ||
    op.handler_version !== "package-review/1" ||
    !time(op.created_at) ||
    !(op.finished_at === null || time(op.finished_at)) ||
    !(
      op.error_code === null ||
      (typeof op.error_code === "string" &&
        !!op.error_code.trim() &&
        op.error_code.length <= 200)
    ) ||
    (op.state === "succeeded") !== (value.result !== null)
  )
    return null;
  const result = value.result;
  if (
    result !== null &&
    (!recordObject(result) ||
      !exactKeys(result, [
        "digest",
        "requirement_count",
        "matrix_coverage",
        "overall_coverage",
      ]) ||
      !executionSha(result.digest) ||
      !positive(result.requirement_count, 400) ||
      !["partial", "complete"].includes(String(result.matrix_coverage)) ||
      result.overall_coverage !== "partial")
  )
    return null;
  const summary = value as unknown as PackageReviewRunSummary;
  return {
    ...identity(summary),
    operation_id: summary.operation.id,
    result: summary.result,
  };
}
export function packageReviewHistoricalComparison(
  value: PackageReviewComparisonRun,
): PackageReviewHistoricalReference {
  return {
    ...identity(value),
    result: {
      digest: value.result_digest,
      requirement_count: value.requirement_count,
      matrix_coverage: value.matrix_coverage,
      overall_coverage: value.overall_coverage,
    },
  };
}
/** The saved native packet supplies a reference; opening still verifies the original inputs. */
export function packageReviewHistoricalOriginal(
  run: PackageReviewRunView,
): PackageReviewHistoricalReference {
  return {
    ...identity(run),
    operation_id: run.operation.id,
    result: run.result
      ? {
          digest: run.result.digest,
          requirement_count: run.result.manifest.requirement_count,
          matrix_coverage: run.result.manifest.matrix_coverage,
          overall_coverage: run.result.manifest.overall_coverage,
        }
      : null,
  };
}
export function matchesPackageReviewHistoricalReference(
  run: PackageReviewRunView,
  reference: PackageReviewHistoricalReference,
) {
  return (
    identityFields.every((key) =>
      key === "scope"
        ? Object.keys(reference.scope).every(
            (field) =>
              run.scope[field as keyof typeof run.scope] ===
              reference.scope[field as keyof typeof reference.scope],
          )
        : run[key] === reference[key],
    ) &&
    (!reference.operation_id || run.operation.id === reference.operation_id) &&
    (reference.result === null ||
      (!!run.result &&
        run.result.digest === reference.result.digest &&
        run.result.manifest.requirement_count ===
          reference.result.requirement_count &&
        run.result.manifest.matrix_coverage ===
          reference.result.matrix_coverage &&
        run.result.manifest.overall_coverage ===
          reference.result.overall_coverage))
  );
}
