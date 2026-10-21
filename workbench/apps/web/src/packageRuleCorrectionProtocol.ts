import type {
  PackageRequirementInventoryView,
  PackageRuleCorrectionAppliedView,
  PackageRuleCorrectionEvidenceDetail,
  PackageRuleCorrectionEvidencePage,
  PackageRuleCorrectionHistoryPage,
  PackageRuleCorrectionPreviewView,
  PackageRuleCorrectionRequest,
  PackageRuleCorrection_RuleAddition as RuleAddition,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
import {
  correctionBase,
  correctionDecimal,
  correctionEtag,
  correctionInteger as integer,
  correctionText as text,
  validCorrectionBase,
  validCorrectionRequest,
  type CorrectionBase,
  type CorrectionScope,
  type PendingCorrection,
} from "./packageRuleCorrectionRecovery";

export type CorrectionSemantic =
  PackageRuleCorrectionPreviewView["manifest"]["changes"][number]["after"];
export type CorrectionEvidenceEntry =
  PackageRuleCorrectionEvidencePage["items"][number];
export type CorrectionChange = PackageRuleCorrectionRequest["changes"][number];
export const correctionKindNames = {
  disqualification: "否决条款",
  mandatory: "必须响应",
  scoring: "评分条款",
  advisory: "提示条款",
};
export const correctionOperationNames = {
  add: "补充",
  replace: "替换",
  withdraw: "撤销",
};
export function correctionProtocolFailure(): never {
  throw new Error(
    "规则修订响应的清单、原页来源、摘要或操作回执无法核对。尚未确认保存成功，原请求保留。",
  );
}
function ordered(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(ordered);
  if (recordObject(value))
    return Object.fromEntries(
      Object.entries(value)
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([key, item]) => [key, ordered(item)]),
    );
  return value;
}
export const sameCorrectionValue = (a: unknown, b: unknown) =>
  JSON.stringify(ordered(a)) === JSON.stringify(ordered(b));
function ids(value: unknown, maximum = 10000): value is string[] {
  return (
    Array.isArray(value) &&
    value.length <= maximum &&
    value.every(executionId) &&
    new Set(value).size === value.length
  );
}
function strings(value: unknown, maximum = 100): value is string[] {
  return (
    Array.isArray(value) &&
    value.length <= maximum &&
    value.every((v) => text(v, 16000))
  );
}
function matchesScope(
  value: unknown,
  scope: CorrectionScope,
  inventoryId: string,
) {
  return (
    recordObject(value) &&
    exactKeys(value, ["bid_id", "package_id", "revision_id", "inventory_id"]) &&
    value.bid_id === scope.bidId &&
    value.package_id === scope.packageId &&
    value.revision_id === scope.revisionId &&
    value.inventory_id === inventoryId
  );
}
function matchesAuthority(value: unknown, base: CorrectionBase) {
  return (
    recordObject(value) &&
    value.revision_id === base.authorityRevisionId &&
    value.digest === base.authorityDigest &&
    value.identity_digest === base.identityDigest
  );
}
function matchesBase(value: unknown, base: CorrectionBase) {
  return (
    recordObject(value) &&
    value.inventory_digest === base.inventoryDigest &&
    value.rule_set_id === base.ruleSetId &&
    value.rule_set_digest === base.ruleSetDigest
  );
}
function extraction(value: unknown) {
  return (
    recordObject(value) &&
    executionId(value.inventory_id) &&
    executionSha(value.inventory_digest) &&
    executionId(value.rule_set_id) &&
    executionSha(value.rule_set_digest) &&
    executionId(value.extraction_result_id) &&
    executionSha(value.extraction_input_digest) &&
    executionSha(value.extraction_result_digest) &&
    value.extraction_range_status === "all_frozen_evidence_submitted" &&
    ["complete", "partial", "conflict"].includes(
      String(value.extraction_coverage),
    ) &&
    value.extraction_quality_status === "not_measured"
  );
}
export function correctionInventoryMatches(
  value: PackageRequirementInventoryView | null,
  scope: CorrectionScope,
) {
  const m = value?.manifest;
  return !!(
    m &&
    ["bid-package-requirements/2", "bid-package-requirements/3"].includes(
      m.version,
    ) &&
    executionId(m.id) &&
    m.bid_id === scope.bidId &&
    m.package_id === scope.packageId &&
    m.target_revision_id === scope.revisionId &&
    m.package_digest === scope.packageDigest &&
    value &&
    validCorrectionBase(correctionBase(value)) &&
    m.inventory_complete === false &&
    m.review_ready === false
  );
}
export function validCorrectionSemantic(
  value: unknown,
): value is CorrectionSemantic {
  return (
    recordObject(value) &&
    Object.hasOwn(correctionKindNames, String(value.kind)) &&
    text(value.statement, 16000) &&
    strings(value.conditions, 50) &&
    strings(value.exceptions, 50) &&
    (value.max_points === null || correctionDecimal(value.max_points)) &&
    ids(value.evidence_ids) &&
    value.evidence_ids.length > 0 &&
    recordObject(value.applicability_scope) &&
    ["effective", "needs_revalidation", "superseded"].includes(
      String(value.provenance_status),
    ) &&
    Array.isArray(value.bands) &&
    value.bands.length <= 100 &&
    value.bands.every(
      (band) =>
        recordObject(band) &&
        text(band.label, 8000) &&
        text(band.description, 8000) &&
        correctionDecimal(band.points) &&
        ids(band.evidence_ids, 50) &&
        band.evidence_ids.length > 0,
    )
  );
}
export function correctionRuleSemantic(
  snapshot: Record<string, unknown>,
): CorrectionSemantic | null {
  if (!validCorrectionSemantic(snapshot)) return null;
  return {
    kind: snapshot.kind,
    statement: snapshot.statement,
    conditions: snapshot.conditions,
    exceptions: snapshot.exceptions,
    max_points: snapshot.max_points,
    evidence_ids: snapshot.evidence_ids,
    bands: snapshot.bands,
    applicability_scope: snapshot.applicability_scope,
    provenance_status: snapshot.provenance_status,
  };
}
const decimalIdentity = (value: string | null) =>
  value === null
    ? null
    : value
        .replace(/^0+(?=\d)/, "")
        .replace(/(\.\d*?)0+$/, "$1")
        .replace(/\.$/, "");
function semanticIdentity(value: CorrectionSemantic) {
  return {
    ...value,
    max_points: decimalIdentity(value.max_points),
    bands: value.bands.map((band) => ({
      ...band,
      points: decimalIdentity(band.points),
    })),
  };
}
function additionMatches(value: CorrectionSemantic, rule: RuleAddition) {
  return sameCorrectionValue(
    semanticIdentity(value),
    semanticIdentity({
      kind: rule.kind,
      statement: rule.statement,
      conditions: rule.conditions,
      exceptions: rule.exceptions,
      max_points: rule.maximum,
      evidence_ids: [
        ...new Set(rule.evidence_quotes.map((item) => item.evidence_id)),
      ],
      bands: rule.bands,
      applicability_scope: rule.scope,
      provenance_status: "effective",
    }),
  );
}
function previous(value: unknown) {
  return (
    value === null ||
    (recordObject(value) && executionId(value.id) && executionSha(value.digest))
  );
}
function evidenceItem(value: unknown) {
  return (
    recordObject(value) &&
    executionId(value.evidence_id) &&
    text(value.member_id) &&
    executionId(value.document_version_id) &&
    executionSha(value.file_digest) &&
    executionId(value.parse_run_id) &&
    integer(value.physical_page, 1) &&
    integer(value.ordinal) &&
    ["text", "table", "visual_observation"].includes(String(value.kind)) &&
    executionSha(value.evidence_digest) &&
    strings(value.part_ids) &&
    value.part_ids.length > 0 &&
    new Set(value.part_ids).size === value.part_ids.length
  );
}
function page(value: Record<string, unknown>) {
  return (
    typeof value.has_more === "boolean" &&
    (value.has_more
      ? text(value.next_cursor, 4096)
      : value.next_cursor === null)
  );
}
export function validateCorrectionEvidencePage(
  value: unknown,
  scope: CorrectionScope,
  base: CorrectionBase,
): PackageRuleCorrectionEvidencePage {
  if (
    !recordObject(value) ||
    !matchesScope(value.scope, scope, base.inventoryId) ||
    value.inventory_digest !== base.inventoryDigest ||
    !matchesAuthority(value.authority, base) ||
    !Array.isArray(value.items) ||
    value.items.length > 100 ||
    !value.items.every(
      (item) =>
        evidenceItem(item) &&
        recordObject(item) &&
        typeof item.excerpt === "string",
    ) ||
    new Set(
      value.items.map((item) => (item as CorrectionEvidenceEntry).evidence_id),
    ).size !== value.items.length ||
    !page(value)
  )
    correctionProtocolFailure();
  return value as PackageRuleCorrectionEvidencePage;
}
export async function correctionEvidenceTextDigest(text: string) {
  const bytes = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(text),
  );
  return [...new Uint8Array(bytes)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}
export async function validateCorrectionEvidenceDetail(
  value: unknown,
  scope: CorrectionScope,
  base: CorrectionBase,
  expected: CorrectionEvidenceEntry,
): Promise<PackageRuleCorrectionEvidenceDetail> {
  if (
    !recordObject(value) ||
    !matchesScope(value.scope, scope, base.inventoryId) ||
    value.inventory_digest !== base.inventoryDigest ||
    !matchesAuthority(value.authority, base) ||
    !evidenceItem(value.evidence) ||
    !recordObject(value.evidence) ||
    typeof value.evidence.text_content !== "string"
  )
    correctionProtocolFailure();
  const detail = value as PackageRuleCorrectionEvidenceDetail;
  const identity = (
    item:
      | CorrectionEvidenceEntry
      | PackageRuleCorrectionEvidenceDetail["evidence"],
  ) => ({
    evidence_id: item.evidence_id,
    member_id: item.member_id,
    document_version_id: item.document_version_id,
    parse_run_id: item.parse_run_id,
    physical_page: item.physical_page,
    ordinal: item.ordinal,
    kind: item.kind,
    evidence_digest: item.evidence_digest,
    file_digest: item.file_digest,
    part_ids: item.part_ids,
  });
  if (!sameCorrectionValue(identity(expected), identity(detail.evidence)))
    correctionProtocolFailure();
  if (
    (await correctionEvidenceTextDigest(detail.evidence.text_content)) !==
    detail.evidence.evidence_digest
  )
    correctionProtocolFailure();
  return detail;
}
export async function validateCorrectionPreview(
  value: unknown,
  scope: CorrectionScope,
  inventory: PackageRequirementInventoryView,
  request: PackageRuleCorrectionRequest,
): Promise<PackageRuleCorrectionPreviewView> {
  if (
    !recordObject(value) ||
    !recordObject(value.manifest) ||
    !executionSha(value.digest)
  )
    correctionProtocolFailure();
  const result = value as PackageRuleCorrectionPreviewView;
  const m = result.manifest,
    base = correctionBase(inventory);
  if (
    m.version !== "package-rule-correction-preview/1" ||
    !matchesScope(m.scope, scope, base.inventoryId) ||
    !matchesBase(m.base, base) ||
    !matchesAuthority(m.authority, base) ||
    !extraction(m.extraction_basis) ||
    !previous(m.previous) ||
    !integer(m.sequence_no, 1, 32) ||
    !executionSha(m.policy_digest) ||
    !executionSha(m.source_snapshot_digest) ||
    !sameCorrectionValue(m.request, request) ||
    !validCorrectionRequest(m.request, scope.bidId) ||
    m.request_digest !== (await jsonDigest(request)) ||
    result.digest !== (await jsonDigest(m)) ||
    m.source_snapshot_digest !==
      (await jsonDigest(inventory.manifest.source_snapshot)) ||
    m.inventory_complete !== false ||
    m.review_ready !== false ||
    m.original_bytes_verified !== false ||
    !strings(m.limitations, 100) ||
    !Array.isArray(m.changes) ||
    m.changes.length !== request.changes.length ||
    !recordObject(m.counts)
  )
    correctionProtocolFailure();
  const raw = inventory.manifest as unknown as Record<string, unknown>;
  const root =
    raw.version === "bid-package-requirements/3"
      ? raw.extraction_basis
      : {
          inventory_id: base.inventoryId,
          inventory_digest: base.inventoryDigest,
          rule_set_id: base.ruleSetId,
          rule_set_digest: base.ruleSetDigest,
          extraction_result_id: raw.extraction_result_id,
          extraction_input_digest: raw.extraction_input_digest,
          extraction_result_digest: raw.extraction_result_digest,
          extraction_range_status: raw.extraction_range_status,
          extraction_coverage: raw.extraction_coverage,
          extraction_quality_status: raw.extraction_quality_status,
        };
  if (!sameCorrectionValue(m.extraction_basis, root))
    correctionProtocolFailure();
  const counts = m.counts;
  const added = request.changes.filter((item) => item.op === "add").length;
  const replaced = request.changes.filter(
    (item) => item.op === "replace",
  ).length;
  const withdrawn = request.changes.filter(
    (item) => item.op === "withdraw",
  ).length;
  if (
    Object.values(counts).some((value) => !integer(value, 0, 10000)) ||
    counts.before !== base.ruleCount ||
    counts.added !== added ||
    counts.replaced !== replaced ||
    counts.withdrawn !== withdrawn ||
    counts.after !== counts.before + added ||
    counts.carried !== counts.before - replaced - withdrawn ||
    counts.active_after > counts.after
  )
    correctionProtocolFailure();
  m.changes.forEach((change, index) => {
    const requested = request.changes[index];
    const binding =
      requested.op === "add"
        ? null
        : inventory.manifest.requirements.find(
            (item) =>
              item.rule_id === requested.rule_id &&
              item.rule_digest === requested.rule_digest,
          );
    const original = binding
      ? correctionRuleSemantic(binding.rule_snapshot)
      : null;
    const quotes =
      requested.op === "withdraw"
        ? requested.evidence_quotes
        : requested.rule.evidence_quotes;
    if (
      change.index !== index ||
      change.op !== requested.op ||
      !validCorrectionSemantic(change.after) ||
      (requested.op !== "withdraw" &&
        change.after.applicability_scope.bid_id !== scope.bidId) ||
      (requested.op === "add"
        ? change.rule_id !== null ||
          change.rule_digest !== null ||
          change.before !== null
        : change.rule_id !== requested.rule_id ||
          change.rule_digest !== requested.rule_digest ||
          !original ||
          !validCorrectionSemantic(change.before) ||
          !sameCorrectionValue(
            semanticIdentity(change.before),
            semanticIdentity(original),
          )) ||
      (requested.op === "withdraw"
        ? !change.before ||
          !sameCorrectionValue(
            semanticIdentity(change.after),
            semanticIdentity({
              ...change.before,
              provenance_status: "superseded",
            }),
          )
        : !additionMatches(change.after, requested.rule)) ||
      !Array.isArray(change.quotes) ||
      change.quotes.length !== quotes.length ||
      !change.quotes.every((quote, quoteIndex) => {
        const expected = quotes[quoteIndex];
        return (
          quote.evidence_id === expected.evidence_id &&
          quote.quote === expected.quote &&
          text(quote.member_id) &&
          executionId(quote.document_version_id) &&
          executionId(quote.parse_run_id) &&
          integer(quote.physical_page, 1) &&
          executionSha(quote.evidence_digest) &&
          strings(quote.part_ids) &&
          quote.part_ids.length > 0
        );
      })
    )
      correctionProtocolFailure();
  });
  return result;
}
export function validateCorrectionHistory(
  value: unknown,
  scope: CorrectionScope,
  inventoryId: string,
): PackageRuleCorrectionHistoryPage {
  if (
    !recordObject(value) ||
    !matchesScope(value.scope, scope, inventoryId) ||
    !Array.isArray(value.items) ||
    value.items.length > 100 ||
    !page(value) ||
    !value.items.every(
      (item) =>
        recordObject(item) &&
        executionId(item.id) &&
        executionSha(item.digest) &&
        typeof item.created_at === "string" &&
        Number.isFinite(Date.parse(item.created_at)) &&
        executionId(item.actor_id) &&
        executionId(item.base_inventory_id) &&
        executionId(item.result_inventory_id) &&
        ["added", "replaced", "withdrawn"].every((key) =>
          integer(item[key], 0, 10000),
        ),
    ) ||
    new Set(value.items.map((item) => (item as { id: string }).id)).size !==
      value.items.length
  )
    correctionProtocolFailure();
  return value as PackageRuleCorrectionHistoryPage;
}
/** PostgreSQL summaries may retain an offset while the signed manifest uses UTC. */
export function sameCorrectionInstant(left: string, right: string) {
  const format =
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.(\d{1,6}))?(?:Z|[+-]\d{2}:\d{2})$/;
  const one = format.exec(left),
    two = format.exec(right);
  return (
    !!one &&
    !!two &&
    Number.isFinite(Date.parse(left)) &&
    Date.parse(left) === Date.parse(right) &&
    (one[1] ?? "").padEnd(6, "0").slice(3) ===
      (two[1] ?? "").padEnd(6, "0").slice(3)
  );
}
export async function validateCorrectionApplied(
  value: unknown,
  scope: CorrectionScope,
  expected: {
    base: CorrectionBase;
    id?: string;
    digest?: string;
    pending?: PendingCorrection;
  },
  etag: string | null,
): Promise<PackageRuleCorrectionAppliedView> {
  if (
    !recordObject(value) ||
    !recordObject(value.correction) ||
    !recordObject(value.correction.manifest) ||
    !recordObject(value.inventory) ||
    !recordObject(value.inventory.manifest) ||
    !recordObject(value.command)
  )
    correctionProtocolFailure();
  const result = value as PackageRuleCorrectionAppliedView;
  const correction = result.correction,
    m = correction.manifest,
    base = expected.base,
    command = result.command,
    inventory = result.inventory,
    next = inventory.manifest;
  if (
    m.version !== "package-rule-correction/1" ||
    !executionId(m.id) ||
    (expected.id && m.id !== expected.id) ||
    !executionSha(correction.digest) ||
    (expected.digest && correction.digest !== expected.digest) ||
    !matchesScope(m.scope, scope, base.inventoryId) ||
    !matchesBase(m.base, base) ||
    !matchesAuthority(m.authority, base) ||
    !extraction(m.extraction_basis) ||
    !previous(m.previous) ||
    !integer(m.sequence_no, 1, 32) ||
    !executionSha(m.policy_digest) ||
    !executionSha(m.preview_digest) ||
    !executionSha(m.source_snapshot_digest) ||
    !validCorrectionRequest(m.request, scope.bidId) ||
    m.request.base_inventory_digest !== base.inventoryDigest ||
    m.request.base_rule_set_digest !== base.ruleSetDigest ||
    m.request_digest !== (await jsonDigest(m.request)) ||
    correction.digest !== (await jsonDigest(m)) ||
    !executionId(m.actor_id) ||
    !executionId(m.command_id) ||
    typeof m.created_at !== "string" ||
    !Number.isFinite(Date.parse(m.created_at)) ||
    command.command_id !== m.command_id ||
    command.actor_id !== m.actor_id ||
    !text(command.idempotency_key, 128) ||
    !correctionEtag(command.if_match) ||
    !sameCorrectionValue(command.request, {
      request: m.request,
      preview_digest: m.preview_digest,
    }) ||
    command.request_digest !==
      (await jsonDigest({
        body: {
          scope: [
            scope.bidId,
            scope.packageId,
            scope.revisionId,
            base.inventoryId,
          ],
          ...command.request,
        },
        if_match: command.if_match,
      }))
  )
    correctionProtocolFailure();
  if (
    expected.pending &&
    (command.actor_id !== scope.memberId ||
      command.idempotency_key !== expected.pending.key ||
      command.if_match !== expected.pending.etag ||
      !sameCorrectionValue(command.request, expected.pending.body))
  )
    correctionProtocolFailure();
  if (
    !recordObject(m.result) ||
    !executionId(m.result.inventory_id) ||
    !executionId(m.result.rule_set_id) ||
    !executionSha(m.result.rule_set_digest) ||
    !executionSha(m.result.rules_digest) ||
    !integer(m.result.rule_count, 0, 10000) ||
    next.version !== "bid-package-requirements/3" ||
    next.id !== m.result.inventory_id ||
    next.bid_id !== scope.bidId ||
    next.package_id !== scope.packageId ||
    next.target_revision_id !== scope.revisionId ||
    next.package_digest !== scope.packageDigest ||
    next.predecessor_digest !== base.inventoryDigest ||
    next.revision !== base.inventoryRevision + 1 ||
    next.rule_set_id !== m.result.rule_set_id ||
    next.rule_set_digest !== m.result.rule_set_digest ||
    next.authority_revision_id !== base.authorityRevisionId ||
    next.authority_digest !== base.authorityDigest ||
    next.identity_digest !== base.identityDigest ||
    next.actor_id !== m.actor_id ||
    next.inventory_complete !== false ||
    next.review_ready !== false ||
    !Array.isArray(next.requirements) ||
    next.requirements.length !== m.result.rule_count ||
    !executionSha(inventory.digest) ||
    inventory.digest !== (await jsonDigest(next)) ||
    etag !== `"requirement-inventory:${scope.revisionId}:${inventory.digest}"`
  )
    correctionProtocolFailure();
  const derived = next as unknown as Record<string, unknown>;
  if (
    !sameCorrectionValue(derived.extraction_basis, m.extraction_basis) ||
    !recordObject(derived.human_derivation) ||
    derived.human_derivation.head_id !== m.id ||
    derived.human_derivation.head_digest !== correction.digest ||
    derived.human_derivation.length !== m.sequence_no
  )
    correctionProtocolFailure();
  if (
    !Array.isArray(m.mappings) ||
    m.mappings.length !== base.ruleCount ||
    !Array.isArray(m.additions) ||
    !Array.isArray(m.decision_bindings)
  )
    correctionProtocolFailure();
  const added = m.request.changes.filter(
    (change) => change.op === "add",
  ).length;
  if (
    m.additions.length !== added ||
    m.result.rule_count !== base.ruleCount + added ||
    new Set(next.requirements.map((binding) => binding.rule_id)).size !==
      next.requirements.length
  )
    correctionProtocolFailure();
  for (const mapping of m.mappings) {
    const binding = next.requirements.find(
      (item) =>
        item.rule_id === mapping.to_rule_id &&
        item.rule_digest === mapping.to_rule_digest,
    );
    if (
      !executionId(mapping.from_rule_id) ||
      !executionSha(mapping.from_rule_digest) ||
      !binding ||
      !["carry", "replace", "withdraw"].includes(mapping.op)
    )
      correctionProtocolFailure();
    if (mapping.op === "carry") {
      if (mapping.change_index !== null) correctionProtocolFailure();
    } else {
      const change =
        mapping.change_index === null
          ? null
          : m.request.changes[mapping.change_index];
      if (
        !change ||
        change.op !== mapping.op ||
        change.rule_id !== mapping.from_rule_id ||
        change.rule_digest !== mapping.from_rule_digest
      )
        correctionProtocolFailure();
      if (mapping.op === "replace" && binding.annotation.mapped)
        correctionProtocolFailure();
      if (
        mapping.op === "withdraw" &&
        (binding.rule_snapshot.provenance_status !== "superseded" ||
          binding.decision_snapshot?.decision !== "rejected")
      )
        correctionProtocolFailure();
    }
  }
  for (const addition of m.additions) {
    const binding = next.requirements.find(
      (item) =>
        item.rule_id === addition.to_rule_id &&
        item.rule_digest === addition.to_rule_digest,
    );
    if (
      m.request.changes[addition.change_index]?.op !== "add" ||
      !binding ||
      binding.annotation.mapped ||
      binding.decision_snapshot?.decision !== "confirmed"
    )
      correctionProtocolFailure();
  }
  return result;
}
