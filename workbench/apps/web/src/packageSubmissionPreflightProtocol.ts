import type {
  PackageSubmissionPreflightView,
  PackageSubmissionPreview,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  exactKeys,
  executionId as uuid,
  executionSha as sha,
  recordObject as object,
} from "./executionInputValidation";
import { historicalDateTime } from "./historicalImportProtocol";
import {
  sameSubmissionValue as same,
  validatePackageSubmissionPreview,
  type PackageSubmissionScope,
} from "./packageSubmissionProtocol";

const LIMITATIONS = [
  "INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED",
  "PACKAGE_REVIEW_QUALITY_NOT_MEASURED",
  "HUMAN_OPINION_IS_NOT_RECHECK_RESOLUTION",
  "ORIGINAL_BYTES_VERIFIED_AT_OBSERVATION_ONLY",
  "ORIGINAL_BYTES_NOT_ATOMIC_WITH_DATABASE",
  "PREFLIGHT_IS_NOT_SUBMISSION_AUTHORIZATION",
];
const codes = (value: unknown): value is string[] =>
  Array.isArray(value) &&
  value.length <= 100 &&
  new Set(value).size === value.length &&
  value.every(
    (code) =>
      typeof code === "string" &&
      code.length <= 200 &&
      /^[A-Z][A-Z0-9_]+$/.test(code),
  );
function invalid(): never {
  throw new Error(
    "原件复核回执与当前项目、成员或所选整包检查不一致。未采纳此结果，请重新读取提交检查。",
  );
}

export async function validateSubmissionPreflight(
  value: PackageSubmissionPreflightView,
  preview: PackageSubmissionPreview,
  scope: PackageSubmissionScope,
) {
  await validatePackageSubmissionPreview(
    preview,
    preview.selection_request,
    scope.bidId,
  );
  const m = value?.manifest;
  if (
    !object(value) ||
    !exactKeys(value, ["manifest", "digest"]) ||
    !object(m) ||
    !exactKeys(m, [
      "version",
      "kind",
      "subject",
      "selection_request",
      "selection_digest",
      "input_digest",
      "actor_id",
      "checked_at",
      "bid_etag",
      "policy_digest",
      "metadata_gate_digest",
      "review_runtime",
      "originals",
      "gates",
      "state",
      "allowed",
      "inventory_complete",
      "quality_status",
      "submission_eligible",
      "publication_authorized",
      "platform_submission_verified",
      "limitations",
    ]) ||
    m.version !== "package-submission-preflight/1" ||
    m.kind !== "verified_package_submission_observation" ||
    m.actor_id !== scope.memberId ||
    !uuid(m.actor_id) ||
    !same(m.subject, preview.gate.manifest.subject) ||
    !same(m.selection_request, preview.selection_request) ||
    m.input_digest !== preview.input_digest ||
    m.bid_etag !== preview.bid_etag ||
    !sha(m.policy_digest) ||
    !sha(m.metadata_gate_digest) ||
    !sha(value.digest) ||
    (await jsonDigest(m)) !== value.digest ||
    (await jsonDigest(preview.selection)) !== m.selection_digest ||
    m.allowed !== false ||
    m.inventory_complete !== false ||
    m.quality_status !== "not_measured" ||
    m.submission_eligible !== false ||
    m.publication_authorized !== false ||
    m.platform_submission_verified !== false ||
    !codes(m.limitations) ||
    !same(m.limitations, LIMITATIONS) ||
    !object(m.gates) ||
    !exactKeys(m.gates, [
      "current_input",
      "core_coverage",
      "mandatory_confirmation",
      "known_blocking_risks",
    ])
  )
    invalid();
  const checkedAt = historicalDateTime(m.checked_at, "原件复核时间");
  if (Date.parse(checkedAt) < Date.parse(preview.gate.manifest.checked_at))
    invalid();
  for (const key of [
    "core_coverage",
    "mandatory_confirmation",
    "known_blocking_risks",
  ] as const) {
    if (!same(m.gates[key], preview.gate.manifest.gates[key])) invalid();
  }
  const current = m.gates.current_input;
  const metadata = preview.gate.manifest.gates.current_input;
  const retainedCodes = metadata.codes.filter(
    (code) =>
      ![
        "ORIGINAL_BYTES_NOT_CHECKED",
        "REVIEW_RUNTIME_DEPENDENCIES_NOT_CHECKED",
      ].includes(code),
  );
  if (
    !object(current) ||
    !exactKeys(current, [
      "state",
      "codes",
      "scope",
      "metadata_observations_digest",
      "current_identity_digest",
      "original_verification",
      "original_count",
      "originals_digest",
      "physical_page_gaps",
    ]) ||
    !["pass", "unknown", "blocked"].includes(current.state) ||
    !codes(current.codes) ||
    !retainedCodes.every((code) => current.codes.includes(code)) ||
    (metadata.state === "blocked" && current.state !== "blocked") ||
    current.codes.some((code) =>
      [
        "ORIGINAL_BYTES_NOT_CHECKED",
        "REVIEW_RUNTIME_DEPENDENCIES_NOT_CHECKED",
      ].includes(code),
    ) ||
    current.scope !== "current_input_verified_observation" ||
    current.original_verification !== "verified_at_observation" ||
    current.metadata_observations_digest !== metadata.observations_digest ||
    current.current_identity_digest !== metadata.current_identity_digest ||
    !same(current.physical_page_gaps, metadata.physical_page_gaps) ||
    !Array.isArray(m.originals) ||
    m.originals.length === 0 ||
    m.originals.length > 2000 ||
    !Number.isSafeInteger(current.original_count) ||
    current.original_count !== m.originals.length ||
    current.originals_digest !== (await jsonDigest(m.originals))
  )
    invalid();
  const seen = new Set<string>();
  let byteCount = 0;
  for (const original of m.originals) {
    if (
      !object(original) ||
      !exactKeys(original, [
        "document_version_id",
        "digest",
        "byte_size",
        "media_type",
        "artifact_kind",
        "original_name",
        "roles",
      ]) ||
      !uuid(original.document_version_id) ||
      seen.has(original.document_version_id) ||
      !sha(original.digest) ||
      !Number.isSafeInteger(original.byte_size) ||
      original.byte_size < 0 ||
      ![
        original.media_type,
        original.artifact_kind,
        original.original_name,
      ].every((v) => typeof v === "string") ||
      !Array.isArray(original.roles) ||
      original.roles.length === 0 ||
      new Set(original.roles).size !== original.roles.length ||
      !original.roles.every((role) =>
        ["target", "authority", "source_ancestor"].includes(role),
      )
    )
      invalid();
    seen.add(original.document_version_id);
    byteCount += original.byte_size;
    for (const role of ["target", "authority"] as const) {
      if (
        original.roles.includes(role) &&
        !preview.selection[role]?.manifest.members.some(
          (member) =>
            member.document_version_id === original.document_version_id &&
            member.file_digest === original.digest,
        )
      )
        invalid();
    }
  }
  if (!Number.isSafeInteger(byteCount) || byteCount > 8 * 1024 ** 3) invalid();
  for (const role of ["target", "authority"] as const) {
    for (const member of preview.selection[role]?.manifest.members ?? []) {
      if (
        !m.originals.some(
          (original) =>
            original.document_version_id === member.document_version_id &&
            original.digest === member.file_digest &&
            original.roles.includes(role),
        )
      )
        invalid();
    }
  }
  const runtime = m.review_runtime,
    selected = preview.selection_request.review_run;
  if (
    !object(runtime) ||
    !exactKeys(runtime, [
      "state",
      "run_id",
      "selected_input_digest",
      "current_input_digest",
      "codes",
    ]) ||
    !codes(runtime.codes) ||
    runtime.run_id !== (selected?.id ?? null) ||
    runtime.selected_input_digest !== (selected?.input_digest ?? null) ||
    (runtime.current_input_digest !== null &&
      !sha(runtime.current_input_digest)) ||
    (selected === null
      ? runtime.state !== "not_selected" ||
        runtime.current_input_digest !== null ||
        !same(runtime.codes, ["PACKAGE_REVIEW_NOT_SELECTED"])
      : !["matched", "blocked"].includes(runtime.state)) ||
    (runtime.state === "matched" &&
      (runtime.current_input_digest !== selected?.input_digest ||
        runtime.codes.length > 0)) ||
    (runtime.state === "blocked" &&
      (runtime.codes.length === 0 || current.state !== "blocked")) ||
    (current.state === "pass" &&
      (runtime.state !== "matched" ||
        current.codes.length > 0 ||
        current.physical_page_gaps.length > 0)) ||
    !runtime.codes.every((code) => current.codes.includes(code)) ||
    m.state !==
      (Object.values(m.gates).some((card) => card.state === "blocked")
        ? "blocked"
        : "unknown")
  )
    invalid();
  return value;
}
