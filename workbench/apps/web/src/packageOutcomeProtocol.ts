import { ApiError } from "./api";
import type {
  OutcomeRequest,
  PackageOutcomeContext,
  PackageOutcomeVerificationDetails,
  PackageOutcomeVerificationRequest,
  PackageSubmissionView,
  ResearchOutcomeDetail,
  ResearchOutcomePage,
  ResearchOutcomeView,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  exactKeys,
  executionId as uuid,
  executionSha as sha,
  recordObject as object,
} from "./executionInputValidation";
import {
  historicalDateTime,
  historicalSame as same,
} from "./historicalImportProtocol";

export type PackageOutcomeScope = {
  bidId: string;
  memberId: string;
  submissionId: string;
  bindingDigest: string;
};
export type PendingPackageOutcome =
  | {
      kind: "register" | "correct";
      key: string;
      baseId: string | null;
      etag: string | null;
      body: OutcomeRequest;
    }
  | {
      kind: "verify";
      key: string;
      baseId: string;
      etag: string;
      baseRevision: number;
      score: OutcomeRequest & { supersedes_id: string | null };
      body: PackageOutcomeVerificationRequest;
    };
export const packageOutcomeScope = (
  bidId: string,
  memberId: string,
  submission: PackageSubmissionView,
): PackageOutcomeScope => ({
  bidId,
  memberId,
  submissionId: submission.id,
  bindingDigest: submission.package_binding.digest,
});
export function outcomeIdentity(submission: PackageSubmissionView) {
  const { subject, package_identity: i } = submission.package_binding.manifest;
  return {
    project_id: i.engineering_project_id,
    lot_id: "lot_id" in i ? i.lot_id : null,
    round_id: i.round_id,
    bidder_id: i.bidder_id,
    package_id: subject.package_id,
    revision_id: subject.revision_id,
    package_digest: subject.package_digest,
    binding_digest: submission.package_binding.digest,
    identity_digest: i.digest,
  };
}
export function outcomeAuthority(submission: PackageSubmissionView) {
  const a = submission.package_binding.manifest.selection.authority;
  return a
    ? {
        package_id: a.manifest.package_id,
        revision_id: a.manifest.revision_id,
        digest: a.digest,
        identity_digest: a.identity.digest,
      }
    : null;
}
export const outcomeVerificationEtag = (id: string, revision: number) =>
  `"outcome-verification:${id}:${revision}"`;
export const outcomeHeadEtag = (submission: string, revision: number) =>
  `"outcome-head:${submission}:${revision}"`;
const validHeadEtag = (
  value: unknown,
  submissionId: string,
): value is string => {
  if (
    typeof value !== "string" ||
    !new RegExp(`^"outcome-head:${submissionId}:[1-9][0-9]*"$`).test(value)
  )
    return false;
  const revision = Number(value.slice(1, -1).split(":").at(-1));
  return Number.isSafeInteger(revision) && revision < Number.MAX_SAFE_INTEGER;
};
export const packageOutcomePath = (
  scope: PackageOutcomeScope,
  p: PendingPackageOutcome,
) =>
  p.kind === "register"
    ? `/bids/${scope.bidId}/outcomes`
    : `/outcomes/${p.baseId}/${p.kind === "correct" ? "corrections" : "verification"}`;
export function outcomeFailure(
  message = "成绩记录的实交身份、来源或版本不一致；未确认保存成功，原请求仍保留。",
): never {
  throw new Error(message);
}
const integer = (value: unknown) =>
  Number.isSafeInteger(value) && Number(value) >= 0;
const text = (value: unknown, max: number, blank = false): value is string =>
  typeof value === "string" &&
  (blank || !!value.trim()) &&
  Array.from(value).length <= max &&
  Array.from(value).every((character) => {
    const code = character.codePointAt(0)!;
    return (
      (code >= 32 || [9, 10, 13].includes(code)) &&
      (code < 0xd800 || code > 0xdfff)
    );
  });
export function outcomeInstant(value: unknown): bigint | null {
  try {
    const normalized = historicalDateTime(value, "成绩时间");
    const millis = Date.parse(normalized);
    return Number.isFinite(millis)
      ? BigInt(millis) * 1000n +
          BigInt((/\.(\d{6})/.exec(normalized)?.[1] ?? "000000").slice(3))
      : null;
  } catch {
    return null;
  }
}
const sameTime = (a: unknown, b: unknown) =>
  outcomeInstant(a) !== null && outcomeInstant(a) === outcomeInstant(b);
const decimal = (v: unknown): v is string =>
  typeof v === "string" && /^(0|[1-9][0-9]*)(\.[0-9]+)?$/.test(v);
const decimalKey = (v: string) =>
  v.includes(".") ? v.replace(/0+$/, "").replace(/\.$/, "") : v;
const sameAmount = (a: string | null, b: string | null) =>
  a === null || b === null ? a === b : decimalKey(a) === decimalKey(b);
function scoreValid(kind: unknown, value: unknown, maximum: unknown) {
  if (
    !["technical_total", "comprehensive_total", "unknown"].includes(
      String(kind),
    )
  )
    return false;
  if (value === null || maximum === null)
    return value === null && maximum === null;
  if (kind === "unknown" || !decimal(value) || !decimal(maximum)) return false;
  const places = Math.max(
    value.split(".")[1]?.length ?? 0,
    maximum.split(".")[1]?.length ?? 0,
  );
  const scaled = (s: string) => {
    const [whole, fraction = ""] = s.split(".");
    return BigInt(whole + fraction.padEnd(places, "0"));
  };
  return scaled(maximum) > 0n && scaled(value) <= scaled(maximum);
}
const requestKeys = [
  "submission_id",
  "score_kind",
  "value",
  "maximum",
  "source_version_id",
  "known_at",
];
export function validOutcomeRequest(
  value: unknown,
  submissionId: string,
): value is OutcomeRequest {
  return (
    object(value) &&
    exactKeys(value, requestKeys) &&
    value.submission_id === submissionId &&
    scoreValid(value.score_kind, value.value, value.maximum) &&
    uuid(value.source_version_id) &&
    outcomeInstant(value.known_at) !== null
  );
}
export function makeOutcomeRequest(
  submission: PackageSubmissionView,
  draft: {
    scoreKind: OutcomeRequest["score_kind"];
    value: string;
    maximum: string;
    sourceId: string;
    known: string;
  },
): OutcomeRequest {
  const known = historicalDateTime(draft.known.trim(), "成绩取得时间");
  const body: OutcomeRequest = {
    submission_id: submission.id,
    score_kind: draft.scoreKind,
    value:
      draft.scoreKind === "unknown" || !draft.value.trim()
        ? null
        : draft.value.trim(),
    maximum:
      draft.scoreKind === "unknown" || !draft.maximum.trim()
        ? null
        : draft.maximum.trim(),
    source_version_id: draft.sourceId,
    known_at: known,
  };
  if (!validOutcomeRequest(body, submission.id))
    outcomeFailure(
      "请同时填写有效得分与正数满分，得分不得大于满分；未知成绩留空，真实零分填写 0。还须选择准确的成绩原件。",
    );
  const at = outcomeInstant(known)!;
  if (
    at < outcomeInstant(submission.submitted_at)! ||
    at > BigInt(Date.now()) * 1000n
  )
    outcomeFailure("成绩取得时间不能早于实际提交或晚于现在，请保留明确时区。");
  return body;
}
export function validOutcomeVerification(
  value: unknown,
  submission: PackageSubmissionView,
  sourceId: string,
): value is PackageOutcomeVerificationRequest {
  if (
    !object(value) ||
    !exactKeys(value, [
      "version",
      "subject_kind",
      "state",
      "reason",
      "identity",
      "authority",
      "aggregation",
      "published_at",
      "evidence_refs",
    ]) ||
    value.version !== "package-outcome-verification/1" ||
    value.subject_kind !== "bid_package" ||
    !["pending", "verified", "conflict", "rejected"].includes(
      String(value.state),
    ) ||
    !text(value.reason, 4000) ||
    !same(value.identity, outcomeIdentity(submission)) ||
    !same(value.authority, outcomeAuthority(submission)) ||
    !text(value.aggregation, 200, true) ||
    !(
      value.published_at === null || outcomeInstant(value.published_at) !== null
    ) ||
    !Array.isArray(value.evidence_refs) ||
    value.evidence_refs.length > 100
  )
    return false;
  const refs = value.evidence_refs;
  if (
    !refs.every(
      (r) =>
        object(r) &&
        exactKeys(r, [
          "document_version_id",
          "evidence_id",
          "physical_page",
          "quote",
        ]) &&
        r.document_version_id === sourceId &&
        uuid(r.evidence_id) &&
        integer(r.physical_page) &&
        Number(r.physical_page) > 0 &&
        text(r.quote, 4000),
    ) ||
    new Set(refs.map((r) => r.evidence_id)).size !== refs.length
  )
    return false;
  return (
    value.state !== "verified" ||
    (value.authority !== null &&
      !!value.aggregation.trim() &&
      value.published_at !== null &&
      refs.length > 0)
  );
}
export function validPendingOutcome(
  value: unknown,
  scope: PackageOutcomeScope,
  submission: PackageSubmissionView,
): value is PendingPackageOutcome {
  if (!object(value) || !uuid(value.key)) return false;
  if (value.kind === "register" || value.kind === "correct") {
    return (
      exactKeys(value, ["kind", "key", "baseId", "etag", "body"]) &&
      validOutcomeRequest(value.body, scope.submissionId) &&
      (value.kind === "register"
        ? value.baseId === null && value.etag === null
        : uuid(value.baseId) && validHeadEtag(value.etag, scope.submissionId))
    );
  }
  if (
    value.kind !== "verify" ||
    !exactKeys(value, [
      "kind",
      "key",
      "baseId",
      "etag",
      "baseRevision",
      "score",
      "body",
    ]) ||
    !uuid(value.baseId) ||
    !integer(value.baseRevision) ||
    Number(value.baseRevision) >= Number.MAX_SAFE_INTEGER ||
    value.etag !==
      outcomeVerificationEtag(value.baseId, Number(value.baseRevision)) ||
    !object(value.score) ||
    !exactKeys(value.score, [...requestKeys, "supersedes_id"])
  )
    return false;
  const { supersedes_id, ...score } = value.score;
  return (
    (supersedes_id === null || uuid(supersedes_id)) &&
    validOutcomeRequest(score, scope.submissionId) &&
    validOutcomeVerification(value.body, submission, score.source_version_id)
  );
}
export function validateOutcomeContext(
  value: unknown,
  submission: PackageSubmissionView,
): PackageOutcomeContext {
  if (
    !object(value) ||
    value.subject_kind !== "bid_package" ||
    value.bid_id !== submission.bid_id ||
    value.submission_id !== submission.id ||
    value.body_version_id !== null ||
    !same(value.identity, outcomeIdentity(submission)) ||
    !same(value.authority, outcomeAuthority(submission)) ||
    !same(value.package_binding, submission.package_binding) ||
    !same(
      value.package_identity,
      submission.package_binding.manifest.package_identity,
    ) ||
    !same(
      value.recorded_identity,
      submission.package_binding.manifest.recorded_identity,
    ) ||
    !sameTime(value.submitted_at, submission.submitted_at) ||
    value.kind !== submission.kind ||
    !object(value.display) ||
    value.display.body_filename !== null ||
    typeof value.identity_ready !== "boolean" ||
    !["confirmed", "changed", "unavailable"].includes(
      String(value.identity_status),
    ) ||
    value.identity_ready !== (value.identity_status === "confirmed") ||
    !Array.isArray(value.verification_blockers) ||
    !value.verification_blockers.every((v) => text(v, 200)) ||
    value.verification_requires_source_evidence !== true ||
    value.formal_sample_eligible !== false ||
    !same(value.formal_sample_blockers, [
      "package_formal_sample_not_supported",
    ]) ||
    !Array.isArray(value.source_candidates) ||
    value.source_candidates.length > 100 ||
    !value.source_candidates.every(
      (s) =>
        object(s) &&
        uuid(s.id) &&
        text(s.original_name, 1000) &&
        outcomeInstant(s.obtained_at) !== null,
    ) ||
    new Set(value.source_candidates.map((s) => s.id)).size !==
      value.source_candidates.length
  )
    outcomeFailure(
      "成绩登记上下文与这次整包提交不一致，未使用当前正文或其他包替代。",
    );
  const original = submission.package_binding.manifest.package_identity;
  if (
    !same(value.display, {
      project_title: original.engineering_title,
      lot: original.lot,
      round_no: original.round_no,
      bidder_name: original.bidder_name,
      body_filename: null,
    })
  )
    outcomeFailure();
  return value as PackageOutcomeContext;
}
const viewKeys = [
  "id",
  "bid_id",
  ...requestKeys,
  "verification",
  "verification_revision",
  "supersedes_id",
  "verification_details",
];
export function validateOutcomeView(
  value: unknown,
  bidId: string,
  submissionId?: string,
): ResearchOutcomeView {
  if (
    !object(value) ||
    !uuid(value.id) ||
    value.bid_id !== bidId ||
    !uuid(value.submission_id) ||
    (submissionId && value.submission_id !== submissionId) ||
    !scoreValid(value.score_kind, value.value, value.maximum) ||
    !uuid(value.source_version_id) ||
    outcomeInstant(value.known_at) === null ||
    !integer(value.verification_revision) ||
    !["pending", "verified", "conflict", "rejected"].includes(
      String(value.verification),
    ) ||
    !(value.supersedes_id === null || uuid(value.supersedes_id)) ||
    !viewKeys.every((k) => k in value)
  )
    outcomeFailure();
  return value as ResearchOutcomeView;
}
export function validateOutcomePage(
  value: unknown,
  bidId: string,
): ResearchOutcomePage {
  if (
    !object(value) ||
    !exactKeys(value, ["items", "heads"]) ||
    !Array.isArray(value.items) ||
    !Array.isArray(value.heads)
  )
    outcomeFailure();
  const items = value.items.map((v) => validateOutcomeView(v, bidId));
  if (
    new Set(items.map((v) => v.id)).size !== items.length ||
    !value.heads.every(
      (h) =>
        object(h) &&
        exactKeys(h, ["submission_id", "bid_id", "outcome_id", "revision"]) &&
        h.bid_id === bidId &&
        uuid(h.submission_id) &&
        uuid(h.outcome_id) &&
        integer(h.revision) &&
        Number(h.revision) > 0 &&
        items.some(
          (v) => v.id === h.outcome_id && v.submission_id === h.submission_id,
        ),
    ) ||
    new Set(value.heads.map((h) => h.submission_id)).size !== value.heads.length
  )
    outcomeFailure();
  return value as ResearchOutcomePage;
}
async function verifiedDetails(
  value: ResearchOutcomeView,
  submission: PackageSubmissionView,
) {
  const details: unknown = value.verification_details;
  if (value.verification_revision === 0) {
    if (value.verification !== "pending" || details !== null) outcomeFailure();
    return;
  }
  if (
    !object(details) ||
    !exactKeys(details, [
      "version",
      "subject_kind",
      "request",
      "package_identity",
      "binding_digest",
      "checked_at",
      "authority_proof",
      "official_source_proof",
      "verification_scope",
      "formal_sample_eligible",
      "formal_sample_blockers",
    ]) ||
    details.version !== "package-outcome-verification-record/1" ||
    details.subject_kind !== "bid_package" ||
    !validOutcomeVerification(
      details.request,
      submission,
      value.source_version_id,
    ) ||
    details.request.state !== value.verification ||
    !same(
      details.package_identity,
      submission.package_binding.manifest.package_identity,
    ) ||
    details.binding_digest !== submission.package_binding.digest ||
    outcomeInstant(details.checked_at) === null ||
    outcomeInstant(details.checked_at)! <
      outcomeInstant(submission.recorded_at)! ||
    details.verification_scope !== "official_outcome_association" ||
    details.formal_sample_eligible !== false ||
    !same(details.formal_sample_blockers, [
      "package_formal_sample_not_supported",
    ])
  )
    outcomeFailure();
  for (const proof of [
    details.authority_proof,
    details.official_source_proof,
  ]) {
    if (value.verification !== "verified") {
      if (proof !== null) outcomeFailure();
    } else if (
      !object(proof) ||
      !exactKeys(proof, ["digest", "snapshot"]) ||
      !sha(proof.digest) ||
      !object(proof.snapshot) ||
      (await jsonDigest(proof.snapshot)) !== proof.digest
    )
      outcomeFailure();
  }
  if (value.verification === "verified") {
    const authority = (
      details.authority_proof as { snapshot: Record<string, unknown> }
    ).snapshot;
    const official = (
      details.official_source_proof as { snapshot: Record<string, unknown> }
    ).snapshot;
    if (
      authority.version !== "package-outcome-authority/1" ||
      authority.binding_digest !== submission.package_binding.digest ||
      !same(authority.authority, outcomeAuthority(submission)) ||
      official.schema !== "official-source-authority/v2" ||
      !uuid(official.root_id) ||
      !Array.isArray(official.heads) ||
      !official.heads.some(
        (row) =>
          object(row) && row.document_version_id === value.source_version_id,
      ) ||
      !Array.isArray(official.evidence) ||
      official.evidence.length !== details.request.evidence_refs.length
    )
      outcomeFailure();
    for (const ref of details.request.evidence_refs) {
      const proof = official.evidence.find(
        (row) => object(row) && row.id === ref.evidence_id,
      );
      const quoteDigest = Array.from(
        new Uint8Array(
          await crypto.subtle.digest(
            "SHA-256",
            new TextEncoder().encode(ref.quote),
          ),
        ),
        (byte) => byte.toString(16).padStart(2, "0"),
      ).join("");
      if (
        !object(proof) ||
        proof.physical_page !== ref.physical_page ||
        !uuid(proof.parse_id) ||
        !sha(proof.digest) ||
        proof.quote_digest !== quoteDigest
      )
        outcomeFailure();
    }
    const submitted = outcomeInstant(submission.submitted_at)!,
      published = outcomeInstant(details.request.published_at)!,
      known = outcomeInstant(value.known_at)!,
      checked = outcomeInstant(details.checked_at)!;
    if (!(submitted <= published && published <= known && known <= checked))
      outcomeFailure();
  }
}
export async function validateOutcomeDetail(
  value: unknown,
  submission: PackageSubmissionView,
  id: string,
  etag: string | null,
  headEtag: string | undefined,
) {
  const view = validateOutcomeView(value, submission.bid_id, submission.id);
  if (
    !object(value) ||
    value.id !== id ||
    typeof value.current !== "boolean" ||
    etag !== outcomeVerificationEtag(id, view.verification_revision) ||
    !validHeadEtag(headEtag, submission.id)
  )
    outcomeFailure();
  await verifiedDetails(view, submission);
  const a = value.package_association;
  if (
    !object(a) ||
    !exactKeys(a, [
      "available",
      "reasons",
      "checked_at",
      "scope",
      "formal_sample_eligible",
    ]) ||
    typeof a.available !== "boolean" ||
    !Array.isArray(a.reasons) ||
    !a.reasons.every((r) => text(r, 200)) ||
    a.available !== (a.reasons.length === 0) ||
    outcomeInstant(a.checked_at) === null ||
    a.scope !== "official_outcome_association" ||
    a.formal_sample_eligible !== false ||
    (a.available && (!value.current || view.verification !== "verified"))
  )
    outcomeFailure();
  return value as ResearchOutcomeDetail;
}
function scoreMatches(value: ResearchOutcomeView, expected: OutcomeRequest) {
  return (
    value.submission_id === expected.submission_id &&
    value.score_kind === expected.score_kind &&
    sameAmount(value.value, expected.value) &&
    sameAmount(value.maximum, expected.maximum) &&
    value.source_version_id === expected.source_version_id &&
    sameTime(value.known_at, expected.known_at)
  );
}
export async function validateOutcomeAck(
  value: unknown,
  etag: string | null,
  p: PendingPackageOutcome,
  scope: PackageOutcomeScope,
  submission: PackageSubmissionView,
) {
  const view = validateOutcomeView(value, scope.bidId, scope.submissionId);
  await verifiedDetails(view, submission);
  if (p.kind === "verify") {
    const d =
      view.verification_details as PackageOutcomeVerificationDetails | null;
    if (
      view.id !== p.baseId ||
      !scoreMatches(view, p.score) ||
      view.supersedes_id !== p.score.supersedes_id ||
      view.verification_revision !== p.baseRevision + 1 ||
      etag !== outcomeVerificationEtag(view.id, p.baseRevision + 1) ||
      !d ||
      !same(d.request, p.body)
    )
      outcomeFailure();
  } else {
    const revision =
      p.kind === "register"
        ? 1
        : Number(p.etag!.slice(1, -1).split(":").at(-1)) + 1;
    if (
      !scoreMatches(view, p.body) ||
      view.supersedes_id !== p.baseId ||
      view.id === p.baseId ||
      view.verification !== "pending" ||
      view.verification_revision !== 0 ||
      view.verification_details !== null ||
      etag !== outcomeHeadEtag(scope.submissionId, revision)
    )
      outcomeFailure();
  }
  return view;
}
const terminalOutcomeCodes = new Set([
  "REVISION_CONFLICT",
  "OUTCOME_NOT_CURRENT",
  "OUTCOME_ALREADY_EXISTS",
  "OUTCOME_SUBMISSION_MISMATCH",
  "OUTCOME_TIME_INVALID",
  "INVALID_SCORE",
  "INVALID_SCORE_KIND",
  "INVALID_AMOUNT",
  "PACKAGE_OUTCOME_IDENTITY_MISMATCH",
  "PACKAGE_OUTCOME_AUTHORITY_MISMATCH",
  "PACKAGE_OUTCOME_AUTHORITY_MISSING",
  "PACKAGE_OUTCOME_SOURCE_INCOMPLETE",
  "PACKAGE_OUTCOME_SOURCE_INVALID",
  "PACKAGE_OUTCOME_SOURCE_MISMATCH",
  "PACKAGE_OUTCOME_TIME_INVALID",
  "PACKAGE_OUTCOME_SUBJECT_MISMATCH",
  "PACKAGE_OUTCOME_CAPACITY_EXCEEDED",
  "PACKAGE_OUTCOME_AUTHORITY_SOURCE_UNPROVEN",
  "PACKAGE_OUTCOME_AUTHORITY_SOURCE_INVALID",
  "PACKAGE_OUTCOME_AUTHORITY_SOURCE_CHANGED",
  "PACKAGE_OUTCOME_AUTHORITY_IDENTITY_MISMATCH",
  "PACKAGE_OUTCOME_AUTHORITY_ORIGINAL_CHANGED",
  "PACKAGE_OUTCOME_AUTHORITY_PARSE_CHANGED",
  "SUBMISSION_IDENTITY_CHANGED",
]);
export const definitiveOutcomeFailure = (error: unknown) =>
  error instanceof ApiError &&
  [409, 412, 422].includes(error.status) &&
  terminalOutcomeCodes.has(error.code);

export const packageOutcomeReason = (reason: string) =>
  (
    ({
      package_outcome_not_verified: "此成绩尚未完成核验",
      package_outcome_verification_unproven: "尚无完整的整包成绩核验凭据",
      package_outcome_authority_missing: "实交时未绑定招标依据包",
      package_outcome_identity_changed: "投标身份已变化，需要核对原实交身份",
      package_outcome_source_invalid: "官方结果来源当前不可用",
      package_outcome_source_no_longer_effective:
        "官方结果来源已撤回或不再生效",
      package_outcome_not_current: "已有更新的成绩记录，这条仅保留为历史",
      package_outcome_not_observed_at_as_of: "在所选统计时间尚未取得完整记录",
      package_outcome_binding_changed: "原整包绑定无法按原记录核对",
      package_outcome_authority_proof_changed: "原招标依据的有效性已变化",
      package_outcome_official_source_proof_changed:
        "官方成绩原件的来源状态已变化",
      package_outcome_source_proof_unproven: "原来源核验凭据无法还原",
      package_outcome_verification_changed: "当前核验记录与原凭据不符",
      package_outcome_subject_mismatch: "成绩与这次原实交身份不符",
      source_no_longer_effective: "来源已撤回或不再生效",
      PACKAGE_OUTCOME_AUTHORITY_MISSING: "原实交记录未绑定招标依据包",
      PACKAGE_OUTCOME_IDENTITY_UNVERIFIED: "原实交身份尚未核验",
    }) as Record<string, string>
  )[reason] ?? reason;
