import { ApiError } from "./api";
import type {
  BidPackageStoredView,
  KnowledgePackageReviewTargetPage,
  PackageReviewRunView,
  PackageSubmissionAppliedView,
  PackageSubmissionPreview,
  PackageSubmissionRequest,
  PackageSubmissionSelection,
  PackageSubmissionView,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  exactKeys,
  executionId as uuid,
  executionSha as sha,
  recordObject as object,
} from "./executionInputValidation";
import { historicalDateTime, historicalSame } from "./historicalImportProtocol";

export type PackageSubmissionScope = { bidId: string; memberId: string };
export type PendingPackageSubmission = {
  key: string;
  body: PackageSubmissionRequest;
  etag: string;
  supersedesId: string | null;
};
export type SubmissionRunTarget =
  KnowledgePackageReviewTargetPage["items"][number];
export const sameSubmissionValue = historicalSame;
export const packageSubmissionBase = (
  bidId: string,
  s: PackageSubmissionSelection,
) => `/bids/${bidId}/packages/${s.package_id}/revisions/${s.revision_id}`;
export const packageSubmissionPath = (
  bidId: string,
  p: PendingPackageSubmission,
) =>
  p.supersedesId
    ? `/submissions/${p.supersedesId}/package-corrections`
    : `${packageSubmissionBase(bidId, p.body.selection)}/submissions`;
export function submissionProtocolFailure(): never {
  throw new Error(
    "整包提交的项目、固定来源、摘要或原操作回执不一致。尚未确认保存成功，原请求保留。",
  );
}
const integer = (v: unknown): v is number =>
  Number.isSafeInteger(v) && Number(v) >= 0;
const text = (v: unknown, maximum = 2000): v is string =>
  typeof v === "string" &&
  !!v.trim() &&
  Array.from(v).length <= maximum &&
  Array.from(v).every((c) => {
    const n = c.codePointAt(0)!;
    return (
      (n >= 32 || [9, 10, 13].includes(n)) && !(n >= 0xd800 && n <= 0xdfff)
    );
  });
const strings = (v: unknown): v is string[] =>
  Array.isArray(v) && v.every((s) => text(s, 10000));
const ids = (v: unknown): v is string[] =>
  Array.isArray(v) && v.every(uuid) && new Set(v).size === v.length;
export const validSubmissionBidEtag = (
  v: unknown,
  bidId: string,
): v is string =>
  typeof v === "string" &&
  v.startsWith(`"bid:${bidId}:`) &&
  /^"bid:[a-f0-9-]{36}:[a-f0-9]{64}"$/.test(v);
function instant(value: unknown): bigint | null {
  try {
    const normalized = historicalDateTime(value, "实际提交时间");
    const fraction = /\.(\d{6})/.exec(normalized)?.[1] ?? "000000";
    const ms = Date.parse(normalized);
    return Number.isFinite(ms)
      ? BigInt(ms) * 1000n + BigInt(fraction.slice(3))
      : null;
  } catch {
    return null;
  }
}
export function submissionTime(value: string, now = Date.now()) {
  const normalized = historicalDateTime(value.trim(), "实际提交时间");
  const at = instant(normalized);
  if (at === null || at > BigInt(now) * 1000n)
    throw new Error("只能登记已经发生的提交，请填写包含秒和时区的准确时间。");
  // This endpoint records the exact JSON body (unlike the historical import model dump).
  // Validate calendar/precision without rewriting the user's offset or fractional spelling.
  return value.trim();
}
const sameInstant = (a: unknown, b: unknown) =>
  instant(a) !== null && instant(a) === instant(b);
function pointer(v: unknown) {
  return (
    v === null ||
    (object(v) && exactKeys(v, ["id", "digest"]) && uuid(v.id) && sha(v.digest))
  );
}
export function validPackageSubmissionSelection(
  v: unknown,
): v is PackageSubmissionSelection {
  return (
    object(v) &&
    exactKeys(v, [
      "package_id",
      "revision_id",
      "package_digest",
      "inventory",
      "coverage",
      "review_run",
    ]) &&
    uuid(v.package_id) &&
    uuid(v.revision_id) &&
    sha(v.package_digest) &&
    pointer(v.inventory) &&
    pointer(v.coverage) &&
    (v.inventory !== null || (v.coverage === null && v.review_run === null)) &&
    (v.review_run === null ||
      (object(v.review_run) &&
        exactKeys(v.review_run, ["id", "input_digest", "result_digest"]) &&
        uuid(v.review_run.id) &&
        sha(v.review_run.input_digest) &&
        (v.review_run.result_digest === null ||
          sha(v.review_run.result_digest))))
  );
}
export function validPackageSubmissionRequest(
  v: unknown,
): v is PackageSubmissionRequest {
  return (
    object(v) &&
    exactKeys(v, [
      "kind",
      "selection",
      "input_digest",
      "evidence",
      "submitted_at",
      "explanation",
      "expected_head",
      "correction_reason",
    ]) &&
    ["standard", "offline_fact"].includes(String(v.kind)) &&
    validPackageSubmissionSelection(v.selection) &&
    sha(v.input_digest) &&
    object(v.evidence) &&
    exactKeys(v.evidence, ["document_version_id", "digest", "byte_size"]) &&
    uuid(v.evidence.document_version_id) &&
    sha(v.evidence.digest) &&
    integer(v.evidence.byte_size) &&
    instant(v.submitted_at) !== null &&
    text(v.explanation) &&
    (v.expected_head === null
      ? v.correction_reason === null
      : object(v.expected_head) &&
        exactKeys(v.expected_head, ["id", "revision"]) &&
        uuid(v.expected_head.id) &&
        integer(v.expected_head.revision) &&
        v.expected_head.revision > 0 &&
        text(v.correction_reason))
  );
}
export function validPendingPackageSubmission(
  v: unknown,
  bidId: string,
): v is PendingPackageSubmission {
  return (
    object(v) &&
    exactKeys(v, ["key", "body", "etag", "supersedesId"]) &&
    typeof v.key === "string" &&
    /^[\x20-\x7e]{1,128}$/.test(v.key) &&
    validPackageSubmissionRequest(v.body) &&
    validSubmissionBidEtag(v.etag, bidId) &&
    (v.supersedesId === null || uuid(v.supersedesId)) &&
    v.supersedesId === (v.body.expected_head?.id ?? null)
  );
}
export function submissionPackageMatches(
  v: BidPackageStoredView | undefined,
  bidId: string,
  packageId: string,
  revisionId: string,
) {
  return (
    !!v &&
    object(v.manifest) &&
    v.manifest.scope.bid_id === bidId &&
    v.manifest.package_id === packageId &&
    v.manifest.revision_id === revisionId &&
    v.manifest.kind === "bid" &&
    sha(v.digest) &&
    sha(v.identity?.digest) &&
    Array.isArray(v.manifest.members) &&
    v.manifest.members.length > 0 &&
    v.manifest.members.every(
      (m) =>
        uuid(m.document_version_id) &&
        sha(m.file_digest) &&
        m.scope.bid_id === bidId,
    )
  );
}
async function validateFrozenSelection(
  selection: PackageSubmissionPreview["selection"],
  request: PackageSubmissionSelection,
  bidId: string,
) {
  const target = selection?.target;
  if (
    !submissionPackageMatches(
      target,
      bidId,
      request.package_id,
      request.revision_id,
    ) ||
    target.digest !== request.package_digest ||
    (await jsonDigest(target.manifest)) !== target.digest
  )
    submissionProtocolFailure();
  const i = selection.inventory;
  if (request.inventory === null) {
    if (i !== null || selection.authority !== null) submissionProtocolFailure();
  } else if (
    !i ||
    i.manifest.id !== request.inventory.id ||
    i.digest !== request.inventory.digest ||
    i.manifest.bid_id !== bidId ||
    i.manifest.package_id !== request.package_id ||
    i.manifest.target_revision_id !== request.revision_id ||
    i.manifest.package_digest !== request.package_digest ||
    (await jsonDigest(i.manifest)) !== i.digest ||
    !selection.authority ||
    selection.authority.manifest.scope.bid_id !== bidId ||
    selection.authority.manifest.kind !== "authority" ||
    selection.authority.manifest.revision_id !==
      i.manifest.authority_revision_id ||
    selection.authority.digest !== i.manifest.authority_digest ||
    (await jsonDigest(selection.authority.manifest)) !==
      selection.authority.digest
  )
    submissionProtocolFailure();
  const coverage = selection.coverage;
  if (request.coverage === null) {
    if (coverage !== null) submissionProtocolFailure();
  } else if (
    !coverage ||
    coverage.manifest.id !== request.coverage.id ||
    coverage.digest !== request.coverage.digest ||
    coverage.manifest.bid_id !== bidId ||
    coverage.manifest.inventory_id !== request.inventory?.id ||
    coverage.manifest.inventory_digest !== request.inventory?.digest ||
    coverage.manifest.package_digest !== request.package_digest ||
    (await jsonDigest(coverage.manifest)) !== coverage.digest
  )
    submissionProtocolFailure();
}
export async function validateSubmissionGate(
  gate: PackageSubmissionPreview["gate"],
  request: PackageSubmissionSelection,
  selection: PackageSubmissionPreview["selection"],
  bidId: string,
) {
  const m = gate?.manifest;
  if (
    !object(m) ||
    m.version !== "package-submission-gate/1" ||
    m.kind !== "current_package_submission_observation" ||
    !sameSubmissionValue(m.subject, {
      kind: "bid_package",
      bid_id: bidId,
      package_id: request.package_id,
      revision_id: request.revision_id,
      package_digest: request.package_digest,
      identity_digest: selection.target.identity.digest,
    }) ||
    m.allowed !== false ||
    m.inventory_complete !== false ||
    m.quality_status !== "not_measured" ||
    m.formal_scoring_eligible !== false ||
    m.submission_eligible !== false ||
    m.publication_authorized !== false ||
    m.platform_submission_verified !== false ||
    !["blocked", "unknown"].includes(String(m.state)) ||
    !sha(m.policy_digest) ||
    instant(m.checked_at) === null ||
    !strings(m.limitations) ||
    !sha(gate.digest) ||
    (await jsonDigest(m)) !== gate.digest ||
    !object(m.selection) ||
    !sha(m.selection.digest) ||
    m.selection.inventory_id !== (request.inventory?.id ?? null) ||
    m.selection.inventory_digest !== (request.inventory?.digest ?? null) ||
    m.selection.coverage_attempt_id !== (request.coverage?.id ?? null) ||
    m.selection.coverage_digest !== (request.coverage?.digest ?? null) ||
    m.selection.run_id !== (request.review_run?.id ?? null) ||
    m.selection.result_digest !== (request.review_run?.result_digest ?? null) ||
    m.selection.authority_revision_id !==
      (selection.authority?.manifest.revision_id ?? null) ||
    m.selection.authority_digest !== (selection.authority?.digest ?? null) ||
    !object(m.gates)
  )
    submissionProtocolFailure();
  const g = m.gates;
  for (const key of [
    "current_input",
    "core_coverage",
    "mandatory_confirmation",
    "known_blocking_risks",
  ] as const) {
    if (
      !object(g[key]) ||
      !["pass", "unknown", "blocked"].includes(g[key].state) ||
      !strings(g[key].codes)
    )
      submissionProtocolFailure();
  }
  if (
    !["not_performed", "failed"].includes(
      g.current_input.original_verification,
    ) ||
    !integer(g.current_input.member_count) ||
    !Array.isArray(g.current_input.physical_page_gaps) ||
    !g.current_input.physical_page_gaps.every(
      (v) =>
        object(v) &&
        ["target", "authority"].includes(v.role) &&
        text(v.member_id) &&
        integer(v.first_page) &&
        v.first_page > 0 &&
        integer(v.last_page) &&
        v.last_page >= v.first_page,
    ) ||
    ![
      g.core_coverage.active_core_count,
      g.core_coverage.judged_core_count,
      g.core_coverage.unknown_core_count,
      g.core_coverage.unfavorable_core_count,
      g.core_coverage.human_declared_count,
      g.mandatory_confirmation.core_rule_count,
      g.mandatory_confirmation.confirmed_count,
      g.known_blocking_risks.runs_read,
      g.known_blocking_risks.result_rows_read,
      g.known_blocking_risks.blocked_count,
      g.known_blocking_risks.unknown_count,
    ].every(integer) ||
    g.core_coverage.inventory_complete !== false ||
    g.core_coverage.quality_status !== "not_measured" ||
    !["partial", "unknown"].includes(g.core_coverage.overall_coverage) ||
    !ids(g.mandatory_confirmation.pending_rule_ids) ||
    !ids(g.mandatory_confirmation.inactive_rule_ids) ||
    !ids(g.mandatory_confirmation.needs_revalidation_rule_ids) ||
    !Array.isArray(g.mandatory_confirmation.decisions) ||
    !ids(g.known_blocking_risks.unknown_run_ids) ||
    typeof g.known_blocking_risks.history_complete !== "boolean" ||
    !Array.isArray(g.known_blocking_risks.risks)
  )
    submissionProtocolFailure();
}
export async function validatePackageSubmissionPreview(
  value: PackageSubmissionPreview,
  request: PackageSubmissionSelection,
  bidId: string,
) {
  if (
    !object(value) ||
    !sameSubmissionValue(value.selection_request, request) ||
    !validPackageSubmissionSelection(request) ||
    !sha(value.input_digest) ||
    !validSubmissionBidEtag(value.bid_etag, bidId) ||
    !object(value.selection)
  )
    submissionProtocolFailure();
  const h = value.current_submission_head;
  if (
    h !== null &&
    (!object(h) ||
      !uuid(h.id) ||
      !integer(h.revision) ||
      h.revision < 1 ||
      !["single_body", "bid_package"].includes(h.subject_kind))
  )
    submissionProtocolFailure();
  await validateFrozenSelection(value.selection, request, bidId);
  await validateSubmissionGate(value.gate, request, value.selection, bidId);
  return value;
}
export function submissionRunPath(bidId: string, target: SubmissionRunTarget) {
  return `/bids/${bidId}/packages/${target.package_id}/revisions/${target.revision_id}/requirement-inventories/${target.inventory_id}/frozen-review-inputs/${target.frozen_input_id}/execution-inputs/${target.execution_input_id}/review-runs/${target.id}`;
}
export function validateSubmissionRunTargets(
  v: KnowledgePackageReviewTargetPage,
  bidId: string,
  offset = 0,
) {
  if (
    !v ||
    v.bid_id !== bidId ||
    v.reference_only !== true ||
    v.changes_frozen_result !== false ||
    v.formal_score_allowed !== false ||
    !Array.isArray(v.items) ||
    v.items.length > 50 ||
    !v.items.every(
      (t) =>
        object(t) &&
        t.target_kind === "package_review_run" &&
        [
          t.id,
          t.package_id,
          t.revision_id,
          t.inventory_id,
          t.frozen_input_id,
          t.execution_input_id,
        ].every(uuid) &&
        sha(t.input_digest) &&
        (t.result_digest === null || sha(t.result_digest)) &&
        instant(t.created_at) !== null &&
        text(t.state),
    ) ||
    !(
      v.next_offset === null ||
      (integer(v.next_offset) &&
        v.next_offset === offset + v.items.length &&
        v.next_offset > offset)
    )
  )
    submissionProtocolFailure();
  return v;
}
export async function validateSubmissionRun(
  value: PackageReviewRunView,
  target: SubmissionRunTarget,
  bidId: string,
) {
  if (
    !value ||
    value.kind !== "package_review_run" ||
    value.id !== target.id ||
    value.input_digest !== target.input_digest ||
    !sameSubmissionValue(value.scope, {
      bid_id: bidId,
      package_id: target.package_id,
      revision_id: target.revision_id,
      inventory_id: target.inventory_id,
    }) ||
    value.frozen_input_id !== target.frozen_input_id ||
    value.execution_input_id !== target.execution_input_id ||
    !sha(value.frozen_input_digest) ||
    !sha(value.execution_input_digest) ||
    !sha(value.execution_digest) ||
    (value.result?.digest ?? null) !== target.result_digest ||
    !object(value.operation) ||
    value.operation.input_digest !== value.input_digest ||
    (value.result &&
      ((await jsonDigest(value.result.manifest)) !== value.result.digest ||
        value.result.manifest.run_id !== value.id ||
        value.result.manifest.input_digest !== value.input_digest ||
        !sameSubmissionValue(value.result.manifest.scope, value.scope)))
  )
    submissionProtocolFailure();
  return value;
}
export async function validatePackageSubmission(
  value: PackageSubmissionView,
  bidId: string,
  id?: string,
) {
  const b = value?.package_binding,
    m = b?.manifest;
  if (
    !object(value) ||
    value.subject_kind !== "bid_package" ||
    value.bid_id !== bidId ||
    !uuid(value.id) ||
    (id && value.id !== id) ||
    value.body_version_id !== null ||
    value.review_id !== null ||
    value.original_name !== null ||
    value.artifact_kind !== null ||
    typeof value.current !== "boolean" ||
    value.platform_submission_verified !== false ||
    value.gate_checked !== false ||
    !object(m) ||
    m.version !== "package-submission-binding/1" ||
    m.bid_id !== bidId ||
    m.submission_id !== value.id ||
    !uuid(m.actor_id) ||
    !uuid(m.command_id) ||
    !validPackageSubmissionRequest(m.request) ||
    !sameSubmissionValue(m.request.selection, m.selection_request) ||
    value.kind !== m.request.kind ||
    value.explanation !== m.request.explanation ||
    value.correction_reason !== m.request.correction_reason ||
    value.supersedes_id !== m.supersedes_id ||
    m.supersedes_id !== (m.request.expected_head?.id ?? null) ||
    m.head_revision !== (m.request.expected_head?.revision ?? 0) + 1 ||
    value.recorded_by !== m.actor_id ||
    !sameInstant(value.submitted_at, m.request.submitted_at) ||
    !sameInstant(m.submitted_at, m.request.submitted_at) ||
    !sameInstant(value.recorded_at, m.recorded_at) ||
    instant(m.assessed_at) === null ||
    !validSubmissionBidEtag(m.if_match, bidId) ||
    m.original_bytes_verified !== true ||
    m.platform_submission_verified !== false ||
    m.pre_submission_system_check_verified !== false ||
    !sha(b.digest) ||
    (await jsonDigest(m)) !== b.digest ||
    m.input_digest !== m.request.input_digest ||
    !sameSubmissionValue(m.subject, {
      kind: "bid_package",
      bid_id: bidId,
      package_id: m.request.selection.package_id,
      revision_id: m.request.selection.revision_id,
      package_digest: m.request.selection.package_digest,
    }) ||
    !sameSubmissionValue(value.identity, m.package_identity) ||
    !sameSubmissionValue(m.package_identity, m.selection?.target?.identity) ||
    !object(m.context.current) ||
    !object(m.context.current.current) ||
    !sameSubmissionValue(
      m.recorded_identity,
      m.context.current.current.identity,
    )
  )
    submissionProtocolFailure();
  await validateFrozenSelection(m.selection, m.selection_request, bidId);
  await validateSubmissionGate(m.gate, m.selection_request, m.selection, bidId);
  if (
    !sameSubmissionValue(
      value.open_risk_snapshot,
      m.gate.manifest.gates.known_blocking_risks,
    ) ||
    m.gate.manifest.checked_at !== m.assessed_at ||
    (await jsonDigest({
      selection: m.selection,
      selection_request: m.selection_request,
      context: m.context,
      review_run: m.review_run,
      inventory_proof: m.inventory_proof,
    })) !== m.input_digest ||
    (await jsonDigest({
      body: {
        scope: [bidId, m.subject.package_id, m.subject.revision_id],
        supersedes_id: m.supersedes_id,
        ...m.request,
      },
      if_match: m.if_match,
    })) !== m.request_digest ||
    !Array.isArray(m.originals) ||
    !m.originals.length ||
    m.originals.length > 2000 ||
    new Set(m.originals.map((o) => o.document_version_id)).size !==
      m.originals.length ||
    !m.originals.every(
      (o) =>
        object(o) &&
        uuid(o.document_version_id) &&
        sha(o.digest) &&
        integer(o.byte_size) &&
        strings(o.roles) &&
        o.roles.length > 0 &&
        o.roles.every((r) =>
          [
            "target",
            "authority",
            "submission_attachment",
            "source_ancestor",
          ].includes(r),
        ) &&
        typeof o.original_name === "string" &&
        typeof o.media_type === "string" &&
        typeof o.artifact_kind === "string",
    ) ||
    !m.originals.some((o) => sameSubmissionValue(o, m.evidence)) ||
    !m.evidence.roles.includes("submission_attachment") ||
    value.evidence_ref !== m.evidence.document_version_id ||
    !sameSubmissionValue(m.request.evidence, {
      document_version_id: m.evidence.document_version_id,
      digest: m.evidence.digest,
      byte_size: m.evidence.byte_size,
    }) ||
    !Array.isArray(m.attachment_sources)
  )
    submissionProtocolFailure();
  for (const role of ["target", "authority"] as const) {
    for (const member of m.selection[role]?.manifest.members ?? []) {
      if (
        !m.originals.some(
          (o) =>
            o.document_version_id === member.document_version_id &&
            o.digest === member.file_digest &&
            o.roles.includes(role),
        )
      )
        submissionProtocolFailure();
    }
  }
  if (
    m.selection_request.review_run === null
      ? m.review_run !== null
      : !m.review_run ||
        m.review_run.id !== m.selection_request.review_run.id ||
        m.review_run.input_digest !==
          m.selection_request.review_run.input_digest ||
        (m.review_run.result?.digest ?? null) !==
          m.selection_request.review_run.result_digest
  )
    submissionProtocolFailure();
  if (m.review_run) {
    await validateSubmissionRun(
      m.review_run,
      {
        id: m.selection_request.review_run!.id,
        target_kind: "package_review_run",
        created_at: m.review_run.created_at,
        input_digest: m.selection_request.review_run!.input_digest,
        execution_input_id: m.review_run.execution_input_id,
        frozen_input_id: m.review_run.frozen_input_id,
        state: m.review_run.operation.state,
        package_id: m.subject.package_id,
        revision_id: m.subject.revision_id,
        inventory_id: m.selection_request.inventory!.id,
        result_digest: m.selection_request.review_run!.result_digest,
      },
      bidId,
    );
  }
  return value;
}
export async function validatePackageSubmissionAck(
  value: PackageSubmissionAppliedView,
  bidEtag: string | undefined,
  scope: PackageSubmissionScope,
  pending: PendingPackageSubmission,
) {
  if (
    !object(value) ||
    !object(value.command) ||
    !validSubmissionBidEtag(bidEtag, scope.bidId) ||
    bidEtag === pending.etag ||
    value.command.actor_id !== scope.memberId ||
    value.command.idempotency_key !== pending.key ||
    value.command.if_match !== pending.etag ||
    !sameSubmissionValue(value.command.request, pending.body) ||
    !uuid(value.command.command_id) ||
    value.command.request_digest !==
      (await jsonDigest({
        body: {
          scope: [
            scope.bidId,
            pending.body.selection.package_id,
            pending.body.selection.revision_id,
          ],
          supersedes_id: pending.supersedesId,
          ...pending.body,
        },
        if_match: pending.etag,
      }))
  )
    submissionProtocolFailure();
  const record = await validatePackageSubmission(value.submission, scope.bidId);
  const m = record.package_binding.manifest;
  if (
    !sameSubmissionValue(m.request, pending.body) ||
    m.if_match !== pending.etag ||
    m.actor_id !== scope.memberId ||
    m.command_id !== value.command.command_id ||
    m.request_digest !== value.command.request_digest ||
    m.supersedes_id !== pending.supersedesId
  )
    submissionProtocolFailure();
  return record;
}
const terminal = new Set(
  [
    "FUTURE_TIME",
    "EXPLANATION_REQUIRED",
    "INPUT_CHANGED",
    "CONTEXT_CHANGED",
    "HEAD_INVALID",
    "HEAD_CONFLICT",
    "ALREADY_RECORDED",
    "CORRECTION_REASON_REQUIRED",
    "SELECTION_CHANGED",
    "EVIDENCE_CHANGED",
    "ORIGINAL_CHANGED",
    "EMPTY_PACKAGE",
    "GATE_BLOCKED",
    "CAPACITY_EXCEEDED",
    "HISTORY_CAPACITY_EXCEEDED",
    "ORIGINAL_CAPACITY_EXCEEDED",
  ].map((s) => `PACKAGE_SUBMISSION_${s}`),
);
export function definitelyRejectedPackageSubmission(e: unknown) {
  return (
    e instanceof ApiError &&
    (([409, 412, 422].includes(e.status) && terminal.has(e.code)) ||
      (e.status === 412 && e.code === "REVISION_CONFLICT") ||
      ([409, 422].includes(e.status) &&
        ["ORIGINAL_BYTES_CORRUPTED", "ORIGINAL_NOT_AVAILABLE"].includes(
          e.code,
        )))
  );
}
