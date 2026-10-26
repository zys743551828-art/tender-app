import type {
  AuthoringDocument,
  AuthoringNode,
  AuthoringExactDraftStatus,
  AuthoringExactSectionBinding,
  AuthoringExactRevisionView,
  AuthoringExactManualRevisionView,
  AuthoringExactTextEditRequest,
  AuthoringExactTextEditResult,
  AuthoringExactTextEditCapabilities,
  SectionView,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import { readExactDraftStatus } from "./authoringExactProtocol";
import { validateEditableContent } from "./richEditorSchema";
import {
  exactKeys,
  executionId as uuid,
  executionSha as sha,
  recordObject as object,
} from "./executionInputValidation";

export type ExactTextEditScope = {
  memberId: string;
  bidId: string;
  draftId: string;
};
export type ExactTextEditBase = {
  status: AuthoringExactDraftStatus;
  section: SectionView;
  qualification: AuthoringExactRevisionView | AuthoringExactManualRevisionView;
};
export type ExactTextEditPending = {
  key: string;
  etag: string;
  base: ExactTextEditBase;
  body: AuthoringExactTextEditRequest;
};
function fail(): never {
  throw new Error(
    "文字修订的原稿、来源资格或回执无法核对，原请求与文字继续保留。",
  );
}
const hasControls = (text: string) =>
  Array.from(text).some(
    (char) => char.charCodeAt(0) < 32 && char !== "\n" && char !== "\t",
  );
export function readTextEditCapabilities(
  value: unknown,
): AuthoringExactTextEditCapabilities {
  if (
    !object(value) ||
    !exactKeys(value, [
      "protocol",
      "available",
      "supported_content",
      "preserves_source_refs",
      "preserves_rule_ids",
      "ordinary_edit_available",
      "blocking_reasons",
    ]) ||
    value.protocol !== "authoring-exact-text-edit-capabilities/1" ||
    typeof value.available !== "boolean" ||
    value.supported_content !== "plain_text_stable_node" ||
    value.preserves_source_refs !== true ||
    value.preserves_rule_ids !== true ||
    value.ordinary_edit_available !== false ||
    !Array.isArray(value.blocking_reasons) ||
    value.blocking_reasons.some((x) => typeof x !== "string") ||
    (value.available && value.blocking_reasons.length !== 0)
  )
    fail();
  return value as unknown as AuthoringExactTextEditCapabilities;
}
export function editableTextNodes(content: AuthoringDocument) {
  const found: { id: string; text: string; node: AuthoringNode }[] = [];
  function visit(node: AuthoringNode) {
    if (
      (node.type === "paragraph" || node.type === "heading") &&
      node.content.every((c) => c.type === "text" && !c.marks?.length)
    )
      found.push({
        id: node.attrs.id,
        text: node.content
          .map((c) => (c.type === "text" ? c.text : ""))
          .join(""),
        node,
      });
    if ("content" in node) node.content.forEach(visit);
  }
  content.content.forEach(visit);
  return found;
}
const manifestKeys = [
  "protocol",
  "id",
  "bid_id",
  "draft_id",
  "draft_revision",
  "section_id",
  "section_revision_id",
  "section_revision",
  "section_digest",
  "schema_digest",
  "parent_section_revision_id",
  "parent_section_revision",
  "parent_section_digest",
  "input",
  "origin",
  "source_scope",
  "source_refs_digest",
  "rule_ids_digest",
  "method",
  "method_digest",
  "candidate_adopted",
  "content_correctness_certified",
];

async function verifyQualification(
  value: unknown,
  binding: AuthoringExactSectionBinding,
  scope: ExactTextEditScope,
  section: SectionView,
) {
  if (
    !object(value) ||
    !exactKeys(value, ["manifest", "digest"]) ||
    !object(value.manifest) ||
    value.digest !== binding.qualification_digest ||
    value.digest !== (await jsonDigest(value.manifest))
  )
    fail();
  const m = value.manifest;
  if (
    !exactKeys(m, manifestKeys) ||
    ![
      "authoring-exact-revision/1",
      "authoring-exact-manual-revision/1",
    ].includes(String(m.protocol)) ||
    m.id !== binding.qualification_id ||
    m.bid_id !== scope.bidId ||
    m.draft_id !== scope.draftId ||
    !Number.isSafeInteger(m.draft_revision) ||
    Number(m.draft_revision) < 2 ||
    m.section_id !== binding.section_id ||
    m.section_revision_id !== binding.section_revision_id ||
    m.section_revision !== binding.section_revision ||
    m.section_digest !== binding.section_digest ||
    m.schema_digest !== section.schema_digest ||
    !sha(m.schema_digest) ||
    !uuid(m.parent_section_revision_id) ||
    m.parent_section_revision !== Number(m.section_revision) - 1 ||
    !sha(m.parent_section_digest) ||
    m.source_scope !== "exact_package_context" ||
    m.content_correctness_certified !== false ||
    !object(m.input) ||
    !exactKeys(m.input, ["id", "digest", "context_digest"]) ||
    m.input.id !== binding.authoring_input_id ||
    m.input.digest !== binding.authoring_input_digest ||
    !sha(m.input.context_digest) ||
    !object(m.origin) ||
    !uuid(m.origin.command_id) ||
    !uuid(m.origin.actor_id) ||
    !sha(m.origin.before_action_digest) ||
    !object(m.method) ||
    !exactKeys(m.method, ["protocol", "supported_content", "source_sha256"]) ||
    m.method.supported_content !== "plain_text_stable_node" ||
    !object(m.method.source_sha256) ||
    !Object.keys(m.method.source_sha256).length ||
    !Object.values(m.method.source_sha256).every(sha) ||
    m.method_digest !== (await jsonDigest(m.method)) ||
    m.source_refs_digest !==
      (await jsonDigest(section.content.attrs.source_refs)) ||
    m.rule_ids_digest !== (await jsonDigest(section.content.attrs.rule_ids))
  )
    fail();
  if (m.protocol === "authoring-exact-revision/1") {
    if (
      m.candidate_adopted !== true ||
      m.origin.kind !== "model_candidate_adoption" ||
      m.method.protocol !== "authoring-exact-adoption-policy/1" ||
      !exactKeys(m.origin, [
        "kind",
        "job_id",
        "job_input_digest",
        "action_id",
        "action_digest",
        "candidate_digest",
        "command_id",
        "actor_id",
        "before_action_digest",
      ]) ||
      ![m.origin.job_id, m.origin.action_id].every(uuid) ||
      ![
        m.origin.job_input_digest,
        m.origin.action_digest,
        m.origin.candidate_digest,
      ].every(sha)
    )
      fail();
  } else if (
    m.candidate_adopted !== false ||
    m.origin.kind !== "manual_text_edit" ||
    m.method.protocol !== "authoring-exact-text-edit-policy/1" ||
    !exactKeys(m.origin, [
      "kind",
      "parent_qualification_id",
      "parent_qualification_digest",
      "root_qualification_id",
      "root_qualification_digest",
      "command_id",
      "actor_id",
      "before_action_digest",
      "node_id",
      "before_node_digest",
      "replacement_text_digest",
      "reason",
    ]) ||
    ![m.origin.parent_qualification_id, m.origin.root_qualification_id].every(
      uuid,
    ) ||
    ![
      m.origin.parent_qualification_digest,
      m.origin.root_qualification_digest,
      m.origin.before_node_digest,
      m.origin.replacement_text_digest,
    ].every(sha) ||
    typeof m.origin.node_id !== "string" ||
    !m.origin.node_id ||
    typeof m.origin.reason !== "string" ||
    !m.origin.reason.trim()
  )
    fail();
  return value as unknown as ExactTextEditBase["qualification"];
}

export async function verifyTextEditBase(
  value: unknown,
  scope: ExactTextEditScope,
): Promise<ExactTextEditBase> {
  if (
    ![scope.memberId, scope.bidId, scope.draftId].every(uuid) ||
    !object(value) ||
    !exactKeys(value, ["status", "section", "qualification"]) ||
    !object(value.section)
  )
    fail();
  const status = readExactDraftStatus(value.status, scope.bidId, scope.draftId),
    section = value.section;
  if (
    !exactKeys(section, [
      "id",
      "draft_id",
      "revision",
      "schema_digest",
      "content",
      "writing_plan_id",
    ]) ||
    !uuid(section.id) ||
    section.draft_id !== scope.draftId ||
    !Number.isSafeInteger(section.revision) ||
    !sha(section.schema_digest) ||
    !(section.writing_plan_id === null || uuid(section.writing_plan_id))
  )
    fail();
  validateEditableContent(section.content, false);
  const bound = status.exact_sections.find((b) => b.section_id === section.id);
  if (
    !bound ||
    bound.section_revision !== section.revision ||
    bound.section_digest !== (await jsonDigest(section.content))
  )
    fail();
  const typedSection = section as unknown as SectionView;
  const qualification = await verifyQualification(
    value.qualification,
    bound,
    scope,
    typedSection,
  );
  if (qualification.manifest.draft_revision > status.draft_revision) fail();
  return { status, section: typedSection, qualification };
}

export async function verifyTextEditPending(
  value: unknown,
  scope: ExactTextEditScope,
): Promise<ExactTextEditPending> {
  if (
    !object(value) ||
    !exactKeys(value, ["key", "etag", "base", "body"]) ||
    !uuid(value.key) ||
    !object(value.body)
  )
    fail();
  const base = await verifyTextEditBase(value.base, scope),
    b = value.body;
  if (
    !exactKeys(b, [
      "base_draft_revision",
      "section_revision_id",
      "node_id",
      "before_node_digest",
      "replacement_text",
      "reason",
    ]) ||
    b.base_draft_revision !== base.status.draft_revision ||
    b.section_revision_id !== base.qualification.manifest.section_revision_id ||
    value.etag !== `"draft:${scope.draftId}:${base.status.draft_revision}"` ||
    typeof b.node_id !== "string" ||
    !sha(b.before_node_digest) ||
    typeof b.replacement_text !== "string" ||
    Array.from(b.replacement_text).length > 20000 ||
    hasControls(b.replacement_text) ||
    typeof b.reason !== "string" ||
    !b.reason.trim() ||
    Array.from(b.reason).length > 1000 ||
    hasControls(b.reason)
  )
    fail();
  const node = editableTextNodes(
    base.section.content as AuthoringDocument,
  ).find((n) => n.id === b.node_id);
  if (
    !node ||
    b.before_node_digest !== (await jsonDigest(node.node)) ||
    node.text === b.replacement_text
  )
    fail();
  return { ...value, base } as unknown as ExactTextEditPending;
}
function replaced(
  base: ExactTextEditBase,
  body: AuthoringExactTextEditRequest,
): AuthoringDocument {
  const content = structuredClone(base.section.content) as AuthoringDocument;
  const node = editableTextNodes(content).find(
    (n) => n.id === body.node_id,
  )!.node;
  if (node.type !== "paragraph" && node.type !== "heading") fail();
  node.content = body.replacement_text
    ? [{ type: "text", text: body.replacement_text }]
    : [];
  return content;
}
async function textDigest(text: string) {
  const bytes = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(text),
  );
  return [...new Uint8Array(bytes)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
export async function verifyTextEditACK(
  value: unknown,
  etag: string | null,
  pending: ExactTextEditPending,
  scope: ExactTextEditScope,
): Promise<AuthoringExactTextEditResult> {
  const p = await verifyTextEditPending(pending, scope),
    parent = p.base.qualification,
    pm = parent.manifest;
  if (
    !object(value) ||
    !exactKeys(value, [
      "protocol",
      "bid_id",
      "draft_id",
      "draft_revision",
      "snapshot_id",
      "snapshot_digest",
      "parent_section_revision_id",
      "section_revision_id",
      "section_digest",
      "qualification",
    ]) ||
    value.protocol !== "authoring-exact-text-edit-result/1" ||
    value.bid_id !== scope.bidId ||
    value.draft_id !== scope.draftId ||
    value.draft_revision !== p.body.base_draft_revision + 1 ||
    !uuid(value.snapshot_id) ||
    !sha(value.snapshot_digest) ||
    !uuid(value.section_revision_id) ||
    value.section_revision_id === pm.section_revision_id ||
    value.parent_section_revision_id !== pm.section_revision_id ||
    value.section_digest !== (await jsonDigest(replaced(p.base, p.body))) ||
    etag !== `"draft:${scope.draftId}:${value.draft_revision}"` ||
    !object(value.qualification) ||
    !object(value.qualification.manifest)
  )
    fail();
  const m = value.qualification.manifest;
  const newSection = {
    ...p.base.section,
    revision: pm.section_revision + 1,
    content: replaced(p.base, p.body),
  };
  const q = await verifyQualification(
    value.qualification,
    {
      section_id: pm.section_id,
      section_revision_id: value.section_revision_id,
      section_revision: pm.section_revision + 1,
      section_digest: value.section_digest,
      qualification_id: String(m.id),
      qualification_digest: String(value.qualification.digest),
      authoring_input_id: pm.input.id,
      authoring_input_digest: pm.input.digest,
      source_scope: "exact_package_context",
    },
    scope,
    newSection,
  );
  if (q.manifest.protocol !== "authoring-exact-manual-revision/1") fail();
  const a = q.manifest,
    o = a.origin;
  const root =
    pm.protocol === "authoring-exact-revision/1"
      ? { id: pm.id, digest: parent.digest }
      : {
          id: pm.origin.root_qualification_id,
          digest: pm.origin.root_qualification_digest,
        };
  if (
    !uuid(a.id) ||
    a.id === pm.id ||
    a.draft_revision !== value.draft_revision ||
    a.parent_section_revision_id !== pm.section_revision_id ||
    a.parent_section_digest !== pm.section_digest ||
    o.parent_qualification_id !== pm.id ||
    o.parent_qualification_digest !== parent.digest ||
    o.root_qualification_id !== root.id ||
    o.root_qualification_digest !== root.digest ||
    o.actor_id !== scope.memberId ||
    o.node_id !== p.body.node_id ||
    o.before_node_digest !== p.body.before_node_digest ||
    o.replacement_text_digest !== (await textDigest(p.body.replacement_text)) ||
    o.reason !== p.body.reason ||
    o.before_action_digest !==
      (await jsonDigest({
        request: p.body,
        base_snapshot_id: p.base.status.snapshot_id,
        base_snapshot_digest: p.base.status.snapshot_digest,
      }))
  )
    fail();
  return value as unknown as AuthoringExactTextEditResult;
}
