import type {
  PackageAuthoringInputContext,
  PackageAuthoringInputRequest,
  PackageAuthoringInputView,
  PackageAuthoringSelection,
  PackageTaskAuthoringCapabilities,
  TaskKindPage,
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

export const packageAuthoringScope =
  "使用明确选定的整包、需求清单、事实声明和正文快照，生成目标文字节点的修改候选。候选发布后仍须核对；本入口尚不提供正文采纳或交付包构建。";
export function authoringInputFailure(
  message = "固定整包编写输入的身份、摘要或边界无法核对，未采用这份输入。",
): never {
  throw new Error(message);
}
export const authoringInteger = (v: unknown, min = 1): v is number =>
  typeof v === "number" && Number.isSafeInteger(v) && v >= min;
export const authoringText = (v: unknown, max: number): v is string =>
  typeof v === "string" && !!v.trim() && Array.from(v).length <= max;
export function authoringTimestamp(v: unknown) {
  try {
    historicalDateTime(v);
    return true;
  } catch {
    return false;
  }
}
export function isPackageAuthoringSelection(
  v: unknown,
): v is PackageAuthoringSelection {
  return (
    object(v) &&
    exactKeys(v, ["authoring_input_id", "authoring_input_digest"]) &&
    uuid(v.authoring_input_id) &&
    sha(v.authoring_input_digest)
  );
}
export type AuthoringBusinessScope = {
  bid_id: string;
  lot_id: string;
  round_id: string;
  bidder_id: string;
  engineering_project_id: string;
  bidder_status: "confirmed";
};
export function validateAuthoringScope(
  v: unknown,
  bidId: string,
): AuthoringBusinessScope {
  if (
    !object(v) ||
    !exactKeys(v, [
      "bid_id",
      "lot_id",
      "round_id",
      "bidder_id",
      "engineering_project_id",
      "bidder_status",
    ]) ||
    v.bid_id !== bidId ||
    ![
      v.bid_id,
      v.lot_id,
      v.round_id,
      v.bidder_id,
      v.engineering_project_id,
    ].every(uuid) ||
    v.bidder_status !== "confirmed"
  )
    authoringInputFailure();
  return v as AuthoringBusinessScope;
}
export function validateAuthoringTarget(
  v: unknown,
): PackageAuthoringInputRequest["target_section"] {
  const ids = ["draft_id", "snapshot_id", "section_id", "section_revision_id"];
  const digests = [
    "snapshot_digest",
    "section_digest",
    "schema_digest",
    "before_node_digest",
  ];
  if (
    !object(v) ||
    !exactKeys(v, [
      ...ids,
      ...digests,
      "node_id",
      "base_draft_revision",
      "base_section_revision",
    ]) ||
    !ids.every((k) => uuid(v[k])) ||
    !digests.every((k) => sha(v[k])) ||
    !authoringText(v.node_id, 200) ||
    !authoringInteger(v.base_draft_revision) ||
    !authoringInteger(v.base_section_revision)
  )
    authoringInputFailure();
  return v as PackageAuthoringInputRequest["target_section"];
}
export function validateAuthoringInputRequest(
  v: unknown,
): PackageAuthoringInputRequest {
  if (
    !object(v) ||
    !exactKeys(v, [
      "protocol",
      "purpose",
      "target_relation",
      "package_context",
      "target_section",
      "facts",
    ]) ||
    v.protocol !== "package-authoring-input-request/1" ||
    v.purpose !== "authoring" ||
    v.target_relation !== "draft_using_package_context"
  )
    authoringInputFailure();
  const p = v.package_context,
    f = v.facts;
  if (!object(p) || !exactKeys(p, ["target", "authority", "inventory"]))
    authoringInputFailure();
  for (const role of ["target", "authority"]) {
    const ref = p[role];
    if (
      !object(ref) ||
      !exactKeys(ref, ["package_id", "revision_id", "manifest_digest"]) ||
      !uuid(ref.package_id) ||
      !uuid(ref.revision_id) ||
      !sha(ref.manifest_digest)
    )
      authoringInputFailure();
  }
  const inv = p.inventory;
  if (
    !object(inv) ||
    !exactKeys(inv, ["id", "digest", "rule_set_id"]) ||
    !uuid(inv.id) ||
    !uuid(inv.rule_set_id) ||
    !sha(inv.digest)
  )
    authoringInputFailure();
  validateAuthoringTarget(v.target_section);
  if (
    !object(f) ||
    !exactKeys(f, [
      "fact_set_id",
      "fact_head_revision",
      "identity_fact_ids",
      "uses",
    ]) ||
    !uuid(f.fact_set_id) ||
    !authoringInteger(f.fact_head_revision) ||
    !Array.isArray(f.identity_fact_ids) ||
    f.identity_fact_ids.length !== 5 ||
    !f.identity_fact_ids.every(uuid) ||
    new Set(f.identity_fact_ids).size !== 5 ||
    !Array.isArray(f.uses) ||
    f.uses.length > 500
  )
    authoringInputFailure();
  const seen = new Set<string>();
  for (const use of f.uses) {
    if (
      !object(use) ||
      !exactKeys(use, ["fact_id", "fact_item_digest", "subject", "reason"]) ||
      !uuid(use.fact_id) ||
      seen.has(use.fact_id) ||
      !sha(use.fact_item_digest) ||
      !authoringText(use.reason, 2000) ||
      !object(use.subject) ||
      !exactKeys(use.subject, ["kind", "id"]) ||
      !["engineering_project", "lot", "round", "bidder"].includes(
        String(use.subject.kind),
      ) ||
      !uuid(use.subject.id)
    )
      authoringInputFailure();
    seen.add(use.fact_id);
  }
  return v as unknown as PackageAuthoringInputRequest;
}
export type VerifiedAuthoringInput = PackageAuthoringInputView & {
  manifest: {
    protocol: "package-authoring-input/1";
    id: string;
    bid_id: string;
    actor_id: string;
    command_id: string;
    saved_at: string;
    originals_verified_at: string;
    selection: PackageAuthoringInputRequest;
    scope: AuthoringBusinessScope;
    identity_digest: string;
    context_digest: string;
    method_digest: string;
    counts: {
      logical_members: number;
      physical_pages: number;
      evidence_blocks: number;
      facts: number;
      requirements: number;
      context_bytes: number;
    };
    fact_declarations: { manifest: Record<string, unknown>; digest: string }[];
    generation_available: false;
    publication_authorized: false;
    apply_available: false;
    build_available: false;
    formal_decisions_allowed: false;
  };
};
export async function validateAuthoringInput(
  value: unknown,
  bidId: string,
  expected?: PackageAuthoringSelection,
): Promise<VerifiedAuthoringInput> {
  if (
    !object(value) ||
    !exactKeys(value, ["manifest", "digest"]) ||
    !sha(value.digest) ||
    !object(value.manifest)
  )
    authoringInputFailure();
  const m = value.manifest;
  if (
    !exactKeys(m, [
      "protocol",
      "id",
      "bid_id",
      "actor_id",
      "command_id",
      "saved_at",
      "originals_verified_at",
      "selection",
      "scope",
      "identity_digest",
      "context_digest",
      "method_digest",
      "counts",
      "fact_declarations",
      "generation_available",
      "publication_authorized",
      "apply_available",
      "build_available",
      "formal_decisions_allowed",
    ]) ||
    m.protocol !== "package-authoring-input/1" ||
    m.bid_id !== bidId ||
    ![m.id, m.bid_id, m.actor_id, m.command_id].every(uuid) ||
    ![m.identity_digest, m.context_digest, m.method_digest].every(sha) ||
    !authoringTimestamp(m.saved_at) ||
    !authoringTimestamp(m.originals_verified_at) ||
    m.generation_available !== false ||
    m.publication_authorized !== false ||
    m.apply_available !== false ||
    m.build_available !== false ||
    m.formal_decisions_allowed !== false ||
    (expected &&
      (!isPackageAuthoringSelection(expected) ||
        m.id !== expected.authoring_input_id ||
        value.digest !== expected.authoring_input_digest))
  )
    authoringInputFailure();
  validateAuthoringScope(m.scope, bidId);
  const selection = validateAuthoringInputRequest(m.selection);
  const counts = m.counts;
  if (
    !object(counts) ||
    !exactKeys(counts, [
      "logical_members",
      "physical_pages",
      "evidence_blocks",
      "facts",
      "requirements",
      "context_bytes",
    ]) ||
    !Object.values(counts).every((v) => authoringInteger(v, 0)) ||
    !authoringInteger(counts.logical_members) ||
    !authoringInteger(counts.physical_pages) ||
    !authoringInteger(counts.context_bytes) ||
    counts.context_bytes > 32 * 1024 * 1024 ||
    !Array.isArray(m.fact_declarations) ||
    m.fact_declarations.length !== selection.facts.uses.length
  )
    authoringInputFailure();
  const seen = new Set<string>();
  for (const d of m.fact_declarations) {
    if (
      !object(d) ||
      !exactKeys(d, ["manifest", "digest"]) ||
      !sha(d.digest) ||
      !object(d.manifest)
    )
      authoringInputFailure();
    const dm = d.manifest;
    const use = selection.facts.uses.find((u) => u.fact_id === dm.fact_id);
    if (
      !exactKeys(dm, [
        "protocol",
        "id",
        "bid_id",
        "input_id",
        "fact_id",
        "purpose",
        "revision",
        "action",
        "previous_digest",
        "actor_id",
        "command_id",
        "recorded_at",
        "basis_digest",
        "fact_item_digest",
        "proof_digest",
        "subject",
        "reason",
      ]) ||
      dm.protocol !== "authoring-package-fact-scope/1" ||
      !uuid(dm.id) ||
      typeof dm.fact_id !== "string" ||
      seen.has(dm.fact_id) ||
      !use ||
      dm.bid_id !== bidId ||
      dm.input_id !== m.id ||
      dm.purpose !== "authoring" ||
      dm.action !== "bind" ||
      dm.revision !== 1 ||
      dm.previous_digest !== null ||
      dm.actor_id !== m.actor_id ||
      dm.command_id !== m.command_id ||
      dm.recorded_at !== m.saved_at ||
      dm.basis_digest !== m.context_digest ||
      dm.fact_item_digest !== use.fact_item_digest ||
      !sha(dm.proof_digest) ||
      !same(dm.subject, use.subject) ||
      dm.reason !== use.reason.trim() ||
      (await jsonDigest(dm)) !== d.digest
    )
      authoringInputFailure();
    seen.add(dm.fact_id);
  }
  if ((await jsonDigest(m)) !== value.digest) authoringInputFailure();
  return value as unknown as VerifiedAuthoringInput;
}
export async function validateAuthoringInputPage(
  value: unknown,
  bidId: string,
  prior: VerifiedAuthoringInput[] = [],
  cursor: string | null = null,
) {
  if (
    !object(value) ||
    !exactKeys(value, ["items", "next_cursor", "has_more"]) ||
    !Array.isArray(value.items) ||
    value.items.length > 100 ||
    typeof value.has_more !== "boolean" ||
    (value.has_more
      ? !authoringText(value.next_cursor, 2048) ||
        value.next_cursor === cursor ||
        !value.items.length
      : value.next_cursor !== null)
  )
    authoringInputFailure("固定输入目录分页无法核对，保留已读记录。");
  const items = await Promise.all(
    value.items.map((v) => validateAuthoringInput(v, bidId)),
  );
  const ids = [...prior, ...items].map((v) => v.manifest.id);
  if (
    new Set(ids).size !== ids.length ||
    ids.some((id, i) => i > 0 && id <= ids[i - 1])
  )
    authoringInputFailure("固定输入目录重复或顺序不一致，未跳过记录继续选择。");
  return {
    items,
    has_more: value.has_more,
    next_cursor: value.next_cursor as string | null,
  };
}
export function validateAuthoringPublicContext(
  value: unknown,
  input: VerifiedAuthoringInput,
): PackageAuthoringInputContext {
  const m = input.manifest;
  if (
    !object(value) ||
    !exactKeys(value, [
      "input_id",
      "input_digest",
      "stored_context_digest",
      "context",
      "redacted_fields",
      "original_bytes_reverified",
    ]) ||
    value.input_id !== m.id ||
    value.input_digest !== input.digest ||
    value.stored_context_digest !== m.context_digest ||
    value.original_bytes_reverified !== false ||
    !same(value.redacted_fields, ["documents[*].object_key"]) ||
    !object(value.context)
  )
    authoringInputFailure();
  const c = value.context;
  if (
    !exactKeys(c, [
      "bid_id",
      "documents",
      "facts",
      "identity",
      "inventory",
      "method",
      "method_digest",
      "packages",
      "protocol",
      "request",
      "sources",
      "target",
    ]) ||
    c.protocol !== "package-authoring-context/1" ||
    c.bid_id !== m.bid_id ||
    !same(c.request, m.selection) ||
    c.method_digest !== m.method_digest ||
    !object(c.identity) ||
    c.identity.digest !== m.identity_digest ||
    !Array.isArray(c.documents) ||
    c.documents.length !== m.counts.logical_members ||
    c.documents.some(
      (d) =>
        !object(d) ||
        "object_key" in d ||
        !uuid(d.document_version_id) ||
        !uuid(d.parse_id) ||
        !sha(d.digest),
    ) ||
    !object(c.facts) ||
    !Array.isArray(c.facts.items) ||
    c.facts.items.length !== m.counts.facts ||
    !object(c.inventory) ||
    !object(c.inventory.record) ||
    c.inventory.record.digest !== m.selection.package_context.inventory.digest
  )
    authoringInputFailure();
  // The public projection omits private object keys. Its digest cannot be compared
  // with the full stored context; the server verifies that retained private value.
  return value as unknown as PackageAuthoringInputContext;
}
export function packageAuthoringCapability(
  value: TaskKindPage,
): PackageTaskAuthoringCapabilities | null {
  const matches = Array.isArray(value?.items)
    ? value.items.filter((i) => i.task_kind === "chapter_suggestion")
    : [];
  if (
    matches.length !== 1 ||
    value.default_trigger !== "manual" ||
    value.saving_preset_creates_run !== false
  )
    authoringInputFailure("章节任务能力无法核对。");
  const c = matches[0].exact_package_authoring;
  if (c == null) return null;
  if (
    !object(c) ||
    !exactKeys(c, [
      "available",
      "reason",
      "input_mode",
      "trigger",
      "source_scope",
      "automatic_input_selection",
      "rerun_supported",
      "apply_available",
      "build_available",
    ]) ||
    typeof c.available !== "boolean" ||
    (c.available ? c.reason !== null : !authoringText(c.reason, 1000)) ||
    c.input_mode !== "exact_package_authoring" ||
    c.trigger !== "manual" ||
    c.source_scope !== "exact_package_context" ||
    c.automatic_input_selection !== false ||
    c.rerun_supported !== false ||
    c.apply_available !== false ||
    c.build_available !== false
  )
    authoringInputFailure("固定整包编写的实际能力边界无法核对。");
  return c;
}
