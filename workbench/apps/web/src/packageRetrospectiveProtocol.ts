import type { ApiResult } from "./api";
import { jsonDigest } from "./editorSchema";
import {
  exactKeys,
  executionId as uuid,
  executionSha as hash,
  recordObject as object,
} from "./executionInputValidation";
import {
  validateCompletePackageReviewComparison,
  validatePackageReviewComparisonPage,
} from "./packageReviewComparisonProtocol";
import type {
  PackageRetrospectiveApplied,
  PackageRetrospectiveChoices,
  PackageRetrospectiveDetail,
  PackageRetrospectiveKnowledgeApplied,
  PackageRetrospectiveKnowledgeLink,
  PackageRetrospectiveKnowledgeRequest,
  PackageRetrospectivePage,
  PackageRetrospectivePreview,
  PackageRetrospectiveRequest,
  PackageRetrospectiveSelection,
  PackageRetrospectiveView,
} from "./packageRetrospectiveContracts";

const flags = [
  "official_deduction_reasons_inferred",
  "risk_resolution_assessed",
  "formal_sample_eligible",
  "model_qualification_granted",
  "knowledge_published",
] as const;
const text = (v: unknown): v is string =>
  typeof v === "string" && v.trim().length > 0;
const date = (v: unknown): v is string =>
  typeof v === "string" && Number.isFinite(Date.parse(v));
const falseFlags = (v: Record<string, unknown>) =>
  flags.every((field) => v[field] === false);

export function retrospectiveFailure(): never {
  throw new Error(
    "复盘所选实交、结果、核查或保存回执不一致。原输入和未确认请求仍保留，请重新读取或恢复原请求。",
  );
}
export const retrospectiveBase = (bidId: string) =>
  `/bids/${bidId}/package-retrospectives`;
export const retrospectiveTag = (v: PackageRetrospectiveView) =>
  `"package-retrospective:${v.manifest.id}:${v.digest}"`;
export function readRetrospectiveText(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

export function validRetrospectiveSelection(
  v: unknown,
): v is PackageRetrospectiveSelection {
  if (
    !object(v) ||
    !exactKeys(v, [
      "submission_id",
      "outcome_id",
      "outcome_missing_reason",
      "business_result_id",
      "business_result_missing_reason",
      "baseline_run_id",
      "submitted_run_id",
      "reviews_missing_reason",
    ]) ||
    !uuid(v.submission_id)
  )
    return false;
  for (const prefix of ["outcome", "business_result"])
    if (
      v[`${prefix}_id`] === null
        ? !text(v[`${prefix}_missing_reason`])
        : !uuid(v[`${prefix}_id`]) || v[`${prefix}_missing_reason`] !== null
    )
      return false;
  return v.baseline_run_id === null
    ? v.submitted_run_id === null && text(v.reviews_missing_reason)
    : uuid(v.baseline_run_id) &&
        uuid(v.submitted_run_id) &&
        v.baseline_run_id !== v.submitted_run_id &&
        v.reviews_missing_reason === null;
}

export async function validateRetrospectivePreview(
  value: unknown,
  bidId: string,
  selected?: PackageRetrospectiveSelection,
): Promise<PackageRetrospectivePreview> {
  if (
    !object(value) ||
    !exactKeys(value, ["manifest", "digest"]) ||
    !hash(value.digest) ||
    !object(value.manifest) ||
    (await jsonDigest(value.manifest)) !== value.digest
  )
    return retrospectiveFailure();
  const p = value.manifest;
  if (
    p.version !== "package-retrospective-preview/1" ||
    p.bid_id !== bidId ||
    p.timing !== "post_outcome_retrospective" ||
    !falseFlags(p) ||
    !validRetrospectiveSelection(p.selection) ||
    !object(p.submission) ||
    (selected &&
      (await jsonDigest(selected)) !== (await jsonDigest(p.selection)))
  )
    return retrospectiveFailure();
  const s = p.submission;
  if (
    s.id !== p.selection.submission_id ||
    !uuid(s.package_id) ||
    !uuid(s.revision_id) ||
    !hash(s.package_digest) ||
    !hash(s.binding_digest) ||
    !hash(s.registration_risk_digest) ||
    !date(s.submitted_at) ||
    !date(s.recorded_at) ||
    !date(s.registration_assessed_at) ||
    s.risk_resolution_assessed !== false ||
    typeof s.current !== "boolean" ||
    !["standard", "offline_fact"].includes(String(s.kind)) ||
    !object(s.identity)
  )
    return retrospectiveFailure();
  const identity = s.identity;
  const identityWithoutHash = { ...identity };
  delete identityWithoutHash.digest;
  if (
    !hash(identity.digest) ||
    (await jsonDigest(identityWithoutHash)) !== identity.digest ||
    ![
      identity.engineering_project_id,
      identity.round_id,
      identity.bidder_id,
    ].every(uuid)
  )
    return retrospectiveFailure();
  if (
    p.outcome === null
      ? p.selection.outcome_id !== null
      : !object(p.outcome) ||
        p.outcome.id !== p.selection.outcome_id ||
        p.outcome.submission_id !== s.id ||
        !["technical_total", "overall_total", "unknown"].includes(
          String(p.outcome.score_kind),
        ) ||
        !["pending", "verified", "conflict", "rejected"].includes(
          String(p.outcome.verification),
        ) ||
        !Array.isArray(p.outcome.evidence_refs) ||
        typeof p.outcome.current !== "boolean" ||
        !Array.isArray(p.outcome.association_reasons)
  )
    return retrospectiveFailure();
  if (object(p.outcome))
    for (const field of ["value", "maximum"])
      if (
        p.outcome[field] !== null &&
        (typeof p.outcome[field] !== "string" ||
          !/^-?(0|[1-9][0-9]*)(\.[0-9]+)?$/.test(String(p.outcome[field])))
      )
        return retrospectiveFailure();
  if (
    p.business_result === null
      ? p.selection.business_result_id !== null
      : !object(p.business_result) ||
        p.business_result.id !== p.selection.business_result_id ||
        p.business_result.bid_id !== bidId ||
        p.business_result.submission_id !== s.id ||
        typeof p.business_result.current !== "boolean" ||
        !["pending", "verified", "conflict", "rejected"].includes(
          String(p.business_result.verification),
        )
  )
    return retrospectiveFailure();
  if (
    !Array.isArray(p.source_ids) ||
    p.source_ids.length > 400 ||
    !p.source_ids.every(uuid) ||
    new Set(p.source_ids).size !== p.source_ids.length ||
    !Array.isArray(p.source_snapshot) ||
    p.source_snapshot.length > 20000 ||
    !Array.isArray(p.documents) ||
    !p.documents.length ||
    p.documents.length > 100 ||
    !p.documents.every(
      (d) =>
        object(d) &&
        uuid(d.id) &&
        hash(d.digest) &&
        text(d.original_name) &&
        Number.isSafeInteger(d.byte_size) &&
        Number(d.byte_size) >= 0,
    ) ||
    !Array.isArray(p.gaps) ||
    !p.gaps.every((g) => object(g) && text(g.code) && text(g.message))
  )
    return retrospectiveFailure();
  if (p.comparison !== null) {
    if (
      !object(p.comparison) ||
      !hash(p.comparison.digest) ||
      !object(p.comparison.manifest) ||
      p.selection.baseline_run_id === null ||
      p.selection.submitted_run_id === null
    )
      return retrospectiveFailure();
    const m = p.comparison.manifest;
    const page = await validatePackageReviewComparisonPage(
      {
        ...m,
        comparison_digest: p.comparison.digest,
        has_more: false,
        next_cursor: null,
      },
      {
        bidId,
        leftId: p.selection.baseline_run_id,
        rightId: p.selection.submitted_run_id,
      },
      800,
    );
    await validateCompletePackageReviewComparison(page, page.items);
    if (
      page.right.scope.package_id !== s.package_id ||
      page.right.scope.revision_id !== s.revision_id
    )
      return retrospectiveFailure();
  } else if (
    p.selection.baseline_run_id !== null ||
    p.selection.submitted_run_id !== null
  )
    return retrospectiveFailure();
  return value as unknown as PackageRetrospectivePreview;
}

export async function validateRetrospectiveView(
  value: unknown,
  bidId: string,
): Promise<PackageRetrospectiveView> {
  if (
    !object(value) ||
    !exactKeys(value, ["manifest", "digest"]) ||
    !hash(value.digest) ||
    !object(value.manifest) ||
    (await jsonDigest(value.manifest)) !== value.digest
  )
    return retrospectiveFailure();
  const m = value.manifest;
  if (
    m.version !== "package-retrospective/1" ||
    m.bid_id !== bidId ||
    m.state !== "pending_review" ||
    !uuid(m.id) ||
    !uuid(m.actor_id) ||
    !uuid(m.command_id) ||
    !date(m.created_at) ||
    !text(m.title) ||
    !falseFlags(m) ||
    !object(m.notes) ||
    !text(m.notes.observations) ||
    !text(m.notes.next_actions) ||
    typeof m.notes.hypotheses !== "string" ||
    typeof m.notes.additional_missing_materials !== "string"
  )
    return retrospectiveFailure();
  await validateRetrospectivePreview(m.preview, bidId);
  return value as unknown as PackageRetrospectiveView;
}

export function validateRetrospectiveLink(
  value: unknown,
  frozen: PackageRetrospectiveView,
): PackageRetrospectiveKnowledgeLink {
  if (
    !object(value) ||
    value.retrospective_id !== frozen.manifest.id ||
    value.retrospective_digest !== frozen.digest ||
    !uuid(value.knowledge_id) ||
    !uuid(value.knowledge_version_id) ||
    !uuid(value.source_id) ||
    !uuid(value.actor_id) ||
    !date(value.created_at) ||
    !text(value.reason) ||
    value.policy_class !== "derived_mixed" ||
    value.knowledge_published !== false ||
    value.formal_sample_eligible !== false
  )
    return retrospectiveFailure();
  return value as unknown as PackageRetrospectiveKnowledgeLink;
}

type Pending = { body: unknown; etag: string; key: string; path: string };
export function retrospectivePending(scope: string): Pending | null {
  try {
    const value: unknown = JSON.parse(
      sessionStorage.getItem(`tender:command-record:${scope}`) ?? "null",
    );
    return object(value) &&
      typeof value.etag === "string" &&
      text(value.key) &&
      typeof value.path === "string"
      ? (value as Pending)
      : null;
  } catch {
    return null;
  }
}
async function command(value: unknown, actor: string, pending: Pending) {
  if (
    !object(value) ||
    !exactKeys(value, [
      "command_id",
      "actor_id",
      "idempotency_key",
      "request_digest",
      "request",
      "if_match",
    ]) ||
    !uuid(value.command_id) ||
    value.actor_id !== actor ||
    value.idempotency_key !== pending.key ||
    value.if_match !== pending.etag ||
    (await jsonDigest(value.request)) !== (await jsonDigest(pending.body)) ||
    value.request_digest !==
      (await jsonDigest({ body: pending.body, if_match: pending.etag }))
  )
    return retrospectiveFailure();
  return value;
}
export async function validateRetrospectiveAck(
  result: ApiResult<unknown>,
  bidId: string,
  actor: string,
  scope: string,
): Promise<PackageRetrospectiveApplied> {
  const pending = retrospectivePending(scope);
  if (
    !pending ||
    pending.path !== retrospectiveBase(bidId) ||
    !object(result.data) ||
    !object(pending.body)
  )
    return retrospectiveFailure();
  const expected = pending.body as PackageRetrospectiveRequest;
  const frozen = await validateRetrospectiveView(
    result.data.retrospective,
    bidId,
  );
  const receipt = await command(result.data.command, actor, pending);
  if (
    result.etag !== retrospectiveTag(frozen) ||
    frozen.manifest.command_id !== receipt.command_id ||
    frozen.manifest.actor_id !== actor ||
    frozen.manifest.title !== expected.title ||
    (await jsonDigest(frozen.manifest.notes)) !==
      (await jsonDigest(expected.notes)) ||
    frozen.manifest.preview.digest !== expected.preview_digest ||
    (await jsonDigest(frozen.manifest.preview.manifest.selection)) !==
      (await jsonDigest(expected.selection))
  )
    return retrospectiveFailure();
  return result.data as unknown as PackageRetrospectiveApplied;
}
export async function validateRetrospectiveKnowledgeAck(
  result: ApiResult<unknown>,
  frozen: PackageRetrospectiveView,
  actor: string,
  scope: string,
): Promise<PackageRetrospectiveKnowledgeApplied> {
  const pending = retrospectivePending(scope);
  const path = `${retrospectiveBase(frozen.manifest.bid_id)}/${frozen.manifest.id}/knowledge-candidate`;
  if (
    !pending ||
    pending.path !== path ||
    !object(result.data) ||
    !object(pending.body)
  )
    return retrospectiveFailure();
  const expected = pending.body as PackageRetrospectiveKnowledgeRequest;
  const linked = validateRetrospectiveLink(result.data.link, frozen);
  await command(result.data.command, actor, pending);
  if (
    result.etag !== retrospectiveTag(frozen) ||
    linked.actor_id !== actor ||
    expected.retrospective_digest !== frozen.digest ||
    linked.reason !== expected.reason
  )
    return retrospectiveFailure();
  return result.data as unknown as PackageRetrospectiveKnowledgeApplied;
}
export async function validateRetrospectiveDetail(
  value: unknown,
  bidId: string,
  id: string,
): Promise<PackageRetrospectiveDetail> {
  if (
    !object(value) ||
    !exactKeys(value, ["retrospective", "current", "knowledge_link"]) ||
    !object(value.current) ||
    typeof value.current.unchanged !== "boolean" ||
    !Array.isArray(value.current.issues) ||
    !value.current.issues.every(
      (g) => object(g) && text(g.code) && text(g.message),
    )
  )
    return retrospectiveFailure();
  const frozen = await validateRetrospectiveView(value.retrospective, bidId);
  if (frozen.manifest.id !== id) return retrospectiveFailure();
  if (value.knowledge_link !== null)
    validateRetrospectiveLink(value.knowledge_link, frozen);
  return value as unknown as PackageRetrospectiveDetail;
}
export function validateRetrospectiveChoices(
  value: unknown,
  bidId: string,
  kind: string,
  submission: string | null,
): PackageRetrospectiveChoices {
  if (
    !object(value) ||
    value.bid_id !== bidId ||
    value.kind !== kind ||
    value.submission_id !== submission ||
    !Array.isArray(value.items) ||
    !value.items.every(
      (v) =>
        object(v) &&
        uuid(v.id) &&
        text(v.label) &&
        [true, false, null].includes(v.current as boolean | null),
    ) ||
    (value.next_offset !== null &&
      (!Number.isSafeInteger(value.next_offset) ||
        Number(value.next_offset) < 0))
  )
    return retrospectiveFailure();
  return value as unknown as PackageRetrospectiveChoices;
}

export function validateRetrospectiveHistory(
  value: unknown,
  bidId: string,
): PackageRetrospectivePage {
  if (
    !object(value) ||
    !exactKeys(value, ["bid_id", "items", "next_offset"]) ||
    value.bid_id !== bidId ||
    !Array.isArray(value.items) ||
    value.items.length > 100 ||
    !value.items.every(
      (row) =>
        object(row) &&
        exactKeys(row, [
          "id",
          "title",
          "submission_id",
          "created_at",
          "digest",
        ]) &&
        uuid(row.id) &&
        uuid(row.submission_id) &&
        text(row.title) &&
        date(row.created_at) &&
        hash(row.digest),
    ) ||
    (value.next_offset !== null &&
      (!Number.isSafeInteger(value.next_offset) ||
        Number(value.next_offset) < 0))
  )
    return retrospectiveFailure();
  return value as unknown as PackageRetrospectivePage;
}
