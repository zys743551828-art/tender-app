import type {
  PackageReviewHumanDecisionCurrent,
  PackageReviewHumanDecisionPage,
  PackageReviewHumanDecisionView,
  PackageReviewRunView,
  SavePackageReviewHumanDecision,
} from "./contracts";
import type { DependencyProps } from "./inputDependencyProtocol";
import type {
  PackageReviewQuote,
  PackageReviewRow,
} from "./packageReviewProtocol";
import { packageReviewPath } from "./packageReviewProtocol";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
import { frozenManifestDigest } from "./packageFrozenInput";

export type PackageReviewDecisionProps = DependencyProps & {
  run: PackageReviewRunView;
};
export type PackageReviewDecisionState =
  SavePackageReviewHumanDecision["state"];
export type PendingPackageReviewDecision = {
  key: string;
  requirementId: string;
  previousSequence: number | null;
  body: SavePackageReviewHumanDecision;
};
export const packageReviewDecisionStates = [
  "confirmed",
  "rejected",
  "needs_review",
] as const;
export const packageReviewDecisionLabels = {
  confirmed: "确认此项判断",
  rejected: "不采用此项判断",
  needs_review: "需要复查",
};
export const packageReviewDecisionsPath = (
  p: PackageReviewDecisionProps,
  requirementId?: string,
) =>
  `${packageReviewPath(p)}/${p.run.id}${requirementId ? `/requirements/${requirementId}` : ""}/human-decisions`;

const positive = (v: unknown): v is number =>
  Number.isSafeInteger(v) && Number(v) > 0;
const reason = (v: unknown): v is string =>
  typeof v === "string" && !!v.trim() && Array.from(v).length <= 2000;
const time = (v: unknown): v is string =>
  typeof v === "string" &&
  /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z$/.test(v) &&
  Number.isFinite(Date.parse(v)) &&
  new Date(v).toISOString().slice(0, 19) === v.slice(0, 19);
const same = (value: unknown, expected: Record<string, unknown>) =>
  recordObject(value) &&
  exactKeys(value, Object.keys(expected)) &&
  Object.entries(expected).every(([key, item]) => value[key] === item);
function binding(value: Record<string, unknown>, run: PackageReviewRunView) {
  return (
    !!run.result &&
    run.operation.state === "succeeded" &&
    same(value.scope, run.scope) &&
    value.frozen_input_id === run.frozen_input_id &&
    value.execution_input_id === run.execution_input_id &&
    value.run_id === run.id &&
    value.result_digest === run.result.digest
  );
}
const validHead = (value: unknown) =>
  value === null ||
  (recordObject(value) &&
    exactKeys(value, ["id", "digest"]) &&
    executionId(value.id) &&
    executionSha(value.digest));
const sameHead = (
  a: unknown,
  b: SavePackageReviewHumanDecision["expected_head"],
) => (b === null ? a === null : same(a, b));
export const packageReviewQuoteKey = (q: PackageReviewQuote) =>
  JSON.stringify([
    q.package_role,
    q.member_id,
    q.document_version_id,
    q.parse_run_id,
    q.physical_page,
    q.part_ids,
    q.evidence_id,
    q.evidence_digest,
    q.quote,
  ]);
export function packageReviewDecisionQuotes(row: PackageReviewRow) {
  return Array.from(
    new Map(
      [...row.target_quotes, ...row.authority_quotes].map((q) => [
        packageReviewQuoteKey(q),
        q,
      ]),
    ).values(),
  );
}
function sameQuote(value: unknown, quote: PackageReviewQuote) {
  return (
    recordObject(value) &&
    exactKeys(value, Object.keys(quote)) &&
    Object.entries(quote).every(([key, item]) =>
      key === "part_ids"
        ? Array.isArray(value.part_ids) &&
          value.part_ids.length === quote.part_ids.length &&
          value.part_ids.every((part, index) => part === quote.part_ids[index])
        : value[key] === item,
    )
  );
}
function validQuotes(
  value: unknown,
  row: PackageReviewRow,
): value is PackageReviewQuote[] {
  if (!Array.isArray(value) || value.length > 40) return false;
  const allowed = packageReviewDecisionQuotes(row);
  const indexes = value.map((quote) =>
    allowed.findIndex((original) => sameQuote(quote, original)),
  );
  return (
    indexes.every((index) => index >= 0) &&
    new Set(indexes).size === indexes.length
  );
}
export function validPackageReviewDecisionBody(
  value: unknown,
  run: PackageReviewRunView,
  row: PackageReviewRow,
): value is SavePackageReviewHumanDecision {
  return (
    recordObject(value) &&
    exactKeys(value, [
      "result_digest",
      "row_digest",
      "expected_head",
      "state",
      "reason",
      "selected_quotes",
    ]) &&
    value.result_digest === run.result?.digest &&
    executionSha(value.row_digest) &&
    validHead(value.expected_head) &&
    packageReviewDecisionStates.includes(
      value.state as PackageReviewDecisionState,
    ) &&
    reason(value.reason) &&
    validQuotes(value.selected_quotes, row)
  );
}
export function validPendingPackageReviewDecision(
  value: unknown,
  run: PackageReviewRunView,
): value is PendingPackageReviewDecision {
  if (
    !recordObject(value) ||
    !exactKeys(value, ["key", "requirementId", "previousSequence", "body"]) ||
    !executionId(value.key) ||
    !executionId(value.requirementId)
  )
    return false;
  const row = run.result?.manifest.matrix.find(
    (item) => item.requirement_id === value.requirementId,
  );
  return (
    !!row &&
    validPackageReviewDecisionBody(value.body, run, row) &&
    (value.body.expected_head === null
      ? value.previousSequence === null
      : positive(value.previousSequence) &&
        value.previousSequence < Number.MAX_SAFE_INTEGER)
  );
}
function fail(): never {
  throw new Error(
    "人工记录与原核查结果、条款、引用或版本不符，未采用其他判断；未确认的原请求仍保留。",
  );
}

export async function validatePackageReviewDecision(
  value: unknown,
  run: PackageReviewRunView,
  row: PackageReviewRow,
  pending?: PendingPackageReviewDecision,
  actor?: string,
): Promise<PackageReviewHumanDecisionView> {
  if (
    !recordObject(value) ||
    !exactKeys(value, ["manifest", "digest"]) ||
    !executionSha(value.digest) ||
    !recordObject(value.manifest)
  )
    return fail();
  const m = value.manifest;
  if (
    !exactKeys(m, [
      "version",
      "id",
      "actor_id",
      "created_at",
      "sequence_no",
      "scope",
      "frozen_input_id",
      "execution_input_id",
      "run_id",
      "requirement_id",
      "input_digest",
      "result_digest",
      "row_digest",
      "previous_head",
      "state",
      "reason",
      "selected_quotes",
      "inventory_complete",
      "formal_scoring_eligible",
      "submission_eligible",
    ]) ||
    m.version !== "package-review-human-decision/1" ||
    ![m.id, m.actor_id].every(executionId) ||
    !time(m.created_at) ||
    !positive(m.sequence_no) ||
    !binding(m, run) ||
    m.requirement_id !== row.requirement_id ||
    m.input_digest !== run.input_digest ||
    m.row_digest !== (await frozenManifestDigest(row)) ||
    !validHead(m.previous_head) ||
    (m.sequence_no === 1) !== (m.previous_head === null) ||
    !packageReviewDecisionStates.includes(
      m.state as PackageReviewDecisionState,
    ) ||
    !reason(m.reason) ||
    !validQuotes(m.selected_quotes, row) ||
    m.inventory_complete !== false ||
    m.formal_scoring_eligible !== false ||
    m.submission_eligible !== false ||
    (await frozenManifestDigest(m)) !== value.digest
  )
    return fail();
  if (
    pending &&
    (!validPendingPackageReviewDecision(pending, run) ||
      pending.requirementId !== row.requirement_id ||
      m.actor_id !== actor ||
      m.row_digest !== pending.body.row_digest ||
      !sameHead(m.previous_head, pending.body.expected_head) ||
      m.sequence_no !== (pending.previousSequence ?? 0) + 1 ||
      m.state !== pending.body.state ||
      m.reason !== pending.body.reason ||
      (await frozenManifestDigest(m.selected_quotes)) !==
        (await frozenManifestDigest(pending.body.selected_quotes)))
  )
    return fail();
  return value as unknown as PackageReviewHumanDecisionView;
}

export async function validatePackageReviewDecisionCurrent(
  value: unknown,
  run: PackageReviewRunView,
): Promise<PackageReviewHumanDecisionCurrent> {
  if (
    !recordObject(value) ||
    !exactKeys(value, [
      "scope",
      "frozen_input_id",
      "execution_input_id",
      "run_id",
      "result_digest",
      "items",
    ]) ||
    !binding(value, run) ||
    !Array.isArray(value.items)
  )
    return fail();
  const rows = new Map(
    run.result!.manifest.matrix.map((row) => [row.requirement_id, row]),
  );
  if (
    value.items.length !== rows.size ||
    value.items.length < 1 ||
    value.items.length > 400
  )
    return fail();
  const seen = new Set<string>();
  await Promise.all(
    value.items.map(async (item) => {
      if (
        !recordObject(item) ||
        !exactKeys(item, ["requirement_id", "row_digest", "current"]) ||
        !executionId(item.requirement_id) ||
        seen.has(item.requirement_id)
      )
        return fail();
      seen.add(item.requirement_id);
      const row = rows.get(item.requirement_id);
      if (!row || item.row_digest !== (await frozenManifestDigest(row)))
        return fail();
      const head = item.current;
      if (
        head !== null &&
        (!recordObject(head) ||
          !exactKeys(head, [
            "id",
            "digest",
            "sequence_no",
            "actor_id",
            "created_at",
            "state",
            "reason",
          ]) ||
          ![head.id, head.actor_id].every(executionId) ||
          !executionSha(head.digest) ||
          !positive(head.sequence_no) ||
          !time(head.created_at) ||
          !packageReviewDecisionStates.includes(
            head.state as PackageReviewDecisionState,
          ) ||
          !reason(head.reason))
      )
        return fail();
    }),
  );
  return value as unknown as PackageReviewHumanDecisionCurrent;
}

export async function validatePackageReviewDecisionPage(
  value: unknown,
  run: PackageReviewRunView,
  row: PackageReviewRow,
): Promise<PackageReviewHumanDecisionPage> {
  if (
    !recordObject(value) ||
    !exactKeys(value, [
      "scope",
      "frozen_input_id",
      "execution_input_id",
      "run_id",
      "result_digest",
      "requirement_id",
      "row_digest",
      "items",
      "has_more",
      "next_cursor",
    ]) ||
    !binding(value, run) ||
    value.requirement_id !== row.requirement_id ||
    value.row_digest !== (await frozenManifestDigest(row)) ||
    !Array.isArray(value.items) ||
    value.items.length > 20 ||
    typeof value.has_more !== "boolean" ||
    (value.has_more
      ? !value.items.length ||
        typeof value.next_cursor !== "string" ||
        !value.next_cursor ||
        value.next_cursor.length > 4096
      : value.next_cursor !== null)
  )
    return fail();
  const items = await Promise.all(
    value.items.map((item) => validatePackageReviewDecision(item, run, row)),
  );
  if (new Set(items.map((item) => item.manifest.id)).size !== items.length)
    return fail();
  if (
    items.some(
      (item, index) =>
        index > 0 &&
        (items[index - 1].manifest.sequence_no !==
          item.manifest.sequence_no + 1 ||
          !sameHead(items[index - 1].manifest.previous_head, {
            id: item.manifest.id,
            digest: item.digest,
          })),
    )
  )
    return fail();
  return value as unknown as PackageReviewHumanDecisionPage;
}
