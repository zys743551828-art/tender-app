import type {
  PackageAuthoringFactCatalog,
  PackageAuthoringFactSetPage,
  PackageAuthoringNodeCatalog,
  PackageAuthoringInputRequest,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  exactKeys,
  executionId as uuid,
  executionSha as sha,
  recordObject as object,
} from "./executionInputValidation";
import { historicalSame as same } from "./historicalImportProtocol";
import {
  authoringInteger as integer,
  authoringTimestamp,
  validateAuthoringTarget,
} from "./packageAuthoringInputProtocol";
import { readAuthoringContent } from "./richEditorSchema";

export type CapturePackageReference =
  PackageAuthoringInputRequest["package_context"]["target"];
export type CaptureFactSelection = PackageAuthoringFactCatalog["selection"];
export type CaptureFact = PackageAuthoringFactCatalog["items"][number];
export const captureIdentityNames = [
  "procurement_issuer_identifier",
  "procurement_project_identifier",
  "procurement_lot_identifier",
  "procurement_round_identifier",
  "bidder_identity_identifier",
] as const;
export type CaptureIdentityName = (typeof captureIdentityNames)[number];
export const captureIdentityLabels: Record<CaptureIdentityName, string> = {
  procurement_issuer_identifier: "采购方编号",
  procurement_project_identifier: "工程项目编号",
  procurement_lot_identifier: "标段编号",
  procurement_round_identifier: "投标轮次编号",
  bidder_identity_identifier: "投标主体编号",
};
export const captureSubjectLabels = {
  engineering_project: "工程项目",
  lot: "标段",
  round: "投标轮次",
  bidder: "投标主体",
} as const;
const keys = (v: unknown, names: string[]): v is Record<string, unknown> =>
  object(v) && exactKeys(v, names);
const strings = (v: unknown, max = 50): v is string[] =>
  Array.isArray(v) &&
  v.length <= max &&
  v.every((s) => typeof s === "string" && !!s && s.length <= 200) &&
  new Set(v).size === v.length;
const flags = [
  "observed_at",
  "observation_digest",
  "observation_only",
  "admission_granted",
  "original_bytes_reverified",
  "save_recheck_required",
  "formal_decisions_allowed",
];
const paging = ["next_cursor", "has_more", "total_items"];
export function captureFailure(
  message = "采集目录的固定身份、完整正文或事实依据不能核验；保留原选择，请重新读取。",
): never {
  throw new Error(message);
}
function envelope(
  v: Record<string, unknown>,
): asserts v is Record<string, unknown> & { blocking_reasons: string[] } {
  if (
    !authoringTimestamp(v.observed_at) ||
    !sha(v.observation_digest) ||
    v.observation_only !== true ||
    v.admission_granted !== false ||
    v.original_bytes_reverified !== false ||
    v.save_recheck_required !== true ||
    v.formal_decisions_allowed !== false ||
    !strings(v.blocking_reasons)
  )
    captureFailure();
}
function page(
  v: Record<string, unknown>,
): asserts v is Record<string, unknown> & { blocking_reasons: string[] } {
  envelope(v);
  if (
    !Array.isArray(v.items) ||
    v.items.length > 50 ||
    !integer(v.total_items, 0) ||
    v.total_items > 1000 ||
    v.items.length > v.total_items ||
    typeof v.has_more !== "boolean" ||
    (v.has_more
      ? !v.items.length ||
        typeof v.next_cursor !== "string" ||
        !v.next_cursor ||
        v.next_cursor.length > 4096
      : v.next_cursor !== null)
  )
    captureFailure();
}
function head(v: unknown) {
  return (
    v === null ||
    (keys(v, ["fact_set_id", "revision", "fact_set_digest"]) &&
      uuid(v.fact_set_id) &&
      integer(v.revision) &&
      sha(v.fact_set_digest))
  );
}
function packageRef(v: unknown): v is CapturePackageReference {
  return (
    keys(v, ["package_id", "revision_id", "manifest_digest"]) &&
    uuid(v.package_id) &&
    uuid(v.revision_id) &&
    sha(v.manifest_digest)
  );
}
export function captureNodePath(
  bid: string,
  snapshot: string,
  section: string,
  snapshotDigest: string,
  sectionDigest: string,
) {
  return `/bids/${bid}/authoring/input-catalog/draft-snapshots/${snapshot}/sections/${section}/nodes?expected_snapshot_digest=${snapshotDigest}&expected_section_digest=${sectionDigest}`;
}
export function captureFactsPath(bid: string, s: CaptureFactSelection) {
  const query = new URLSearchParams({
    expected_fact_set_digest: s.fact_set_digest,
    fact_head_revision: String(s.fact_head_revision),
    limit: "20",
  });
  for (const role of ["target", "authority"] as const)
    for (const [k, v] of Object.entries(s[role])) query.set(`${role}_${k}`, v);
  return `/bids/${bid}/authoring/input-catalog/fact-sets/${s.fact_set_id}/facts?${query}`;
}

export async function validateCaptureNodes(
  v: unknown,
  bid: string,
  expected: {
    snapshot_id: string;
    snapshot_digest: string;
    section_id: string;
    section_digest: string;
  },
): Promise<PackageAuthoringNodeCatalog> {
  if (
    !keys(v, [
      "protocol",
      "bid_id",
      "target",
      "section_title",
      "section_content",
      "nodes",
      "unsupported_stable_node_count",
      "current_draft_revision",
      "section_heads",
      "whole_snapshot_plain",
      "structure_supported",
      "blocking_reasons",
      ...flags,
    ]) ||
    v.protocol !== "package-authoring-node-catalog/1" ||
    v.bid_id !== bid ||
    !object(v.target) ||
    typeof v.section_title !== "string" ||
    !v.section_title ||
    !Array.isArray(v.nodes) ||
    v.nodes.length > 10000 ||
    !integer(v.unsupported_stable_node_count, 0) ||
    !integer(v.current_draft_revision) ||
    !Array.isArray(v.section_heads) ||
    v.section_heads.length > 500 ||
    typeof v.whole_snapshot_plain !== "boolean" ||
    typeof v.structure_supported !== "boolean"
  )
    captureFailure();
  const target = v.target;
  envelope(v);
  validateAuthoringTarget({
    ...target,
    node_id: "validation-placeholder",
    before_node_digest: "a".repeat(64),
  });
  if (!Object.entries(expected).every(([k, value]) => target[k] === value))
    captureFailure();
  const document = readAuthoringContent(v.section_content, true);
  if (
    document.attrs.title !== v.section_title ||
    (await jsonDigest(v.section_content)) !== target.section_digest
  )
    captureFailure();
  const stable: Record<string, unknown>[] = [];
  function visit(value: unknown) {
    if (!object(value)) captureFailure();
    for (const child of Array.isArray(value.content) ? value.content : []) {
      if (!object(child)) captureFailure();
      if (object(child.attrs) && child.attrs.id) stable.push(child);
      visit(child);
    }
  }
  visit(v.section_content);
  const ids = stable.map((n) => (n.attrs as Record<string, unknown>).id);
  if (new Set(ids).size !== ids.length) captureFailure();
  function text(n: Record<string, unknown>): string {
    return n.type === "text"
      ? (n.text as string)
      : n.type === "hardBreak"
        ? "\n"
        : (Array.isArray(n.content) ? n.content : [])
            .map((c) => text(c as Record<string, unknown>))
            .join("");
  }
  const eligible = stable.filter((n) =>
    ["paragraph", "heading"].includes(String(n.type)),
  );
  if (
    v.nodes.length !== eligible.length ||
    v.unsupported_stable_node_count !== stable.length - eligible.length
  )
    captureFailure();
  for (let i = 0; i < eligible.length; i++) {
    const n = eligible[i],
      entry = v.nodes[i];
    if (
      !keys(entry, ["node_id", "before_node_digest", "node_type", "text"]) ||
      entry.node_id !== (n.attrs as Record<string, unknown>).id ||
      entry.node_type !== n.type ||
      entry.text !== text(n) ||
      entry.before_node_digest !== (await jsonDigest(n))
    )
      captureFailure();
  }
  const heads = v.section_heads;
  if (
    heads.some(
      (h) =>
        !keys(h, ["section_id", "selected_revision", "head_revision"]) ||
        !uuid(h.section_id) ||
        !integer(h.selected_revision) ||
        !integer(h.head_revision),
    ) ||
    new Set(heads.map((h) => h.section_id)).size !== heads.length ||
    !heads.some(
      (h) =>
        h.section_id === expected.section_id &&
        h.selected_revision === target.base_section_revision,
    )
  )
    captureFailure();
  if (
    (!v.whole_snapshot_plain &&
      !v.blocking_reasons.includes(
        "AUTHORING_PACKAGE_RICH_TARGET_UNSUPPORTED",
      )) ||
    (!v.structure_supported &&
      !v.blocking_reasons.includes(
        "AUTHORING_PACKAGE_STRUCTURE_BASIS_UNSUPPORTED",
      )) ||
    (v.current_draft_revision !== target.base_draft_revision &&
      !v.blocking_reasons.includes("AUTHORING_PACKAGE_DRAFT_CHANGED")) ||
    (heads.some((h) => h.selected_revision !== h.head_revision) &&
      !v.blocking_reasons.includes("AUTHORING_PACKAGE_SECTION_CHANGED"))
  )
    captureFailure();
  const basis = { ...v };
  delete basis.observed_at;
  delete basis.observation_digest;
  if ((await jsonDigest(basis)) !== v.observation_digest) captureFailure();
  return v as unknown as PackageAuthoringNodeCatalog;
}

export function validateCaptureFactSets(
  v: unknown,
  bid: string,
): PackageAuthoringFactSetPage {
  if (
    !keys(v, [
      "protocol",
      "bid_id",
      "items",
      "current_head",
      "blocking_reasons",
      ...paging,
      ...flags,
    ]) ||
    v.protocol !== "package-authoring-fact-set-page/1" ||
    v.bid_id !== bid ||
    !head(v.current_head)
  )
    captureFailure();
  page(v);
  const current = v.current_head as PackageAuthoringFactSetPage["current_head"];
  const items = v.items as unknown[];
  let previous = "";
  for (const item of items) {
    if (
      !keys(item, [
        "fact_set_id",
        "fact_set_digest",
        "fact_count",
        "is_current",
      ]) ||
      !uuid(item.fact_set_id) ||
      item.fact_set_id <= previous ||
      !sha(item.fact_set_digest) ||
      !integer(item.fact_count, 0) ||
      item.is_current !== (current?.fact_set_id === item.fact_set_id) ||
      (item.is_current && current?.fact_set_digest !== item.fact_set_digest)
    )
      captureFailure();
    previous = item.fact_set_id;
  }
  return v as unknown as PackageAuthoringFactSetPage;
}

function validFact(value: unknown): value is CaptureFact {
  if (
    !keys(value, [
      "fact_id",
      "fact_item_digest",
      "proof_digest",
      "name",
      "subject_text",
      "scope_text",
      "value_jsonb_text",
      "unit",
      "identity_name",
      "identity_value_usable",
      "decision",
      "evidence",
      "provenance_status",
      "scope_binding",
      "facts_qualified",
      "blocking_reasons",
    ]) ||
    !uuid(value.fact_id) ||
    !sha(value.fact_item_digest) ||
    !sha(value.proof_digest) ||
    ![
      value.name,
      value.subject_text,
      value.scope_text,
      value.value_jsonb_text,
    ].every((v) => typeof v === "string") ||
    (value.unit !== null && typeof value.unit !== "string") ||
    (value.identity_name !== null &&
      !captureIdentityNames.includes(
        value.identity_name as CaptureIdentityName,
      )) ||
    typeof value.identity_value_usable !== "boolean" ||
    value.facts_qualified !== false ||
    !["verified", "unproven"].includes(String(value.provenance_status)) ||
    !["selected_frozen_parse", "unproven"].includes(
      String(value.scope_binding),
    ) ||
    !strings(value.blocking_reasons) ||
    !value.blocking_reasons.includes("FACT_SCOPE_MAPPING_REQUIRED") ||
    !Array.isArray(value.evidence) ||
    value.evidence.length > 10000
  )
    return false;
  const name = captureIdentityNames.includes(value.name as CaptureIdentityName)
    ? value.name
    : null;
  let decoded: unknown;
  try {
    decoded = JSON.parse(value.value_jsonb_text as string);
  } catch {
    return false;
  }
  if (
    value.identity_name !== name ||
    value.identity_value_usable !==
      !!(name && typeof decoded === "string" && decoded.trim())
  )
    return false;
  const decision = value.decision;
  if (
    decision !== null &&
    (!keys(decision, [
      "id",
      "decision",
      "decision_revision",
      "object_id",
      "actor_id",
      "created_at",
      "binding_verified",
      "basis_verified",
      "carryover_steps",
    ]) ||
      ![decision.id, decision.object_id, decision.actor_id].every(uuid) ||
      !["confirmed", "rejected"].includes(String(decision.decision)) ||
      !integer(decision.decision_revision) ||
      !authoringTimestamp(decision.created_at) ||
      typeof decision.binding_verified !== "boolean" ||
      typeof decision.basis_verified !== "boolean" ||
      !integer(decision.carryover_steps, 0))
  )
    return false;
  if (
    value.evidence.some(
      (e) =>
        !keys(e, [
          "id",
          "parse_id",
          "document_version_id",
          "physical_page",
          "digest",
        ]) ||
        ![e.id, e.parse_id, e.document_version_id].every(uuid) ||
        !integer(e.physical_page) ||
        !sha(e.digest),
    ) ||
    new Set(value.evidence.map((e) => e.id)).size !== value.evidence.length
  )
    return false;
  if (
    value.provenance_status === "verified" &&
    (!decision ||
      decision.decision !== "confirmed" ||
      !decision.binding_verified ||
      !decision.basis_verified ||
      !value.evidence.length ||
      value.scope_binding !== "selected_frozen_parse" ||
      !same(value.blocking_reasons, ["FACT_SCOPE_MAPPING_REQUIRED"]))
  )
    return false;
  return true;
}
export function validateCaptureFacts(
  v: unknown,
  bid: string,
  expected: CaptureFactSelection,
): PackageAuthoringFactCatalog {
  if (
    !keys(v, [
      "protocol",
      "bid_id",
      "selection",
      "current_head",
      "head_matches",
      "package_identity_matches",
      "subject_choices",
      "identity_names",
      "items",
      "blocking_reasons",
      ...paging,
      ...flags,
    ]) ||
    v.protocol !== "package-authoring-fact-catalog/1" ||
    v.bid_id !== bid ||
    !keys(v.selection, [
      "fact_set_id",
      "fact_set_digest",
      "fact_head_revision",
      "target",
      "authority",
    ]) ||
    !uuid(v.selection.fact_set_id) ||
    !sha(v.selection.fact_set_digest) ||
    !integer(v.selection.fact_head_revision) ||
    !packageRef(v.selection.target) ||
    !packageRef(v.selection.authority) ||
    !same(v.selection, expected) ||
    !head(v.current_head) ||
    typeof v.head_matches !== "boolean" ||
    typeof v.package_identity_matches !== "boolean" ||
    !same(v.identity_names, captureIdentityNames) ||
    !Array.isArray(v.subject_choices) ||
    v.subject_choices.length !== 4
  )
    captureFailure();
  page(v);
  const current = v.current_head as PackageAuthoringFactCatalog["current_head"];
  if (
    v.head_matches !==
      !!(
        current &&
        current.fact_set_id === expected.fact_set_id &&
        current.fact_set_digest === expected.fact_set_digest &&
        current.revision === expected.fact_head_revision
      ) ||
    (!v.head_matches &&
      !v.blocking_reasons.includes("AUTHORING_PACKAGE_FACT_HEAD_CHANGED")) ||
    (!v.package_identity_matches &&
      !v.blocking_reasons.includes("AUTHORING_PACKAGE_IDENTITY_CHANGED"))
  )
    captureFailure();
  const kinds = Object.keys(captureSubjectLabels);
  if (
    v.subject_choices.some(
      (s) =>
        !keys(s, ["kind", "id"]) ||
        !kinds.includes(String(s.kind)) ||
        !uuid(s.id),
    ) ||
    new Set(v.subject_choices.map((s) => s.kind)).size !== 4
  )
    captureFailure();
  const items = v.items as unknown[];
  let previous = "";
  for (const item of items) {
    if (!validFact(item) || item.fact_id <= previous) captureFailure();
    previous = item.fact_id;
  }
  return v as unknown as PackageAuthoringFactCatalog;
}
