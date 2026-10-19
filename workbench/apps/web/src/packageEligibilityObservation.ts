import type {
  PackageReviewEligibilityObservation,
  PackageReviewFrozenInputView,
} from "./contracts";
import { matchesExecutionContext } from "./packageReviewContext";
import { reviewInputBlockers } from "./packageReviewBlockers";

export const eligibilityMessages: Record<
  PackageReviewEligibilityObservation["blockers"][number],
  string
> = {
  ...reviewInputBlockers,
  PACKAGE_REVIEW_METHOD_CHANGED:
    "当前方法或模型配置已变化，原冻结记录保持不变。",
  PACKAGE_REVIEW_POLICY_CHANGED: "当前执行政策已变化，需重新核对输入。",
  PACKAGE_REVIEW_FACTS_CHANGED: "当前事实集、人工决定或依据已变化。",
  PACKAGE_REVIEW_FACTS_UNPROVEN:
    "事实输入资格尚未完成核验，人工确认数量不代表资格通过。",
};

export function matchesEligibility(
  value: PackageReviewEligibilityObservation,
  frozen: PackageReviewFrozenInputView,
): boolean {
  return (
    !!value &&
    value.kind === "eligibility_observation" &&
    value.frozen_input_id === frozen.manifest.id &&
    value.frozen_digest === frozen.digest &&
    value.input_digest === frozen.manifest.input_digest &&
    matchesExecutionContext(
      value.current_context,
      value.input_digest,
      value.checked_at,
    ) &&
    value.current_context.as_of === value.checked_at &&
    ["matched", "mismatch"].includes(value.parse_evidence_status) &&
    value.original_verification === "not_performed" &&
    value.review_ready === false &&
    value.launch_available === false &&
    value.publication_authorized === false &&
    Array.isArray(value.blockers) &&
    value.blockers.includes("PACKAGE_REVIEW_EXECUTOR_NOT_READY") &&
    value.blockers.every((code) =>
      Object.prototype.hasOwnProperty.call(eligibilityMessages, code),
    ) &&
    new Set(value.blockers).size === value.blockers.length &&
    (value.parse_evidence_status === "mismatch") ===
      value.blockers.includes("PACKAGE_REVIEW_EVIDENCE_CHANGED") &&
    (
      [
        ["method_digest", "PACKAGE_REVIEW_METHOD_CHANGED"],
        ["policy_digest", "PACKAGE_REVIEW_POLICY_CHANGED"],
        ["facts_digest", "PACKAGE_REVIEW_FACTS_CHANGED"],
      ] as const
    ).every(
      ([field, code]) =>
        (value.current_context[field] !==
          frozen.manifest.execution_context[field]) ===
        value.blockers.includes(code),
    ) &&
    (
      [
        "method_digest",
        "policy_digest",
        "facts_digest",
        "sources_digest",
      ] as const
    ).some(
      (field) =>
        value.current_context[field] !==
        frozen.manifest.execution_context[field],
    ) ===
      (value.current_context.semantic_digest !==
        frozen.manifest.execution_context.semantic_digest) &&
    (value.current_context.facts_digest !==
      frozen.manifest.execution_context.facts_digest ||
      (
        [
          "fact_count",
          "confirmed_fact_count",
          "fact_set_id",
          "facts_binding",
        ] as const
      ).every(
        (field) =>
          value.current_context[field] ===
          frozen.manifest.execution_context[field],
      ))
  );
}
