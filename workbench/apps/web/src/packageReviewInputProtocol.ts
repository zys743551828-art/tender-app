import type {
  PackageReviewRunInputView,
  PackageReviewRunView,
} from "./contracts";
import type { DependencyProps } from "./inputDependencyProtocol";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
import { frozenManifestDigest } from "./packageFrozenInput";
import { packageReviewScope } from "./packageReviewProtocol";

const same = (value: unknown, expected: Record<string, unknown>) =>
  recordObject(value) &&
  exactKeys(value, Object.keys(expected)) &&
  Object.entries(expected).every(([key, item]) => value[key] === item);

/** The historical input is readable independently of current admission or configuration. */
export async function validatePackageReviewInputView(
  value: unknown,
  p: DependencyProps,
  run: PackageReviewRunView,
): Promise<PackageReviewRunInputView> {
  const fail = () => {
    throw new Error(
      "执行依据的原输入、计划、事实声明或方法摘要不符，未采用其他记录。",
    );
  };
  if (
    !recordObject(value) ||
    !exactKeys(value, ["manifest", "digest"]) ||
    value.digest !== run.input_digest ||
    !executionSha(value.digest) ||
    !recordObject(value.manifest)
  )
    return fail();
  const m = value.manifest;
  if (
    !exactKeys(m, [
      "version",
      "purpose",
      "scope",
      "frozen_input",
      "execution_input",
      "dependency_plan",
      "usage_digest",
      "selected_facts_digest",
      "fact_admission",
      "inventory_proof_digest",
      "executor_method",
      "model_input_digest",
      "limitations",
    ]) ||
    m.version !== "package-scope-review-input/1" ||
    m.purpose !== "prebid_compliance" ||
    !same(m.scope, packageReviewScope(p)) ||
    !same(m.scope, run.scope) ||
    !same(m.frozen_input, {
      id: run.frozen_input_id,
      digest: run.frozen_input_digest,
      input_digest: p.frozen.manifest.input_digest,
      evidence_digest: p.frozen.manifest.evidence_digest,
    }) ||
    run.frozen_input_id !== p.frozen.manifest.id ||
    run.frozen_input_digest !== p.frozen.digest ||
    !recordObject(m.execution_input) ||
    !exactKeys(m.execution_input, ["id", "digest", "identity"]) ||
    m.execution_input.id !== run.execution_input_id ||
    m.execution_input.digest !== run.execution_input_digest ||
    run.execution_input_id !== p.prepared.manifest.id ||
    run.execution_input_digest !== p.prepared.digest ||
    !recordObject(m.execution_input.identity) ||
    !same(m.dependency_plan, {
      id: run.dependency_plan_id,
      digest: run.dependency_plan_digest,
    }) ||
    ![
      m.usage_digest,
      m.selected_facts_digest,
      m.inventory_proof_digest,
      m.model_input_digest,
    ].every(executionSha) ||
    !Array.isArray(m.limitations) ||
    m.limitations.length !== 1 ||
    m.limitations[0] !== "INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED"
  )
    return fail();
  if (
    (await frozenManifestDigest(m.execution_input.identity)) !==
      (await frozenManifestDigest(p.prepared.manifest.identity)) ||
    m.execution_input.identity.execution_digest !== run.execution_digest
  )
    return fail();
  const admission = m.fact_admission,
    method = m.executor_method;
  if (
    !recordObject(admission) ||
    !exactKeys(admission, [
      "content_digest",
      "proofs_digest",
      "policy_digest",
      "fact_declarations",
    ]) ||
    ![
      admission.content_digest,
      admission.proofs_digest,
      admission.policy_digest,
    ].every(executionSha) ||
    !Array.isArray(admission.fact_declarations) ||
    !admission.fact_declarations.every(
      (entry) =>
        recordObject(entry) &&
        exactKeys(entry, ["fact_id", "declaration_id", "declaration_digest"]) &&
        executionId(entry.fact_id) &&
        executionId(entry.declaration_id) &&
        executionSha(entry.declaration_digest),
    ) ||
    new Set(admission.fact_declarations.map((entry) => entry.fact_id)).size !==
      admission.fact_declarations.length ||
    !recordObject(method) ||
    !exactKeys(method, ["profile", "digest"]) ||
    method.digest !== run.method_digest ||
    !recordObject(method.profile)
  )
    return fail();
  const profile = method.profile;
  const fixed = {
    engine: "package-review/1",
    purpose: "prebid_compliance",
    assessment: "declared_requirement_response",
    input_scope: "all_frozen_target_and_authority_members",
    model_json_encoding: "finite-json-numbers/1",
    batch_rule_limit: 100,
    batch_limit: 4,
    output_tokens_per_batch: 8192,
    input_character_limit: 240000,
    semantic_quality: "not_measured",
    formal_scoring_eligible: false,
    submission_eligible: false,
  };
  if (
    !exactKeys(profile, [
      ...Object.keys(fixed),
      "model",
      "endpoint",
      "source_digest",
    ]) ||
    Object.entries(fixed).some(
      ([key, expected]) => profile[key] !== expected,
    ) ||
    !["deepseek-flash", "deepseek-v4-pro"].includes(String(profile.model)) ||
    !["https://api.deepseek.com", "https://api.deepseek.com/v1"].includes(
      String(profile.endpoint),
    ) ||
    !executionSha(profile.source_digest) ||
    (await frozenManifestDigest(profile)) !== method.digest ||
    (await frozenManifestDigest(m)) !== value.digest
  )
    return fail();
  return value as unknown as PackageReviewRunInputView;
}
