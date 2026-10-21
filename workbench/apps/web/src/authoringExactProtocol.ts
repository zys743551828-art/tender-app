import type {
  AuthoringExactDraftStatus,
  AuthoringExactRevisionCapabilities,
  AuthoringExactRevisionView,
  AuthoringExactSectionBinding,
  DraftSaved,
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
  authoringText as text,
  type VerifiedAuthoringInput,
} from "./packageAuthoringInputProtocol";
import { readPackageAuthoringProposal } from "./taskPackageAuthoringProtocol";

export type ExactPackageAction = ReturnType<
  typeof readPackageAuthoringProposal
>;
export type ExactActionDecision = "confirm" | "reject";
function fail(
  message = "固定整包采纳的身份、正文修订或原回执不一致；原请求继续保留。",
): never {
  throw new Error(message);
}
const reasons = (v: unknown) =>
  Array.isArray(v) &&
  v.every((x) => text(x, 500)) &&
  new Set(v).size === v.length;

/** A readable historical input is not execution authority. It must still match
 * the exact candidate shown here; the server rechecks all live input sources. */
export async function verifyExactCandidateInput(
  input: VerifiedAuthoringInput,
  action: ExactPackageAction,
) {
  const m = input.manifest,
    target = m.selection.target_section;
  const saved = exactActionSaved(action);
  const node = action.preview.before.content.find(
    (n) => n.attrs.id === target.node_id,
  );
  if (
    m.bid_id !== action.target_bid_id ||
    m.id !== action.preview.authoring_input_id ||
    input.digest !== action.preview.authoring_input_digest ||
    target.section_id !== action.preview.section_id ||
    target.base_draft_revision !== action.base_revision ||
    target.base_section_revision !== action.preview.base_section_revision ||
    (saved && saved.draft_id !== target.draft_id) ||
    target.section_digest !== (await jsonDigest(action.preview.before)) ||
    !node ||
    target.before_node_digest !== (await jsonDigest(node))
  )
    fail("固定编写输入与本候选的原稿、章节或基准不一致，未开放新采纳。");
  return input;
}

export function readExactCapabilities(
  value: unknown,
): AuthoringExactRevisionCapabilities {
  if (
    !object(value) ||
    !exactKeys(value, [
      "protocol",
      "apply_available",
      "build_available",
      "ordinary_edit_available",
      "supported_content",
      "blocking_reasons",
    ]) ||
    value.protocol !== "authoring-exact-revision-capabilities/1" ||
    typeof value.apply_available !== "boolean" ||
    typeof value.build_available !== "boolean" ||
    value.ordinary_edit_available !== false ||
    value.supported_content !== "plain_text_stable_node" ||
    !reasons(value.blocking_reasons)
  )
    fail("固定整包正文采纳能力未能核验，暂未开放新操作。");
  return value as unknown as AuthoringExactRevisionCapabilities;
}

function readBinding(value: unknown): AuthoringExactSectionBinding {
  if (
    !object(value) ||
    !exactKeys(value, [
      "section_id",
      "section_revision_id",
      "section_revision",
      "section_digest",
      "qualification_id",
      "qualification_digest",
      "authoring_input_id",
      "authoring_input_digest",
      "source_scope",
    ]) ||
    ![
      value.section_id,
      value.section_revision_id,
      value.qualification_id,
      value.authoring_input_id,
    ].every(uuid) ||
    !integer(value.section_revision) ||
    ![
      value.section_digest,
      value.qualification_digest,
      value.authoring_input_digest,
    ].every(sha) ||
    value.source_scope !== "exact_package_context"
  )
    fail();
  return value as unknown as AuthoringExactSectionBinding;
}

export function readExactDraftStatus(
  value: unknown,
  bidId: string,
  draftId: string,
): AuthoringExactDraftStatus {
  if (
    !object(value) ||
    !exactKeys(value, [
      "protocol",
      "bid_id",
      "draft_id",
      "draft_revision",
      "snapshot_id",
      "snapshot_digest",
      "exact_sections",
      "ordinary_edit_available",
      "build_available",
      "blocking_reasons",
    ]) ||
    value.protocol !== "authoring-exact-draft-status/1" ||
    value.bid_id !== bidId ||
    value.draft_id !== draftId ||
    ![bidId, draftId, value.snapshot_id].every(uuid) ||
    !integer(value.draft_revision) ||
    !sha(value.snapshot_digest) ||
    !Array.isArray(value.exact_sections) ||
    value.exact_sections.length > 1000 ||
    typeof value.build_available !== "boolean" ||
    value.ordinary_edit_available !== (value.exact_sections.length === 0) ||
    !reasons(value.blocking_reasons)
  )
    fail("当前草稿的固定整包来源资格未能核验，保留原稿并暂停新编辑或构建。");
  const sections = value.exact_sections.map(readBinding);
  if (
    new Set(sections.map((s) => s.section_id)).size !== sections.length ||
    new Set(sections.map((s) => s.section_revision_id)).size !== sections.length
  )
    fail();
  return value as unknown as AuthoringExactDraftStatus;
}

/** The live availability/effect text may change with server configuration; the
 * actual candidate, target, original identities and expiry must not change. */
export function packageActionBasis(action: ExactPackageAction) {
  const {
    apply_available: _apply,
    build_available: _build,
    effect: _effect,
    ...preview
  } = action.preview;
  void _apply;
  void _build;
  void _effect;
  return {
    action_id: action.action_id,
    job_id: action.job_id,
    target_bid_id: action.target_bid_id,
    tool: action.tool,
    request_digest: action.request_digest,
    base_revision: action.base_revision,
    expires_at: action.expires_at,
    preview,
    formal_scoring_input: false,
  };
}

export function exactActionSaved(
  action: ExactPackageAction,
): DraftSaved | null {
  if (action.result === null) {
    if (action.state === "executed") fail();
    return null;
  }
  const result: unknown = action.result;
  if (
    !object(result) ||
    !exactKeys(result, ["assistant_resolution"]) ||
    !object(result.assistant_resolution)
  )
    fail();
  const r = result.assistant_resolution;
  if (
    !exactKeys(r, [
      "action_id",
      "state",
      "tool",
      "target_bid_id",
      "domain_result",
      "error_code",
      "http_status",
      "business_effect_executed",
    ]) ||
    r.action_id !== action.action_id ||
    r.state !== action.state ||
    r.tool !== "authoring.apply_patch" ||
    r.target_bid_id !== action.target_bid_id ||
    typeof r.business_effect_executed !== "boolean" ||
    !Number.isInteger(r.http_status) ||
    Number(r.http_status) < 200 ||
    Number(r.http_status) > 599 ||
    !(r.error_code === null || text(r.error_code, 500))
  )
    fail();
  if (action.state !== "executed") {
    if (r.business_effect_executed !== false || r.domain_result !== null)
      fail();
    return null;
  }
  const saved = r.domain_result;
  if (
    r.business_effect_executed !== true ||
    r.http_status !== 200 ||
    r.error_code !== null ||
    !uuid(action.resolved_by) ||
    !object(saved) ||
    !exactKeys(saved, [
      "draft_id",
      "draft_revision",
      "snapshot_id",
      "snapshot_digest",
    ]) ||
    !uuid(saved.draft_id) ||
    !uuid(saved.snapshot_id) ||
    !sha(saved.snapshot_digest) ||
    saved.draft_revision !== action.base_revision + 1
  )
    fail();
  return saved as unknown as DraftSaved;
}

export async function verifyExactAction(
  value: unknown,
  etag: string | null,
  id: string,
  bidId?: string,
) {
  if (!object(value) || value.action_id !== id || !uuid(value.target_bid_id))
    fail();
  const action = readPackageAuthoringProposal(
    value,
    bidId ?? value.target_bid_id,
  );
  if (etag !== `"assistant-action:${id}:${await jsonDigest(action)}"`)
    fail("候选卡全文与保存令牌不一致，未发送操作。");
  if (
    action.state === "pending" &&
    (action.result !== null || action.resolved_by !== null)
  )
    fail();
  exactActionSaved(action);
  return action;
}

export async function verifyExactActionACK(
  value: unknown,
  etag: string | null,
  original: ExactPackageAction,
) {
  const action = await verifyExactAction(
    value,
    etag,
    original.action_id,
    original.target_bid_id,
  );
  if (
    !same(packageActionBasis(action), packageActionBasis(original)) ||
    action.state === "pending" ||
    (original.state === "pending"
      ? action.revision <= original.revision
      : action.revision < original.revision) ||
    !uuid(action.resolved_by)
  )
    fail();
  // Another member may already have resolved this global action. Preserve the
  // actual consumed result, even when it differs from our requested decision.
  return action;
}

export async function exactAdoptionBinding(
  value: unknown,
  action: ExactPackageAction,
  saved: DraftSaved,
) {
  if (
    !object(value) ||
    value.snapshot_id !== saved.snapshot_id ||
    value.snapshot_digest !== saved.snapshot_digest ||
    !Array.isArray(value.sections) ||
    !object(value.authoring_exact_sections)
  )
    fail();
  const extension = value.authoring_exact_sections;
  if (
    !exactKeys(extension, ["protocol", "sections", "digest"]) ||
    extension.protocol !== "authoring-exact-snapshot/1" ||
    !Array.isArray(extension.sections) ||
    !extension.sections.length ||
    extension.sections.length > 1000 ||
    !sha(extension.digest) ||
    extension.digest !==
      (await jsonDigest({
        protocol: extension.protocol,
        sections: extension.sections,
      }))
  )
    fail();
  const bindings = extension.sections.map(readBinding);
  if (new Set(bindings.map((s) => s.section_id)).size !== bindings.length)
    fail();
  const found = bindings.filter(
    (s) => s.section_id === action.preview.section_id,
  );
  if (found.length !== 1) fail();
  const binding = found[0],
    afterDigest = await jsonDigest(action.preview.after);
  if (
    binding.section_revision !== action.preview.base_section_revision + 1 ||
    binding.authoring_input_id !== action.preview.authoring_input_id ||
    binding.authoring_input_digest !== action.preview.authoring_input_digest ||
    binding.section_digest !== afterDigest ||
    !(await Promise.all(value.sections.map((s) => jsonDigest(s)))).includes(
      afterDigest,
    )
  )
    fail();
  return binding;
}

export async function verifyExactQualification(
  value: unknown,
  binding: AuthoringExactSectionBinding,
  action: ExactPackageAction,
  saved: DraftSaved,
): Promise<AuthoringExactRevisionView> {
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
    !exactKeys(m, [
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
    ]) ||
    m.protocol !== "authoring-exact-revision/1" ||
    m.id !== binding.qualification_id ||
    m.bid_id !== action.target_bid_id ||
    m.draft_id !== saved.draft_id ||
    m.draft_revision !== saved.draft_revision ||
    m.section_id !== binding.section_id ||
    m.section_revision_id !== binding.section_revision_id ||
    m.section_revision !== binding.section_revision ||
    m.section_digest !== binding.section_digest ||
    !sha(m.schema_digest) ||
    !uuid(m.parent_section_revision_id) ||
    m.parent_section_revision !== action.preview.base_section_revision ||
    m.parent_section_digest !== (await jsonDigest(action.preview.before)) ||
    m.source_scope !== "exact_package_context" ||
    m.candidate_adopted !== true ||
    m.content_correctness_certified !== false ||
    !object(m.input) ||
    !exactKeys(m.input, ["id", "digest", "context_digest"]) ||
    m.input.id !== binding.authoring_input_id ||
    m.input.digest !== binding.authoring_input_digest ||
    !sha(m.input.context_digest) ||
    !object(m.origin) ||
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
    m.origin.kind !== "model_candidate_adoption" ||
    m.origin.job_id !== action.job_id ||
    m.origin.action_id !== action.action_id ||
    m.origin.action_digest !== action.request_digest ||
    m.origin.actor_id !== action.resolved_by ||
    !uuid(m.origin.command_id) ||
    ![
      m.origin.job_input_digest,
      m.origin.candidate_digest,
      m.origin.before_action_digest,
    ].every(sha) ||
    !object(m.method) ||
    !exactKeys(m.method, ["protocol", "supported_content", "source_sha256"]) ||
    m.method.protocol !== "authoring-exact-adoption-policy/1" ||
    m.method.supported_content !== "plain_text_stable_node" ||
    !object(m.method.source_sha256) ||
    !Object.keys(m.method.source_sha256).length ||
    !Object.values(m.method.source_sha256).every(sha) ||
    m.method_digest !== (await jsonDigest(m.method)) ||
    m.source_refs_digest !==
      (await jsonDigest(action.preview.after.attrs.source_refs)) ||
    m.rule_ids_digest !==
      (await jsonDigest(action.preview.after.attrs.rule_ids))
  )
    fail();
  return value as unknown as AuthoringExactRevisionView;
}
