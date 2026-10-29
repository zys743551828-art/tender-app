import type {
  PackageTechnicalScopeView,
  PackageTechnicalScoringContext,
} from "./contracts";
import {
  exactKeys,
  recordObject as object,
  executionSha as sha,
  executionId as uuid,
} from "./executionInputValidation";
import { jsonDigest } from "./editorSchema";
import { technicalSame as same } from "./packageTechnicalScopeProtocol";
import { validateTechnicalEligibility } from "./packageTechnicalEligibilityProtocol";

type Gap = PackageTechnicalScoringContext["blockers"][number];
export type MaterialReference = {
  seal_id: string;
  seal_digest: string;
  input_digest: string;
  quote_id: string;
  quote_digest: string;
};
export type MaterialCheck = {
  version: "package-material-execution-check/1";
  scope_digest: string;
  profile_digest: string;
  serializer_digest: string;
  judgment_method_digest: string;
  input_reference: MaterialReference | null;
  budget_usd: string;
};
export type MaterialContext = {
  version: "package-material-execution-context/1";
  qualification: PackageTechnicalScoringContext;
  target: {
    profile: Record<string, unknown>;
    profile_digest: string;
    serializer_digest: string;
    judgment_method_digest: string;
  };
  execution_enabled: false;
  blockers: Gap[];
};
export type MaterialReceipt = {
  version: "package-material-execution-receipt/1";
  command_id: string;
  actor_id: string;
  scope_id: string;
  scope_digest: string;
  request_digest: string;
  request: MaterialCheck;
  observed_at: string;
  state: "blocked";
  reference_status: "unverified";
  execution_authorized: false;
  jobs_created: 0;
  model_requests: 0;
  fee_reserved: false;
  blockers: Gap[];
};
export type PendingMaterialCheck = {
  key: string;
  etag: string;
  body: MaterialCheck;
};
const gaps = [
  "MATERIAL_REFERENCE_UNVERIFIED",
  "LIVE_QUALIFICATION_UNAVAILABLE",
  "LIVE_COST_UNCONFIRMED",
];
const profile = {
  version: "package-technical-complete-vision-profile/3",
  provider_id: "deepseek",
  endpoint: "https://api.deepseek.com/v1/chat/completions",
  model_alias: "deepseek-flash",
  expected_response_model: "deepseek-flash",
  maximum_body_bytes: 48 * 1024 * 1024,
  maximum_image_bytes: 32 * 1024 * 1024,
  maximum_images: 384,
  maximum_total_image_bytes: 64 * 1024 * 1024,
  maximum_dimension: 8192,
  many_images_threshold: 15,
  maximum_many_image_dimension: 4096,
  image_detail: "original",
  max_output_tokens: 4096,
  thinking: "disabled",
  temperature: 0,
  remote_images: false,
  automatic_retry: false,
  immutable_weights_verified: false,
};
export function invalidMaterial(): never {
  throw new Error("完整材料核对记录不完整或身份不符，请保留原请求后核查。");
}
export function validMaterialRequest(
  v: unknown,
  scopeDigest: string,
): v is MaterialCheck {
  if (
    !object(v) ||
    !exactKeys(v, [
      "version",
      "scope_digest",
      "profile_digest",
      "serializer_digest",
      "judgment_method_digest",
      "input_reference",
      "budget_usd",
    ]) ||
    v.version !== "package-material-execution-check/1" ||
    v.scope_digest !== scopeDigest ||
    ![
      v.scope_digest,
      v.profile_digest,
      v.serializer_digest,
      v.judgment_method_digest,
    ].every(sha) ||
    typeof v.budget_usd !== "string" ||
    v.budget_usd.length > 30 ||
    !/^(0|[1-9][0-9]*)(\.[0-9]{1,6})?$/.test(v.budget_usd)
  )
    return false;
  const r = v.input_reference;
  return (
    r === null ||
    (object(r) &&
      exactKeys(r, [
        "seal_id",
        "seal_digest",
        "input_digest",
        "quote_id",
        "quote_digest",
      ]) &&
      uuid(r.seal_id) &&
      uuid(r.quote_id) &&
      sha(r.seal_digest) &&
      sha(r.input_digest) &&
      sha(r.quote_digest))
  );
}
async function checkGaps(value: unknown): Promise<Gap[]> {
  if (
    !Array.isArray(value) ||
    value.length > 20000 ||
    value.length < 3 ||
    new Set(value.map((g) => g?.id)).size !== value.length
  )
    invalidMaterial();
  for (const g of value) {
    if (
      !object(g) ||
      !exactKeys(g, ["id", "code", "subject", "message"]) ||
      !sha(g.id) ||
      typeof g.code !== "string" ||
      !g.code ||
      g.code.length > 200 ||
      typeof g.message !== "string" ||
      !g.message ||
      g.message.length > 10000 ||
      !(
        g.subject === null ||
        (typeof g.subject === "string" && g.subject.length <= 1000)
      ) ||
      g.id !==
        (await jsonDigest({
          code: g.code,
          subject: g.subject,
          message: g.message,
        }))
    )
      invalidMaterial();
  }
  if (
    gaps.some(
      (code) => !value.some((g) => g.code === code && g.subject === null),
    )
  )
    invalidMaterial();
  return value as Gap[];
}
export async function materialContext(
  value: unknown,
  tag: string | null,
  saved: PackageTechnicalScopeView,
): Promise<MaterialContext> {
  if (
    !object(value) ||
    !exactKeys(value, [
      "version",
      "qualification",
      "target",
      "execution_enabled",
      "blockers",
    ]) ||
    value.version !== "package-material-execution-context/1" ||
    value.execution_enabled !== false ||
    !object(value.qualification) ||
    !object(value.target) ||
    !exactKeys(value.target, [
      "profile",
      "profile_digest",
      "serializer_digest",
      "judgment_method_digest",
    ]) ||
    !same(value.target.profile, profile) ||
    value.target.profile_digest !== (await jsonDigest(profile)) ||
    !sha(value.target.serializer_digest) ||
    !sha(value.target.judgment_method_digest)
  )
    invalidMaterial();
  const stable = Object.fromEntries(
    Object.entries(value.qualification).filter(([k]) => k !== "observed_at"),
  );
  const qualification = await validateTechnicalEligibility(
    value.qualification,
    `"package-technical-eligibility:${saved.manifest.id}:${await jsonDigest(stable)}"`,
    saved,
    { purpose: "current_prebid", scaleId: null },
  );
  const blockers = await checkGaps(value.blockers);
  if (
    qualification.blockers.some((g) => !blockers.some((b) => same(g, b))) ||
    tag !==
      `"package-material-execution:${saved.manifest.id}:${await jsonDigest({ ...value, qualification: stable })}"`
  )
    invalidMaterial();
  return value as unknown as MaterialContext;
}
export async function materialReceipt(
  value: unknown,
  pending: PendingMaterialCheck,
  saved: PackageTechnicalScopeView,
  actor: string,
): Promise<MaterialReceipt> {
  if (
    !object(value) ||
    !exactKeys(value, [
      "version",
      "command_id",
      "actor_id",
      "scope_id",
      "scope_digest",
      "request_digest",
      "request",
      "observed_at",
      "state",
      "reference_status",
      "execution_authorized",
      "jobs_created",
      "model_requests",
      "fee_reserved",
      "blockers",
    ]) ||
    value.version !== "package-material-execution-receipt/1" ||
    !uuid(value.command_id) ||
    value.actor_id !== actor ||
    value.scope_id !== saved.manifest.id ||
    value.scope_digest !== saved.digest ||
    !validMaterialRequest(value.request, saved.digest) ||
    !same(value.request, pending.body) ||
    value.request_digest !== (await jsonDigest(pending.body)) ||
    typeof value.observed_at !== "string" ||
    !Number.isFinite(Date.parse(value.observed_at)) ||
    value.state !== "blocked" ||
    value.reference_status !== "unverified" ||
    value.execution_authorized !== false ||
    value.fee_reserved !== false ||
    value.jobs_created !== 0 ||
    value.model_requests !== 0
  )
    invalidMaterial();
  await checkGaps(value.blockers);
  return value as unknown as MaterialReceipt;
}
export function materialStorageKey(
  saved: PackageTechnicalScopeView,
  actor: string,
) {
  return `tender:material-check:${actor}:${saved.manifest.id}:${saved.digest}`;
}
export function readMaterialPending(
  saved: PackageTechnicalScopeView,
  actor: string,
): PendingMaterialCheck | null {
  const raw = sessionStorage.getItem(materialStorageKey(saved, actor));
  if (!raw) return null;
  if (raw.length > 16384) invalidMaterial();
  const v: unknown = JSON.parse(raw);
  if (
    !object(v) ||
    !exactKeys(v, ["key", "etag", "body"]) ||
    !uuid(v.key) ||
    typeof v.etag !== "string" ||
    !new RegExp(
      `^"package-material-execution:${saved.manifest.id}:[a-f0-9]{64}"$`,
    ).test(v.etag) ||
    !validMaterialRequest(v.body, saved.digest)
  )
    invalidMaterial();
  return v as PendingMaterialCheck;
}
