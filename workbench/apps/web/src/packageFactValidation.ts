import type {
  PackageExecutionFactCheck,
  PackageExecutionInputView,
} from "./contracts";
import type { FreezeScope } from "./packageFrozenInput";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
export const factCheckMessages: Record<
  PackageExecutionFactCheck["fact_checks"][number]["blockers"][number],
  string
> = {
  FACT_DECISION_UNCONFIRMED: "当前事实尚无确认决定。",
  FACT_DECISION_BINDING_UNPROVEN: "当前决定与事实的直接或沿用身份尚未证明。",
  FACT_DECISION_BASIS_UNPROVEN: "确认决定缺少与当前事实一致的完整依据。",
  FACT_EVIDENCE_OUTSIDE_FROZEN_INPUT: "事实依据未绑定到选定包的精确冻结解析。",
  FACT_EVIDENCE_QUALITY_UNPROVEN: "事实原页或解析存在缺口，尚不能核实依据。",
  FACT_SOURCE_BINDING_UNPROVEN: "当前来源与确认时的引用或来源链不一致。",
  FACT_SOURCE_NOT_EFFECTIVE: "事实来源尚未生效、已撤回或效力未证明。",
  FACT_SCOPE_MAPPING_REQUIRED: "仍需明确绑定投标主体、标段和适用范围。",
};
export function matchesFactCheck(
  v: PackageExecutionFactCheck,
  scope: FreezeScope,
  frozenId: string,
  prepared: PackageExecutionInputView,
) {
  if (
    !recordObject(v) ||
    !exactKeys(v, [
      "kind",
      "bid_id",
      "package_id",
      "revision_id",
      "inventory_id",
      "frozen_input_id",
      "execution_input_id",
      "execution_input_digest",
      "prepared_context_digest",
      "observed_context_digest",
      "observed_facts_digest",
      "matches_prepared_context",
      "checked_at",
      "fact_count",
      "provenance_verified_count",
      "fact_checks",
      "blockers",
      "facts_qualified",
      "original_verification",
      "review_ready",
      "launch_available",
      "publication_authorized",
    ])
  )
    return false;
  if (
    v.kind !== "fact_validation_observation" ||
    v.bid_id !== scope.bidId ||
    v.package_id !== scope.packageId ||
    v.revision_id !== scope.revisionId ||
    v.inventory_id !== scope.inventoryId ||
    v.frozen_input_id !== frozenId ||
    v.execution_input_id !== prepared.manifest.id ||
    v.execution_input_digest !== prepared.digest ||
    v.prepared_context_digest !==
      prepared.manifest.identity.binding.context_digest ||
    !executionSha(v.observed_context_digest) ||
    !executionSha(v.observed_facts_digest) ||
    typeof v.matches_prepared_context !== "boolean" ||
    v.matches_prepared_context !==
      (v.observed_context_digest === v.prepared_context_digest) ||
    (v.matches_prepared_context &&
      (v.observed_facts_digest !==
        prepared.manifest.execution_context.facts_digest ||
        v.fact_count !== prepared.manifest.execution_context.fact_count ||
        v.provenance_verified_count >
          prepared.manifest.execution_context.confirmed_fact_count)) ||
    typeof v.checked_at !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/.test(
      v.checked_at,
    ) ||
    !Number.isFinite(Date.parse(v.checked_at)) ||
    new Date(v.checked_at).toISOString().slice(0, 19) !==
      v.checked_at.slice(0, 19) ||
    v.facts_qualified !== false ||
    v.original_verification !== "not_performed" ||
    v.review_ready !== false ||
    v.launch_available !== false ||
    v.publication_authorized !== false ||
    !Array.isArray(v.fact_checks) ||
    !Number.isSafeInteger(v.fact_count) ||
    v.fact_count !== v.fact_checks.length ||
    !Number.isSafeInteger(v.provenance_verified_count) ||
    v.provenance_verified_count < 0 ||
    v.provenance_verified_count !==
      v.fact_checks.filter((x) => x?.provenance_status === "verified").length ||
    !Array.isArray(v.blockers) ||
    JSON.stringify(v.blockers) !==
      JSON.stringify(v.fact_count ? [] : ["FACT_SET_EMPTY"])
  )
    return false;
  return (
    new Set(v.fact_checks.map((x) => x?.fact_id)).size === v.fact_count &&
    v.fact_checks.every(
      (x) =>
        recordObject(x) &&
        exactKeys(x, [
          "fact_id",
          "provenance_status",
          "scope_binding",
          "facts_qualified",
          "blockers",
        ]) &&
        executionId(x.fact_id) &&
        ["verified", "unproven"].includes(x.provenance_status) &&
        x.scope_binding === "unproven" &&
        x.facts_qualified === false &&
        Array.isArray(x.blockers) &&
        x.blockers.includes("FACT_SCOPE_MAPPING_REQUIRED") &&
        new Set(x.blockers).size === x.blockers.length &&
        x.blockers.every((k) =>
          Object.prototype.hasOwnProperty.call(factCheckMessages, k),
        ) &&
        (x.provenance_status === "verified") === (x.blockers.length === 1),
    )
  );
}
