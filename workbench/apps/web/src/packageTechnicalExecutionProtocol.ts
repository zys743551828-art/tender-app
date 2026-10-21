import { ApiError } from "./api";
import type {
  PackageTechnicalScoringContext,
  PackageTechnicalScopeView,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  exactKeys,
  executionId as uuid,
  executionSha as sha,
  recordObject as object,
} from "./executionInputValidation";
import { validateTechnicalEligibility } from "./packageTechnicalEligibilityProtocol";
import {
  technicalSame as same,
  technicalText as text,
} from "./packageTechnicalScopeProtocol";

// A software protocol identity, never certification of provider weights or scores.
const method = {
  schema: "package-technical-judgment-method/1",
  provider: "deepseek",
  model_alias: "deepseek-flash",
  immutable_weights_verified: false,
  input_protocol: "package-technical-judgment-input/1",
  output_protocol: "package-technical-judgments/1",
  transport_protocol: "controlled-score-response/1",
  thinking: "disabled",
  temperature: 0,
  context_tokens: 1000000,
  max_output_tokens: 4096,
  maximum_prompt_characters: 262144,
  prompt_digest:
    "b0f0dbab7ff8604813d50c9caf838f66c7d810f254b47773c68f5dda39a92eea",
  output_schema_digest:
    "c41b1c0d5685dcddc247f1c0343046c6c52a749b039440f312fb62be7065829c",
  valid_replicates_required: 3,
  retry_is_replicate: false,
  complete_package_snapshot_required: true,
  visual_interpretation_supported: false,
  formal_scoring_eligible: false,
} as const;
export const packageTechnicalMethodDigest =
  "b278c1ce4785d51f483070c022d0041902115c0858eeed74b02d52c443089996";
const requiredProducerGaps = [
  "PACKAGE_SCORE_FORMAL_RANGE_AUTHORITY_MISSING",
  "PACKAGE_SCORE_VISUAL_AUTHORITY_MISSING",
  "PACKAGE_SCORE_PROVIDER_NOT_CONFIGURED",
  "PACKAGE_SCORE_METHOD_NOT_CERTIFIED",
];
type Gap = PackageTechnicalScoringContext["blockers"][number];

export type PackageTechnicalExecutionContext = {
  version: "package-technical-execution-context/1";
  qualification: PackageTechnicalScoringContext;
  producer: {
    software_foundation: "not_installed" | "installed";
    real_provider_configured: false;
    formal_input_authority_configured: false;
    mechanism_test_publicly_available: false;
  };
  method: typeof method & { digest: string };
  execution_enabled: false;
  blockers: Gap[];
};
export type PackageTechnicalExecutionRefusal = {
  scope_id: string;
  scope_digest: string;
  method_digest: string;
  blockers: Gap[];
  jobs_created: 0;
  model_requests: 0;
  requestId: string;
};

function invalid(): never {
  throw new Error(
    "执行检查回执与这份技术范围、方法或当前条件不一致，请重新读取后核对。",
  );
}

export async function validateTechnicalExecutionContext(
  value: unknown,
  tag: string | null,
  saved: PackageTechnicalScopeView,
  scaleId: string | null,
): Promise<PackageTechnicalExecutionContext> {
  if (
    !object(value) ||
    new TextEncoder().encode(JSON.stringify(value)).length > 32 * 1024 * 1024 ||
    !exactKeys(value, [
      "version",
      "qualification",
      "producer",
      "method",
      "execution_enabled",
      "blockers",
    ]) ||
    value.version !== "package-technical-execution-context/1" ||
    value.execution_enabled !== false ||
    !object(value.qualification) ||
    !object(value.producer) ||
    !exactKeys(value.producer, [
      "software_foundation",
      "real_provider_configured",
      "formal_input_authority_configured",
      "mechanism_test_publicly_available",
    ]) ||
    !["not_installed", "installed"].includes(
      String(value.producer.software_foundation),
    ) ||
    value.producer.real_provider_configured !== false ||
    value.producer.formal_input_authority_configured !== false ||
    value.producer.mechanism_test_publicly_available !== false ||
    !same(value.method, { ...method, digest: packageTechnicalMethodDigest }) ||
    (await jsonDigest(method)) !== packageTechnicalMethodDigest ||
    !Array.isArray(value.blockers) ||
    value.blockers.length > 20000 ||
    new Set(value.blockers.map((gap) => gap?.id)).size !== value.blockers.length
  )
    invalid();

  const blockers = value.blockers;
  const stableQualification = Object.fromEntries(
    Object.entries(value.qualification).filter(
      ([key]) => key !== "observed_at",
    ),
  );
  // The containing server ETag binds this nested object. A derived nested tag
  // lets the existing strict validator check it without inventing a receipt.
  const qualification = await validateTechnicalEligibility(
    value.qualification,
    `"package-technical-eligibility:${saved.manifest.id}:${await jsonDigest(stableQualification)}"`,
    saved,
    { purpose: "current_prebid", scaleId },
  );
  if (qualification.purpose !== "current_prebid") invalid();
  for (const gap of blockers) {
    if (
      !object(gap) ||
      !exactKeys(gap, ["id", "code", "subject", "message"]) ||
      !sha(gap.id) ||
      !text(gap.code, 200) ||
      (gap.subject !== null && !text(gap.subject, 1000)) ||
      !text(gap.message, 10000) ||
      gap.id !==
        (await jsonDigest({
          code: gap.code,
          subject: gap.subject,
          message: gap.message,
        }))
    )
      invalid();
  }
  const existingIds = new Set(qualification.blockers.map((gap) => gap.id));
  if (
    qualification.blockers.some(
      (gap) => !blockers.some((entry) => same(entry, gap)),
    )
  )
    invalid();
  const extra = blockers.filter((gap) => !existingIds.has(gap.id));
  if (
    extra.length !== requiredProducerGaps.length ||
    requiredProducerGaps.some(
      (code) =>
        extra.filter((gap) => gap.code === code && gap.subject === null)
          .length !== 1,
    ) ||
    tag !==
      `"package-technical-execution:${saved.manifest.id}:${await jsonDigest({ ...value, qualification: stableQualification })}"`
  )
    invalid();
  return value as unknown as PackageTechnicalExecutionContext;
}

export function technicalExecutionCheckRequest(
  context: PackageTechnicalExecutionContext,
) {
  return {
    purpose: "current_prebid" as const,
    scope_digest: context.qualification.scope.scope_digest,
    method_digest: context.method.digest,
    scale_id: context.qualification.denominator.scale_id,
    budget: "0",
    reason: "核对本范围的正式执行限制；本次检查预算为零。",
  };
}

export function validateTechnicalExecutionRefusal(
  error: unknown,
  context: PackageTechnicalExecutionContext,
): PackageTechnicalExecutionRefusal {
  if (
    !(error instanceof ApiError) ||
    error.status !== 409 ||
    error.code !== "PACKAGE_TECHNICAL_EXECUTION_BLOCKED" ||
    error.retryable !== false ||
    !uuid(error.requestId) ||
    !object(error.details)
  )
    invalid();
  const detail = error.details;
  if (
    !exactKeys(detail, [
      "scope_id",
      "scope_digest",
      "method_digest",
      "blockers",
      "jobs_created",
      "model_requests",
    ]) ||
    detail.scope_id !== context.qualification.scope.scope_id ||
    detail.scope_digest !== context.qualification.scope.scope_digest ||
    detail.method_digest !== context.method.digest ||
    !same(detail.blockers, context.blockers) ||
    detail.jobs_created !== 0 ||
    detail.model_requests !== 0
  )
    invalid();
  return {
    ...(detail as Omit<PackageTechnicalExecutionRefusal, "requestId">),
    requestId: error.requestId,
  };
}
