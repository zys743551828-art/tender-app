import { ApiError } from "./api";
import type {
  BidPackageStoredView,
  FreezePackageTechnicalScope,
  PackageRequirementInventoryView,
  PackageTechnicalScopeApplied,
  PackageTechnicalScopeContext,
  PackageTechnicalScopePage,
  PackageTechnicalScopePreview,
  PackageTechnicalScopeRequest,
  PackageTechnicalScopeView,
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
import {
  validatePackageNavigationInventory,
  validatePackageNavigationView,
} from "./packageNavigation";

export type TechnicalScopeBase = {
  bidId: string;
  packageId: string;
  revisionId: string;
};
export type TechnicalScope = TechnicalScopeBase & {
  memberId: string;
  inventoryId: string;
  packageDigest: string;
  inventoryDigest: string;
  authorityRevisionId: string;
  authorityDigest: string;
  identityDigest: string;
  ruleSetId: string;
  ruleSetDigest: string;
};
export type TechnicalPending = {
  key: string;
  body: FreezePackageTechnicalScope;
  etag: string;
  expected: { context_digest: string; method_digest: string };
};
export type TechnicalCommand = Omit<TechnicalPending, "key">;
export type TechnicalHistoryEntry = PackageTechnicalScopePage["items"][number];
type Manifest = PackageTechnicalScopePreview["manifest"];

export const technicalFlags = [
  "inventory_complete",
  "scoring_ready",
  "formal_scoring_eligible",
  "model_execution_enabled",
  "training_eligible",
] as const;
export const technicalLimits = {
  members: 500,
  parts: 2000,
  rules: 1000,
  source_rows: 20000,
  blocks: 100000,
  pages: 100000,
  request_bytes: 1024 * 1024,
  snapshot_bytes: 32 * 1024 * 1024,
  original_bytes: 1024 * 1024 * 1024,
};
const methodSources = [
  "packages/domain/package_technical_scope.py",
  "packages/domain/bid_package_technical_scope_repository.py",
  "packages/domain/bid_package_technical_scope_service.py",
  "packages/contracts/package_technical_scope_api.py",
  "packages/contracts/sql/bid-package-technical-scopes.sql",
  "packages/domain/bid_package_review_documents.py",
  "packages/domain/bid_package_repository.py",
  "packages/rag/indexing.py",
];
const timing = {
  purpose: "current_prebid",
  historical_as_of: null,
  submitted_at: null,
  label_known_at: null,
  training_frozen_at: null,
  submission_split_at: null,
  label_available_as_of: null,
  historical_qualification: "not_established",
};
export const technicalScopePath = (scope: TechnicalScopeBase) =>
  `/bids/${scope.bidId}/packages/${scope.packageId}/revisions/${scope.revisionId}`;
export const technicalContextPath = (scope: TechnicalScope) =>
  `${technicalScopePath(scope)}/technical-scope-context?inventory_id=${scope.inventoryId}`;
export const technicalSame = same;
export function technicalFailure(message?: string): never {
  throw new Error(
    message ??
      "技术范围的准确包、清单、原页证据或回执无法核对。尚未确认保存成功，原请求仍保留。",
  );
}
export const technicalText = (
  value: unknown,
  max = 2000,
  blank = false,
): value is string =>
  typeof value === "string" &&
  (blank || !!value.trim()) &&
  Array.from(value).length <= max &&
  !value.includes("\0") &&
  !/[\uD800-\uDFFF]/u.test(value);
const integer = (value: unknown, min = 0): value is number =>
  Number.isSafeInteger(value) && Number(value) >= min;
function uniqueStrings(
  value: unknown,
  max = technicalLimits.parts,
): value is string[] {
  return (
    Array.isArray(value) &&
    value.length <= max &&
    value.every((v) => technicalText(v, 200)) &&
    new Set(value).size === value.length
  );
}
function instant(value: unknown) {
  try {
    const normalized = historicalDateTime(value, "范围记录时间");
    return (
      BigInt(Date.parse(normalized)) * 1000n +
      BigInt((/\.(\d{6})/.exec(normalized)?.[1] ?? "000000").slice(3))
    );
  } catch {
    return null;
  }
}
const flags = (value: Record<string, unknown>) =>
  technicalFlags.every((key) => value[key] === false);
function bounded(value: unknown, limit = technicalLimits.snapshot_bytes) {
  let count = 0;
  const pending: [unknown, number][] = [[value, 0]];
  while (pending.length) {
    const [v, depth] = pending.pop()!;
    if (++count > 2000000 || depth > 80) technicalFailure();
    if (Array.isArray(v))
      pending.push(...v.map((child): [unknown, number] => [child, depth + 1]));
    else if (object(v))
      for (const [key, child] of Object.entries(v)) {
        if (!technicalText(key, limit, true)) technicalFailure();
        pending.push([child, depth + 1]);
      }
    else if (typeof v === "string") {
      if (!technicalText(v, limit, true)) technicalFailure();
    } else if (
      v !== null &&
      typeof v !== "boolean" &&
      !integer(v, -Number.MAX_SAFE_INTEGER)
    )
      technicalFailure();
  }
  if (new TextEncoder().encode(JSON.stringify(value)).length > limit)
    technicalFailure("技术范围超过浏览器完整核对容量，未截断或发送部分内容。");
}
export function assertTechnicalScope(scope: TechnicalScope): void {
  if (
    !object(scope) ||
    !exactKeys(scope, [
      "bidId",
      "memberId",
      "packageId",
      "revisionId",
      "inventoryId",
      "packageDigest",
      "inventoryDigest",
      "authorityRevisionId",
      "authorityDigest",
      "identityDigest",
      "ruleSetId",
      "ruleSetDigest",
    ]) ||
    ![
      scope.bidId,
      scope.memberId,
      scope.packageId,
      scope.revisionId,
      scope.inventoryId,
      scope.authorityRevisionId,
      scope.ruleSetId,
    ].every(uuid) ||
    ![
      scope.packageDigest,
      scope.inventoryDigest,
      scope.authorityDigest,
      scope.identityDigest,
      scope.ruleSetDigest,
    ].every(sha)
  )
    technicalFailure();
}
export function technicalSelection(
  bidId: string,
  memberId: string,
  target: BidPackageStoredView,
  inventory: PackageRequirementInventoryView,
): TechnicalScope {
  const tm = target.manifest,
    im = inventory.manifest;
  const scope: TechnicalScope = {
    bidId,
    memberId,
    packageId: tm.package_id,
    revisionId: tm.revision_id,
    inventoryId: im.id,
    packageDigest: target.digest,
    inventoryDigest: inventory.digest,
    authorityRevisionId: im.authority_revision_id,
    authorityDigest: im.authority_digest,
    identityDigest: im.identity_digest,
    ruleSetId: im.rule_set_id,
    ruleSetDigest: im.rule_set_digest,
  };
  assertTechnicalScope(scope);
  if (
    tm.kind !== "bid" ||
    tm.scope.bid_id !== bidId ||
    im.bid_id !== bidId ||
    im.package_id !== scope.packageId ||
    im.target_revision_id !== scope.revisionId ||
    im.package_digest !== target.digest ||
    im.identity_digest !== target.identity.digest
  )
    technicalFailure();
  return scope;
}
function basis(scope: TechnicalScope) {
  return {
    package_digest: scope.packageDigest,
    authority_revision_id: scope.authorityRevisionId,
    authority_digest: scope.authorityDigest,
    inventory_digest: scope.inventoryDigest,
    rule_set_id: scope.ruleSetId,
    rule_set_digest: scope.ruleSetDigest,
    identity_digest: scope.identityDigest,
  };
}
async function validateMethod(value: unknown): Promise<Manifest["method"]> {
  if (
    !object(value) ||
    !exactKeys(value, ["version", "digest", "sources", "limits"]) ||
    value.version !== "package-technical-scope-policy/1" ||
    !sha(value.digest) ||
    !object(value.sources) ||
    !exactKeys(value.sources, methodSources) ||
    !Object.values(value.sources).every(sha) ||
    !same(value.limits, technicalLimits) ||
    (await jsonDigest({
      version: value.version,
      limits: value.limits,
      sources: value.sources,
    })) !== value.digest
  )
    technicalFailure();
  return value as Manifest["method"];
}
async function validateGaps(
  value: unknown,
): Promise<Manifest["coverage"]["gaps"]> {
  if (
    !Array.isArray(value) ||
    new Set(value.map((v) => v?.id)).size !== value.length
  )
    technicalFailure();
  for (const gap of value) {
    if (
      !object(gap) ||
      !exactKeys(gap, ["id", "code", "subject", "message"]) ||
      !sha(gap.id) ||
      !technicalText(gap.code, 200) ||
      !(gap.subject === null || technicalText(gap.subject, 200, true)) ||
      !technicalText(gap.message) ||
      (await jsonDigest({
        code: gap.code,
        subject: gap.subject,
        message: gap.message,
      })) !== gap.id
    )
      technicalFailure();
  }
  return value as Manifest["coverage"]["gaps"];
}
export async function technicalContextTag(
  scope: TechnicalScopeBase,
  contextDigest: string,
  methodDigest: string,
) {
  return `"package-technical-scope-context:${scope.revisionId}:${await jsonDigest({ snapshot_digest: contextDigest, method_digest: methodDigest })}"`;
}
export async function validateTechnicalContext(
  value: unknown,
  tag: string | null,
  scope: TechnicalScope,
) {
  assertTechnicalScope(scope);
  bounded(value);
  if (
    !object(value) ||
    !exactKeys(value, [
      "target",
      "authority",
      "inventory",
      "method",
      "context_digest",
      "etag",
      "can_freeze",
      "blocking_reasons",
      "catalog_complete",
      "timing",
      ...technicalFlags,
    ]) ||
    !flags(value) ||
    value.catalog_complete !== true ||
    !same(value.timing, timing) ||
    !sha(value.context_digest) ||
    typeof value.can_freeze !== "boolean" ||
    typeof value.etag !== "string" ||
    value.etag !== tag
  )
    technicalFailure();
  const result = value as unknown as PackageTechnicalScopeContext;
  await validatePackageNavigationView(result.target, scope.bidId, {
    packageId: scope.packageId,
    revisionId: scope.revisionId,
    inventoryId: scope.inventoryId,
  });
  await validatePackageNavigationInventory(
    result.inventory,
    result.target,
    scope.inventoryId,
  );
  const a = result.authority,
    i = result.inventory.manifest;
  await validatePackageNavigationView(a, scope.bidId, {
    packageId: a.manifest.package_id,
    revisionId: scope.authorityRevisionId,
    inventoryId: null,
  });
  if (
    result.target.manifest.kind !== "bid" ||
    a.manifest.kind !== "authority" ||
    result.target.digest !== scope.packageDigest ||
    result.inventory.digest !== scope.inventoryDigest ||
    a.digest !== scope.authorityDigest ||
    !same(result.target.identity, a.identity) ||
    !same(result.target.manifest.scope, a.manifest.scope) ||
    result.target.identity.digest !== scope.identityDigest ||
    i.authority_revision_id !== scope.authorityRevisionId ||
    i.authority_digest !== scope.authorityDigest ||
    i.rule_set_id !== scope.ruleSetId ||
    i.rule_set_digest !== scope.ruleSetDigest ||
    i.identity_digest !== scope.identityDigest ||
    !Array.isArray(i.requirements) ||
    !Array.isArray(result.target.manifest.members) ||
    !Array.isArray(a.manifest.members)
  )
    technicalFailure();
  for (const packageView of [result.target, a]) {
    if (
      packageView.manifest.members.length > technicalLimits.members ||
      new Set(packageView.manifest.members.map((m) => m.member_id)).size !==
        packageView.manifest.members.length
    )
      technicalFailure();
    if (
      packageView.manifest.members.some(
        (m) =>
          !Array.isArray(m.parts) ||
          !uuid(m.document_version_id) ||
          !sha(m.file_digest),
      )
    )
      technicalFailure();
  }
  const parts = result.target.manifest.members.flatMap((m) => m.parts);
  if (
    parts.length > technicalLimits.parts ||
    new Set(parts.map((p) => p.part_id)).size !== parts.length
  )
    technicalFailure();
  const scoring = i.requirements.filter(
    (r) => r.rule_snapshot.kind === "scoring",
  );
  if (
    scoring.length > technicalLimits.rules ||
    new Set(scoring.map((r) => r.rule_id)).size !== scoring.length
  )
    technicalFailure();
  for (const row of scoring)
    if (
      !uuid(row.rule_id) ||
      !sha(row.rule_digest) ||
      !sha(row.requirement_digest) ||
      (await jsonDigest(row.rule_snapshot)) !== row.rule_digest ||
      (await jsonDigest(row.requirement)) !== row.requirement_digest
    )
      technicalFailure();
  await validateMethod(result.method);
  await validateGaps(result.blocking_reasons);
  if (
    result.can_freeze !== (result.blocking_reasons.length === 0) ||
    tag !==
      (await technicalContextTag(
        scope,
        result.context_digest,
        result.method.digest,
      ))
  )
    technicalFailure();
  return result;
}
export function validTechnicalRequest(
  value: unknown,
  scope?: TechnicalScope,
): value is PackageTechnicalScopeRequest {
  if (
    !object(value) ||
    !exactKeys(value, [
      "purpose",
      "package_digest",
      "authority_revision_id",
      "authority_digest",
      "inventory_id",
      "inventory_digest",
      "technical_part_ids",
      "rule_scopes",
      "reason",
    ]) ||
    value.purpose !== "current_prebid" ||
    ![
      value.package_digest,
      value.authority_digest,
      value.inventory_digest,
    ].every(sha) ||
    !uuid(value.authority_revision_id) ||
    !uuid(value.inventory_id) ||
    !uniqueStrings(value.technical_part_ids) ||
    value.technical_part_ids.length === 0 ||
    !technicalText(value.reason) ||
    !Array.isArray(value.rule_scopes) ||
    value.rule_scopes.length > technicalLimits.rules
  )
    return false;
  const selected = new Set(value.technical_part_ids);
  if (
    new Set(value.rule_scopes.map((r) => r?.rule_id)).size !==
      value.rule_scopes.length ||
    !value.rule_scopes.every(
      (r) =>
        object(r) &&
        exactKeys(r, [
          "rule_id",
          "rule_digest",
          "selection",
          "part_ids",
          "reason",
        ]) &&
        uuid(r.rule_id) &&
        sha(r.rule_digest) &&
        ["include", "exclude", "unclassified"].includes(String(r.selection)) &&
        uniqueStrings(r.part_ids) &&
        technicalText(r.reason) &&
        (r.selection === "include"
          ? r.part_ids.length > 0 && r.part_ids.every((id) => selected.has(id))
          : r.part_ids.length === 0),
    )
  )
    return false;
  return (
    !scope ||
    (value.package_digest === scope.packageDigest &&
      value.authority_revision_id === scope.authorityRevisionId &&
      value.authority_digest === scope.authorityDigest &&
      value.inventory_id === scope.inventoryId &&
      value.inventory_digest === scope.inventoryDigest)
  );
}
export function technicalDefaultRequest(
  context: PackageTechnicalScopeContext,
): PackageTechnicalScopeRequest {
  const i = context.inventory.manifest;
  return {
    purpose: "current_prebid",
    package_digest: context.target.digest,
    authority_revision_id: context.authority.manifest.revision_id,
    authority_digest: context.authority.digest,
    inventory_id: i.id,
    inventory_digest: context.inventory.digest,
    technical_part_ids: [],
    rule_scopes: i.requirements
      .filter((r) => r.rule_snapshot.kind === "scoring")
      .map((r) => ({
        rule_id: r.rule_id,
        rule_digest: r.rule_digest,
        selection: "unclassified",
        part_ids: [],
        reason: "",
      })),
    reason: "",
  };
}
function validateRequestCatalog(
  request: PackageTechnicalScopeRequest,
  context: PackageTechnicalScopeContext,
) {
  const partIds = new Set(
    context.target.manifest.members.flatMap((m) =>
      m.parts.map((p) => p.part_id),
    ),
  );
  const rules = context.inventory.manifest.requirements.filter(
    (r) => r.rule_snapshot.kind === "scoring",
  );
  if (
    request.technical_part_ids.some((id) => !partIds.has(id)) ||
    request.rule_scopes.length !== rules.length
  )
    technicalFailure();
  for (const r of rules) {
    const choice = request.rule_scopes.find((c) => c.rule_id === r.rule_id);
    if (
      !choice ||
      choice.rule_digest !== r.rule_digest ||
      (choice.selection === "include" &&
        r.rule_snapshot.provenance_status !== "effective")
    )
      technicalFailure();
  }
}
async function rawDigest(value: string) {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return Array.from(new Uint8Array(digest), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
}
async function validateDocuments(
  documents: unknown,
): Promise<Manifest["documents"]> {
  if (
    !Array.isArray(documents) ||
    documents.length > 2 * technicalLimits.members ||
    new Set(documents.map((d) => `${d?.package_role}:${d?.member_id}`)).size !==
      documents.length
  )
    technicalFailure();
  let pages = 0,
    blocks = 0;
  for (const d of documents) {
    if (
      !object(d) ||
      !exactKeys(d, [
        "package_role",
        "member_id",
        "document_version_id",
        "file_digest",
        "byte_size",
        "parse",
        "page_count",
        "pages",
        "blocks",
      ]) ||
      !["target", "authority"].includes(String(d.package_role)) ||
      !technicalText(d.member_id, 200) ||
      !uuid(d.document_version_id) ||
      !sha(d.file_digest) ||
      !integer(d.byte_size) ||
      !(d.page_count === null || integer(d.page_count, 1)) ||
      !object(d.parse) ||
      !exactKeys(d.parse, [
        "status",
        "parse_run_id",
        "parser_digest",
        "config_digest",
        "evidence_digest",
        "reason",
      ]) ||
      !Array.isArray(d.pages) ||
      !Array.isArray(d.blocks)
    )
      technicalFailure();
    if (d.parse.status === "not_frozen") {
      if (
        d.parse.parse_run_id !== null ||
        d.parse.parser_digest !== null ||
        d.parse.config_digest !== null ||
        d.parse.evidence_digest !== null ||
        !technicalText(d.parse.reason) ||
        d.pages.length ||
        d.blocks.length
      )
        technicalFailure();
    } else if (
      d.parse.status !== "frozen" ||
      !uuid(d.parse.parse_run_id) ||
      ![
        d.parse.parser_digest,
        d.parse.config_digest,
        d.parse.evidence_digest,
      ].every(sha) ||
      d.parse.reason !== null ||
      d.pages.length !== d.page_count
    )
      technicalFailure();
    pages += d.pages.length;
    blocks += d.blocks.length;
    if (pages > technicalLimits.pages || blocks > technicalLimits.blocks)
      technicalFailure();
    if (
      !d.pages.every(
        (p, i) =>
          object(p) &&
          exactKeys(p, ["physical_page", "quality", "gaps"]) &&
          p.physical_page === i + 1 &&
          ["usable", "partial", "failed"].includes(String(p.quality)) &&
          Array.isArray(p.gaps) &&
          p.gaps.every((g) =>
            technicalText(g, technicalLimits.snapshot_bytes, true),
          ),
      )
    )
      technicalFailure();
    const ids = new Set(),
      ordinals = new Set();
    for (const b of d.blocks) {
      if (
        !object(b) ||
        !exactKeys(b, [
          "id",
          "physical_page",
          "ordinal",
          "kind",
          "text_content",
          "digest",
          "bbox_json",
          "structure_json",
        ]) ||
        !uuid(b.id) ||
        ids.has(b.id) ||
        !integer(b.physical_page, 1) ||
        b.physical_page > d.pages.length ||
        !integer(b.ordinal) ||
        ordinals.has(`${b.physical_page}:${b.ordinal}`) ||
        !["text", "table", "visual_observation"].includes(String(b.kind)) ||
        !technicalText(b.text_content, technicalLimits.snapshot_bytes, true) ||
        !sha(b.digest) ||
        !(
          b.bbox_json === null ||
          technicalText(b.bbox_json, technicalLimits.snapshot_bytes, true)
        ) ||
        !(
          b.structure_json === null ||
          technicalText(b.structure_json, technicalLimits.snapshot_bytes, true)
        ) ||
        (await rawDigest(b.text_content)) !== b.digest
      )
        technicalFailure();
      ids.add(b.id);
      ordinals.add(`${b.physical_page}:${b.ordinal}`);
    }
  }
  return documents as Manifest["documents"];
}
async function validateSources(value: unknown, bidId: string) {
  if (!Array.isArray(value) || value.length > technicalLimits.source_rows)
    technicalFailure();
  const pairs = new Set<string>();
  for (const row of value) {
    if (
      !object(row) ||
      !exactKeys(row, [
        "source_id",
        "ancestor_id",
        "document_version_id",
        "digest",
        "kind",
        "policy_class",
        "known_at",
        "revision",
        "status",
        "valid_from",
        "valid_until",
        "document_bid",
        "original_digest",
      ]) ||
      !uuid(row.source_id) ||
      !uuid(row.ancestor_id) ||
      !(row.document_version_id === null || uuid(row.document_version_id)) ||
      !sha(row.digest) ||
      !(row.original_digest === null || sha(row.original_digest)) ||
      !technicalText(row.kind, 200) ||
      !technicalText(row.policy_class, 200) ||
      instant(row.known_at) === null ||
      !(row.revision === null || integer(row.revision, 1)) ||
      !(
        row.status === null ||
        ["candidate", "published", "withdrawn"].includes(String(row.status))
      ) ||
      !(row.valid_from === null || instant(row.valid_from) !== null) ||
      !(row.valid_until === null || instant(row.valid_until) !== null) ||
      !(row.document_bid === null || uuid(row.document_bid)) ||
      pairs.has(`${row.source_id}:${row.ancestor_id}`)
    )
      technicalFailure();
    // A preview can retain withdrawn or cross-purpose ancestors as explicit gaps.
    // Historical frozen records apply stronger checks below; this is not eligibility.
    pairs.add(`${row.source_id}:${row.ancestor_id}`);
  }
  if (!uuid(bidId)) technicalFailure();
}
export async function validateTechnicalPreview(
  value: unknown,
  scope: TechnicalScopeBase,
  expected?: {
    request: PackageTechnicalScopeRequest;
    context: PackageTechnicalScopeContext;
    etag: string | null;
  },
): Promise<PackageTechnicalScopePreview> {
  bounded(value);
  if (
    !object(value) ||
    !exactKeys(value, ["manifest", "digest"]) ||
    !sha(value.digest) ||
    !object(value.manifest)
  )
    technicalFailure();
  const m = value.manifest;
  if (
    !exactKeys(m, [
      "version",
      "scope",
      "basis",
      "method",
      "request",
      "request_digest",
      "context_digest",
      "parts",
      "rules",
      "documents",
      "source_snapshot",
      "coverage",
      "timing",
      "original_bytes_verified",
      ...technicalFlags,
    ]) ||
    m.version !== "package-technical-scope-preview/1" ||
    !flags(m) ||
    m.original_bytes_verified !== false ||
    !same(m.timing, timing) ||
    !object(m.scope) ||
    !exactKeys(m.scope, [
      "bid_id",
      "package_id",
      "revision_id",
      "inventory_id",
    ]) ||
    m.scope.bid_id !== scope.bidId ||
    m.scope.package_id !== scope.packageId ||
    m.scope.revision_id !== scope.revisionId ||
    !uuid(m.scope.inventory_id) ||
    !object(m.basis) ||
    !exactKeys(m.basis, [
      "package_digest",
      "authority_revision_id",
      "authority_digest",
      "inventory_digest",
      "rule_set_id",
      "rule_set_digest",
      "identity_digest",
    ]) ||
    !uuid(m.basis.authority_revision_id) ||
    !uuid(m.basis.rule_set_id) ||
    ![
      m.basis.package_digest,
      m.basis.authority_digest,
      m.basis.inventory_digest,
      m.basis.rule_set_digest,
      m.basis.identity_digest,
    ].every(sha) ||
    !sha(m.request_digest) ||
    !sha(m.context_digest) ||
    !validTechnicalRequest(m.request) ||
    m.request.inventory_id !== m.scope.inventory_id ||
    m.request.package_digest !== m.basis.package_digest ||
    m.request.authority_revision_id !== m.basis.authority_revision_id ||
    m.request.authority_digest !== m.basis.authority_digest ||
    m.request.inventory_digest !== m.basis.inventory_digest ||
    !Array.isArray(m.parts) ||
    m.parts.length > technicalLimits.parts ||
    !Array.isArray(m.rules) ||
    m.rules.length > technicalLimits.rules ||
    !object(m.coverage) ||
    !exactKeys(m.coverage, [
      "state",
      "all_part_count",
      "selected_part_count",
      "all_scoring_rule_count",
      "included_rule_count",
      "frozen_parse_member_count",
      "gaps",
      "visual_coverage",
      "required_range_completeness",
    ]) ||
    m.coverage.visual_coverage !== "unproven" ||
    m.coverage.required_range_completeness !== "unproven"
  )
    technicalFailure();
  const result = value as unknown as PackageTechnicalScopePreview,
    p = result.manifest;
  await validateMethod(p.method);
  const documents = await validateDocuments(p.documents);
  await validateSources(p.source_snapshot, scope.bidId);
  const partIds = new Set<string>();
  for (const part of p.parts) {
    const d = documents.find(
        (d) => d.package_role === "target" && d.member_id === part.member_id,
      ),
      r = part.part;
    if (
      !object(part) ||
      !exactKeys(part, [
        "member_id",
        "document_version_id",
        "file_digest",
        "part",
        "selected",
        "read_physical_pages",
        "block_ids",
        "text_evidence_present",
        "visual_coverage",
      ]) ||
      !d ||
      part.document_version_id !== d.document_version_id ||
      part.file_digest !== d.file_digest ||
      !object(r) ||
      !exactKeys(r, [
        "part_id",
        "category",
        "first_page",
        "last_page",
        "shared_attachment",
        "heading_path",
      ]) ||
      !technicalText(r.part_id, 200) ||
      partIds.has(r.part_id) ||
      !technicalText(r.category, 200) ||
      !integer(r.first_page, 1) ||
      !integer(r.last_page, r.first_page) ||
      typeof r.shared_attachment !== "boolean" ||
      !(
        r.heading_path === null ||
        (Array.isArray(r.heading_path) &&
          r.heading_path.every((n) => integer(n, 1)))
      ) ||
      part.selected !== p.request.technical_part_ids.includes(r.part_id) ||
      part.visual_coverage !== "unproven"
    )
      technicalFailure();
    const pages = d.pages.filter(
      (page) =>
        page.physical_page >= r.first_page && page.physical_page <= r.last_page,
    );
    const blocks = d.blocks.filter(
      (block) =>
        block.physical_page >= r.first_page &&
        block.physical_page <= r.last_page,
    );
    if (
      !same(
        part.read_physical_pages,
        pages.map((page) => page.physical_page),
      ) ||
      !same(
        part.block_ids,
        blocks.map((b) => b.id),
      ) ||
      part.text_evidence_present !==
        blocks.some((b) => b.kind === "text" && !!b.text_content.trim())
    )
      technicalFailure();
    partIds.add(r.part_id);
  }
  if (
    p.request.technical_part_ids.some((id) => !partIds.has(id)) ||
    p.rules.length !== p.request.rule_scopes.length ||
    new Set(p.rules.map((r) => r.rule_id)).size !== p.rules.length
  )
    technicalFailure();
  for (const rule of p.rules) {
    const choice = p.request.rule_scopes.find(
      (r) => r.rule_id === rule.rule_id,
    );
    if (
      !object(rule) ||
      !exactKeys(rule, [
        "rule_id",
        "rule_digest",
        "selection",
        "part_ids",
        "reason",
        "rule_snapshot",
        "requirement_digest",
        "declared_target_part_ids",
        "source_evidence",
      ]) ||
      !choice ||
      !Object.keys(choice).every((key) =>
        same(
          choice[key as keyof typeof choice],
          rule[key as keyof typeof rule],
        ),
      ) ||
      !object(rule.rule_snapshot) ||
      rule.rule_snapshot.kind !== "scoring" ||
      !sha(rule.requirement_digest) ||
      !uniqueStrings(rule.declared_target_part_ids) ||
      !Array.isArray(rule.source_evidence) ||
      !Array.isArray(rule.rule_snapshot.evidence_ids) ||
      !rule.rule_snapshot.evidence_ids.every(uuid) ||
      new Set(rule.rule_snapshot.evidence_ids).size !==
        rule.rule_snapshot.evidence_ids.length ||
      (await jsonDigest(rule.rule_snapshot)) !== rule.rule_digest ||
      (rule.selection === "include" &&
        rule.rule_snapshot.provenance_status !== "effective")
    )
      technicalFailure();
    const evidenceIds = new Set<string>();
    for (const ref of rule.source_evidence) {
      if (
        !object(ref) ||
        !exactKeys(ref, [
          "member_id",
          "document_version_id",
          "file_digest",
          "parse_run_id",
          "physical_page",
          "evidence_id",
          "evidence_digest",
          "text_content",
          "part_ids",
        ]) ||
        !uuid(ref.evidence_id) ||
        evidenceIds.has(ref.evidence_id) ||
        !rule.rule_snapshot.evidence_ids.includes(ref.evidence_id) ||
        !uniqueStrings(ref.part_ids) ||
        !ref.part_ids.length
      )
        technicalFailure();
      const d = documents.find(
          (d) =>
            d.package_role === "authority" && d.member_id === ref.member_id,
        ),
        b = d?.blocks.find((b) => b.id === ref.evidence_id);
      if (
        !d ||
        !b ||
        d.parse.status !== "frozen" ||
        d.document_version_id !== ref.document_version_id ||
        d.file_digest !== ref.file_digest ||
        d.parse.parse_run_id !== ref.parse_run_id ||
        b.physical_page !== ref.physical_page ||
        b.digest !== ref.evidence_digest ||
        b.text_content !== ref.text_content
      )
        technicalFailure();
      evidenceIds.add(ref.evidence_id);
    }
    if (
      rule.selection !== "unclassified" &&
      (!evidenceIds.size ||
        !same(
          [...evidenceIds].sort(),
          [...rule.rule_snapshot.evidence_ids].sort(),
        ))
    )
      technicalFailure();
  }
  const c = p.coverage;
  if (
    c.state !==
      (p.parts.some((part) => part.selected && part.block_ids.length)
        ? "partial"
        : "unknown") ||
    c.all_part_count !== p.parts.length ||
    c.selected_part_count !== p.request.technical_part_ids.length ||
    c.all_scoring_rule_count !== p.rules.length ||
    c.included_rule_count !==
      p.rules.filter((r) => r.selection === "include").length ||
    c.frozen_parse_member_count !==
      p.documents.filter(
        (d) => d.package_role === "target" && d.parse.status === "frozen",
      ).length
  )
    technicalFailure();
  await validateGaps(c.gaps);
  for (const code of [
    "INVENTORY_COMPLETENESS_UNPROVEN",
    "VISUAL_COMPLETENESS_UNPROVEN",
    "REQUIRED_RANGE_UNPROVEN",
    "MODEL_EXECUTION_NOT_OPEN",
  ])
    if (!c.gaps.some((g) => g.code === code)) technicalFailure();
  if (
    (await jsonDigest(p.request)) !== p.request_digest ||
    (await jsonDigest(p)) !== result.digest
  )
    technicalFailure();
  if (expected) {
    const context = expected.context;
    const selectedScope = technicalSelection(
      scope.bidId,
      "00000000-0000-4000-8000-000000000001",
      context.target,
      context.inventory,
    );
    if (
      !same(p.request, expected.request) ||
      !same(p.basis, basis(selectedScope)) ||
      !same(p.method, context.method) ||
      p.context_digest !== context.context_digest ||
      p.scope.inventory_id !== context.inventory.manifest.id ||
      expected.etag !== context.etag
    )
      technicalFailure();
    validateRequestCatalog(p.request, context);
    const catalog = context.target.manifest.members.flatMap((member) =>
      member.parts.map((part) => ({ member_id: member.member_id, part })),
    );
    if (
      !same(
        p.parts.map(({ member_id, part }) => ({ member_id, part })),
        catalog,
      )
    )
      technicalFailure();
    const members = [context.target, context.authority].flatMap((v, index) =>
      v.manifest.members.map((member) => ({
        role: index === 0 ? "target" : "authority",
        member,
      })),
    );
    if (members.length !== p.documents.length) technicalFailure();
    for (const { role, member } of members) {
      const document = p.documents.find(
        (d) => d.package_role === role && d.member_id === member.member_id,
      );
      if (
        !document ||
        document.document_version_id !== member.document_version_id ||
        document.file_digest !== member.file_digest ||
        document.page_count !== member.page_count ||
        !same(document.parse, member.parse)
      )
        technicalFailure();
    }
    for (const rule of p.rules) {
      const original = context.inventory.manifest.requirements.find(
        (r) => r.rule_id === rule.rule_id,
      );
      if (
        !original ||
        !same(rule.rule_snapshot, original.rule_snapshot) ||
        rule.requirement_digest !== original.requirement_digest ||
        !same(
          rule.declared_target_part_ids,
          original.requirement.target_part_ids,
        )
      )
        technicalFailure();
      for (const ref of rule.source_evidence) {
        const member = context.authority.manifest.members.find(
          (m) => m.member_id === ref.member_id,
        );
        if (
          !member ||
          !same(
            ref.part_ids,
            member.parts
              .filter(
                (p) =>
                  p.first_page <= ref.physical_page &&
                  p.last_page >= ref.physical_page,
              )
              .map((p) => p.part_id),
          )
        )
          technicalFailure();
      }
    }
  }
  return result;
}
export function validateTechnicalPending(
  value: unknown,
  scope: TechnicalScope,
): TechnicalPending {
  assertTechnicalScope(scope);
  bounded(value, technicalLimits.request_bytes + 8192);
  if (
    !object(value) ||
    !exactKeys(value, ["key", "body", "etag", "expected"]) ||
    !uuid(value.key) ||
    !object(value.body) ||
    !exactKeys(value.body, ["request", "preview_digest"]) ||
    !validTechnicalRequest(value.body.request, scope) ||
    !sha(value.body.preview_digest) ||
    typeof value.etag !== "string" ||
    !new RegExp(
      `^"package-technical-scope-context:${scope.revisionId}:[a-f0-9]{64}"$`,
    ).test(value.etag) ||
    !object(value.expected) ||
    !exactKeys(value.expected, ["context_digest", "method_digest"]) ||
    !sha(value.expected.context_digest) ||
    !sha(value.expected.method_digest)
  )
    technicalFailure();
  bounded(value.body, technicalLimits.request_bytes);
  return value as unknown as TechnicalPending;
}
export async function verifyTechnicalPending(
  value: unknown,
  scope: TechnicalScope,
) {
  const p = validateTechnicalPending(value, scope);
  if (
    p.etag !==
    (await technicalContextTag(
      scope,
      p.expected.context_digest,
      p.expected.method_digest,
    ))
  )
    technicalFailure();
  return p;
}
export function validTechnicalHistory(
  value: unknown,
): value is PackageTechnicalScopePage {
  if (
    !object(value) ||
    !exactKeys(value, ["items", "has_more", "next_cursor"]) ||
    !Array.isArray(value.items) ||
    value.items.length > 50 ||
    typeof value.has_more !== "boolean" ||
    (value.has_more
      ? !uuid(value.next_cursor) || value.next_cursor !== value.items.at(-1)?.id
      : value.next_cursor !== null) ||
    new Set(value.items.map((r) => r?.id)).size !== value.items.length
  )
    return false;
  return value.items.every(
    (r) =>
      object(r) &&
      exactKeys(r, [
        "id",
        "digest",
        "inventory_id",
        "created_at",
        "coverage_state",
        "selected_part_count",
        "included_rule_count",
        "scoring_ready",
      ]) &&
      uuid(r.id) &&
      uuid(r.inventory_id) &&
      sha(r.digest) &&
      instant(r.created_at) !== null &&
      ["partial", "unknown"].includes(String(r.coverage_state)) &&
      integer(r.selected_part_count) &&
      integer(r.included_rule_count) &&
      r.scoring_ready === false,
  );
}
export async function validateTechnicalView(
  value: unknown,
  tag: string | null,
  scope: TechnicalScopeBase,
  expected: TechnicalHistoryEntry | TechnicalPending,
): Promise<PackageTechnicalScopeView> {
  bounded(value);
  if (
    !object(value) ||
    !exactKeys(value, ["manifest", "digest"]) ||
    !sha(value.digest) ||
    !object(value.manifest)
  )
    technicalFailure();
  const m = value.manifest;
  if (
    !exactKeys(m, [
      "version",
      "id",
      "actor_id",
      "command_id",
      "frozen_at",
      "preview",
      "original_verification",
      ...technicalFlags,
    ]) ||
    m.version !== "package-technical-scope/1" ||
    !flags(m) ||
    ![m.id, m.actor_id, m.command_id].every(uuid) ||
    instant(m.frozen_at) === null ||
    tag !== `"package-technical-scope:${m.id}:${value.digest}"` ||
    !object(m.original_verification) ||
    !exactKeys(m.original_verification, ["state", "verified_at", "files"]) ||
    m.original_verification.state !== "verified_at_recording" ||
    instant(m.original_verification.verified_at) === null ||
    instant(m.original_verification.verified_at)! > instant(m.frozen_at)! ||
    !Array.isArray(m.original_verification.files) ||
    !m.original_verification.files.length ||
    m.original_verification.files.length > technicalLimits.source_rows
  )
    technicalFailure();
  const preview = await validateTechnicalPreview(m.preview, scope);
  const files = m.original_verification.files;
  if (
    new Set(files.map((f) => f?.document_version_id)).size !== files.length ||
    !files.every(
      (f) =>
        object(f) &&
        exactKeys(f, ["document_version_id", "digest", "byte_size"]) &&
        uuid(f.document_version_id) &&
        sha(f.digest) &&
        integer(f.byte_size),
    ) ||
    files.reduce((sum, f) => sum + Number(f.byte_size), 0) >
      technicalLimits.original_bytes
  )
    technicalFailure();
  for (const d of preview.manifest.documents) {
    const file = files.find(
      (f) => f.document_version_id === d.document_version_id,
    );
    if (
      !file ||
      file.digest !== d.file_digest ||
      file.byte_size !== d.byte_size
    )
      technicalFailure();
  }
  const sources = preview.manifest.source_snapshot;
  if (
    !same(
      [...new Set(sources.map((s) => s.document_version_id))].sort(),
      files.map((f) => f.document_version_id).sort(),
    )
  )
    technicalFailure();
  for (const s of sources) {
    const file = files.find(
      (f) => f.document_version_id === s.document_version_id,
    );
    if (
      !file ||
      s.digest !== file.digest ||
      s.original_digest !== file.digest ||
      s.document_bid !== scope.bidId ||
      s.kind !== "document" ||
      s.policy_class !== "prebid_content" ||
      s.status !== "published" ||
      !integer(s.revision, 1) ||
      instant(s.known_at) === null ||
      instant(s.valid_from) === null ||
      instant(s.known_at)! > instant(m.frozen_at)! ||
      instant(s.valid_from)! > instant(m.frozen_at)! ||
      (s.valid_until !== null &&
        (instant(s.valid_until) === null ||
          instant(s.valid_until)! <= instant(m.frozen_at)!))
    )
      technicalFailure();
  }
  if ((await jsonDigest(m)) !== value.digest) technicalFailure();
  if ("body" in expected) {
    if (
      preview.digest !== expected.body.preview_digest ||
      !same(preview.manifest.request, expected.body.request) ||
      preview.manifest.context_digest !== expected.expected.context_digest ||
      preview.manifest.method.digest !== expected.expected.method_digest
    )
      technicalFailure();
  } else if (
    m.id !== expected.id ||
    value.digest !== expected.digest ||
    preview.manifest.scope.inventory_id !== expected.inventory_id ||
    instant(m.frozen_at) !== instant(expected.created_at) ||
    preview.manifest.coverage.state !== expected.coverage_state ||
    preview.manifest.coverage.selected_part_count !==
      expected.selected_part_count ||
    preview.manifest.coverage.included_rule_count !==
      expected.included_rule_count
  )
    technicalFailure();
  return value as unknown as PackageTechnicalScopeView;
}
export async function validateTechnicalACK(
  value: unknown,
  tag: string | null,
  pending: TechnicalPending,
  scope: TechnicalScope,
) {
  await verifyTechnicalPending(pending, scope);
  if (
    !object(value) ||
    !exactKeys(value, ["scope", "command"]) ||
    !object(value.command) ||
    !exactKeys(value.command, [
      "command_id",
      "actor_id",
      "idempotency_key",
      "request_digest",
      "request",
      "if_match",
    ])
  )
    technicalFailure();
  const saved = await validateTechnicalView(value.scope, tag, scope, pending),
    c = value.command;
  if (
    c.command_id !== saved.manifest.command_id ||
    c.actor_id !== scope.memberId ||
    saved.manifest.actor_id !== scope.memberId ||
    c.idempotency_key !== pending.key ||
    !same(c.request, pending.body) ||
    c.if_match !== pending.etag ||
    !same(saved.manifest.preview.manifest.basis, basis(scope)) ||
    saved.manifest.preview.manifest.scope.inventory_id !== scope.inventoryId ||
    c.request_digest !==
      (await jsonDigest({
        body: {
          scope: [scope.bidId, scope.packageId, scope.revisionId],
          ...pending.body,
        },
        if_match: pending.etag,
      }))
  )
    technicalFailure();
  return value as unknown as PackageTechnicalScopeApplied;
}
const definitiveCodes = new Set([
  "REVISION_CONFLICT",
  "PACKAGE_TECHNICAL_SCOPE_INVALID",
  "PACKAGE_TECHNICAL_SCOPE_BASIS_CHANGED",
  "PACKAGE_TECHNICAL_SCOPE_PREVIEW_CHANGED",
  "PACKAGE_TECHNICAL_SCOPE_CONTEXT_CHANGED",
  "PACKAGE_TECHNICAL_SCOPE_CONTEXT_UNAVAILABLE",
  "PACKAGE_TECHNICAL_SCOPE_AFTER_SUBMISSION",
  "PACKAGE_TECHNICAL_SCOPE_METHOD_CHANGED",
  "PACKAGE_TECHNICAL_SCOPE_RULE_SET_INCOMPLETE",
  "PACKAGE_TECHNICAL_SCOPE_PART_NOT_FOUND",
  "PACKAGE_TECHNICAL_SCOPE_RULE_CHANGED",
  "PACKAGE_TECHNICAL_SCOPE_RULE_RANGE_INVALID",
  "PACKAGE_TECHNICAL_SCOPE_RULE_INACTIVE",
  "PACKAGE_TECHNICAL_SCOPE_RULE_SOURCE_UNPROVEN",
  "PACKAGE_TECHNICAL_SCOPE_SOURCE_UNAVAILABLE",
]);
export const definitiveTechnicalFailure = (error: unknown) =>
  error instanceof ApiError &&
  !error.retryable &&
  [409, 412, 422].includes(error.status) &&
  definitiveCodes.has(error.code);
