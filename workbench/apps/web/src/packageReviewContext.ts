import type { PackageReviewExecutionContext } from "./contracts";

export function matchesExecutionContext(
  value: PackageReviewExecutionContext | undefined,
  inputDigest: string,
  checkedAt: string,
): boolean {
  if (!value) return false;
  return (
    value.version === "package-review-context/1" &&
    value.kind === "candidate" &&
    value.input_digest === inputDigest &&
    value.purpose === "prebid_compliance" &&
    value.executor_available === false &&
    value.formal_scoring_eligible === false &&
    typeof value.as_of === "string" &&
    Number.isFinite(Date.parse(value.as_of)) &&
    Date.parse(value.as_of) === Date.parse(checkedAt) &&
    [
      value.semantic_digest,
      value.snapshot_digest,
      value.method_digest,
      value.policy_digest,
      value.facts_digest,
      value.sources_digest,
    ].every(
      (digest) => typeof digest === "string" && /^[a-f0-9]{64}$/.test(digest),
    ) &&
    Number.isSafeInteger(value.fact_count) &&
    value.fact_count >= 0 &&
    Number.isSafeInteger(value.confirmed_fact_count) &&
    value.confirmed_fact_count >= 0 &&
    value.confirmed_fact_count <= value.fact_count &&
    (value.fact_set_id === null ||
      (typeof value.fact_set_id === "string" &&
        /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(
          value.fact_set_id,
        ))) &&
    (value.fact_count === 0
      ? value.facts_binding === "empty"
      : value.facts_binding === "unproven" && value.fact_set_id !== null)
  );
}
