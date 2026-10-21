import type {
  AuthoringWordImportCandidate,
  AuthoringWordImportCapabilities,
  AuthoringWordImportPage,
  AuthoringWordImportResult,
} from "./contracts";
import type {
  PendingWordImport,
  WordImportScope,
} from "./authoringWordImportRecovery";
import { wordImportReasonValid } from "./authoringWordImportRecovery";
import {
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
import { readAuthoringContent } from "./richEditorSchema";

const integer = (
  value: unknown,
  minimum = 0,
  maximum = Number.MAX_SAFE_INTEGER,
) =>
  Number.isSafeInteger(value) &&
  Number(value) >= minimum &&
  Number(value) <= maximum;
const text = (value: unknown, maximum = 4096): value is string =>
  typeof value === "string" && value.length <= maximum;
const time = (value: unknown) =>
  text(value, 100) && Number.isFinite(Date.parse(value));
function fail(): never {
  throw new Error(
    "Word导入响应的项目、草稿、原件、结构或回执身份无法核对。原请求保留，未确认导入成功。",
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
export const sameWordImportRequest = (left: unknown, right: unknown) =>
  JSON.stringify(ordered(left)) === JSON.stringify(ordered(right));

export function validateWordImportCapabilities(
  value: unknown,
): AuthoringWordImportCapabilities {
  if (
    !recordObject(value) ||
    typeof value.enabled !== "boolean" ||
    !executionSha(value.method_digest) ||
    !recordObject(value.method) ||
    !Array.isArray(value.supported) ||
    !value.supported.every((item) => text(item)) ||
    !Array.isArray(value.limitations) ||
    !value.limitations.every((item) => text(item)) ||
    !recordObject(value.limits) ||
    ![
      "max_docx_bytes",
      "max_candidate_bytes",
      "max_sections",
      "max_images",
    ].every((key) =>
      integer((value.limits as Record<string, unknown>)[key], 1),
    ) ||
    value.append_only !== true ||
    value.requires_registered_original !== true ||
    value.requires_loss_acknowledgement !== true ||
    (value.unavailable_reason !== null &&
      (!recordObject(value.unavailable_reason) ||
        !text(value.unavailable_reason.code) ||
        !text(value.unavailable_reason.message))) ||
    (value.enabled && value.unavailable_reason !== null)
  )
    fail();
  return value as AuthoringWordImportCapabilities;
}

function validSource(value: unknown) {
  return (
    recordObject(value) &&
    executionId(value.document_version_id) &&
    executionSha(value.digest) &&
    integer(value.byte_size, 1, 33554432) &&
    value.media_type ===
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document" &&
    text(value.filename) &&
    text(value.role) &&
    executionId(value.file_id) &&
    integer(value.file_revision, 1) &&
    executionSha(value.intake_digest)
  );
}
function validSummary(value: unknown, scope: WordImportScope) {
  return (
    recordObject(value) &&
    executionId(value.candidate_id) &&
    value.bid_id === scope.bidId &&
    value.draft_id === scope.draftId &&
    executionSha(value.candidate_digest) &&
    validSource(value.source) &&
    integer(value.base_draft_revision, 1) &&
    executionSha(value.method_digest) &&
    ["ready", "blocked", "applied", "rejected"].includes(String(value.state)) &&
    time(value.created_at) &&
    executionId(value.created_by) &&
    integer(value.section_count, 0, 500) &&
    integer(value.image_count, 0, 500) &&
    integer(value.warning_count, 0, 10000) &&
    integer(value.blocker_count, 0, 10000)
  );
}

export function validateWordImportPage(
  value: unknown,
  scope: WordImportScope,
): AuthoringWordImportPage {
  if (
    !recordObject(value) ||
    value.bid_id !== scope.bidId ||
    value.draft_id !== scope.draftId ||
    !Array.isArray(value.items) ||
    value.items.length > 200 ||
    !value.items.every((item) => validSummary(item, scope)) ||
    new Set(
      value.items.map(
        (item) => (item as { candidate_id: string }).candidate_id,
      ),
    ).size !== value.items.length ||
    typeof value.has_more !== "boolean" ||
    (value.has_more
      ? !executionId(value.next_cursor)
      : value.next_cursor !== null)
  )
    fail();
  return value as AuthoringWordImportPage;
}

function commandShape(value: unknown) {
  return (
    recordObject(value) &&
    executionId(value.command_id) &&
    executionId(value.actor_id) &&
    text(value.idempotency_key, 128) &&
    !!value.idempotency_key &&
    executionSha(value.request_digest) &&
    recordObject(value.request) &&
    (value.if_match === null || text(value.if_match, 512))
  );
}

export function validateWordImportCandidate(
  value: unknown,
  scope: WordImportScope,
  expectedId?: string,
  pending?: Extract<PendingWordImport, { kind: "prepare" }>,
): AuthoringWordImportCandidate {
  if (!validSummary(value, scope) || !recordObject(value)) fail();
  const candidate = value as unknown as AuthoringWordImportCandidate;
  if (
    (expectedId && candidate.candidate_id !== expectedId) ||
    candidate.protocol !== "authoring-word-import-candidate/1" ||
    !executionId(candidate.base_snapshot_id) ||
    !executionSha(candidate.before_digest) ||
    !text(candidate.base_draft_etag, 512) ||
    !/^"[^"\r\n]+"$/.test(candidate.base_draft_etag) ||
    candidate.append_only !== true ||
    candidate.current_validity !== "rechecked_on_append" ||
    !wordImportReasonValid(candidate.reason) ||
    !recordObject(candidate.method) ||
    !commandShape(candidate.preparation) ||
    candidate.preparation.actor_id !== candidate.created_by ||
    !Array.isArray(candidate.sections) ||
    candidate.sections.length !== candidate.section_count ||
    !Array.isArray(candidate.images) ||
    candidate.images.length !== candidate.image_count ||
    !Array.isArray(candidate.mapping) ||
    candidate.mapping.length > 100000 ||
    !Array.isArray(candidate.existing_sections) ||
    candidate.existing_sections.length > 500 ||
    !Array.isArray(candidate.issues) ||
    candidate.issues.length > 10000 ||
    typeof candidate.can_apply !== "boolean"
  )
    fail();
  const preparation = candidate.preparation;
  if (
    preparation.request.source_document_version_id !==
      candidate.source.document_version_id ||
    preparation.request.source_digest !== candidate.source.digest ||
    preparation.request.source_byte_size !== candidate.source.byte_size ||
    preparation.request.base_draft_revision !== candidate.base_draft_revision ||
    preparation.request.method_digest !== candidate.method_digest ||
    preparation.request.reason !== candidate.reason ||
    preparation.if_match !== candidate.base_draft_etag ||
    (pending &&
      (preparation.actor_id !== scope.memberId ||
        preparation.idempotency_key !== pending.key ||
        preparation.if_match !== pending.etag ||
        !sameWordImportRequest(preparation.request, pending.body)))
  )
    fail();
  const existing = new Set<string>();
  for (const section of candidate.existing_sections) {
    if (
      !recordObject(section) ||
      !executionId(section.section_id) ||
      existing.has(section.section_id) ||
      (section.parent_id !== null && !executionId(section.parent_id)) ||
      !integer(section.ordinal) ||
      !text(section.title, 200)
    )
      fail();
    existing.add(section.section_id);
  }
  const sections = new Map<
    string,
    AuthoringWordImportCandidate["sections"][number]
  >();
  const sectionIds = new Set<string>();
  const sectionNodes = new Map<string, Map<string, string>>();
  const imageKeys = new Set<string>();
  for (const image of candidate.images) {
    if (
      !recordObject(image) ||
      !executionId(image.key) ||
      imageKeys.has(image.key) ||
      !text(image.source_part) ||
      !executionSha(image.source_digest) ||
      !integer(image.source_byte_size, 1) ||
      !["image/png", "image/jpeg"].includes(image.source_media_type) ||
      image.media_type !== "image/png" ||
      !executionSha(image.digest) ||
      !integer(image.byte_size, 1, 33554432) ||
      !integer(image.width_px, 1, 30000) ||
      !integer(image.height_px, 1, 30000)
    )
      fail();
    imageKeys.add(image.key);
  }
  for (const section of candidate.sections) {
    if (
      !recordObject(section) ||
      !executionId(section.key) ||
      sections.has(section.key) ||
      !executionId(section.section_id) ||
      sectionIds.has(section.section_id) ||
      existing.has(section.section_id) ||
      (section.parent_key !== null && !executionId(section.parent_key)) ||
      (section.parent_id !== null && !executionId(section.parent_id)) ||
      !integer(section.ordinal, 0, 499) ||
      !text(section.title, 200) ||
      !text(section.source_path)
    )
      fail();
    const document = readAuthoringContent(section.content, true);
    const nodes = new Map<string, string>();
    document.descendants((node) => {
      if (node.attrs.id) nodes.set(String(node.attrs.id), node.type.name);
      if (
        node.type.name === "image" &&
        !imageKeys.has(String(node.attrs.asset_id))
      )
        fail();
    });
    sections.set(section.key, section);
    sectionNodes.set(section.key, nodes);
    sectionIds.add(section.section_id);
  }
  for (const section of candidate.sections) {
    if (
      section.parent_key === null
        ? section.parent_id !== null
        : sections.get(section.parent_key)?.section_id !== section.parent_id
    )
      fail();
    let cursor = section;
    const ancestors = new Set([section.key]);
    while (cursor.parent_key !== null) {
      if (ancestors.has(cursor.parent_key) || ancestors.size > 30) fail();
      ancestors.add(cursor.parent_key);
      cursor = sections.get(cursor.parent_key)!;
      if (!cursor) fail();
    }
  }
  if (
    !candidate.mapping.every(
      (item) =>
        recordObject(item) &&
        text(item.source_path) &&
        sections.has(item.section_key) &&
        executionId(item.node_id) &&
        text(item.kind, 100) &&
        (item.kind === "section_title"
          ? item.node_id === sections.get(item.section_key)?.section_id
          : sectionNodes.get(item.section_key)?.get(item.node_id) ===
            item.kind),
    )
  )
    fail();
  const issueIds = new Set<string>();
  for (const issue of candidate.issues) {
    if (
      !recordObject(issue) ||
      !executionSha(issue.id) ||
      issueIds.has(issue.id) ||
      !text(issue.code, 200) ||
      !["warning", "blocker"].includes(issue.severity) ||
      !text(issue.source_path) ||
      !text(issue.message, 10000)
    )
      fail();
    issueIds.add(issue.id);
  }
  if (
    candidate.warning_count !==
      candidate.issues.filter((issue) => issue.severity === "warning").length ||
    candidate.blocker_count !==
      candidate.issues.filter((issue) => issue.severity === "blocker").length ||
    candidate.can_apply !==
      (candidate.state === "ready" &&
        candidate.blocker_count === 0 &&
        candidate.section_count > 0) ||
    (candidate.state === "applied" || candidate.state === "rejected") !==
      (candidate.resolution !== null)
  )
    fail();
  if (candidate.resolution) {
    validateWordImportResult(candidate.resolution, scope, candidate);
    if (candidate.state !== candidate.resolution.state) fail();
  }
  return candidate;
}

export function validateWordImportResult(
  value: unknown,
  scope: WordImportScope,
  candidate: AuthoringWordImportCandidate,
  pending?: Extract<PendingWordImport, { kind: "resolve" }>,
): AuthoringWordImportResult {
  if (
    !recordObject(value) ||
    value.bid_id !== scope.bidId ||
    value.draft_id !== scope.draftId ||
    value.candidate_id !== candidate.candidate_id ||
    value.candidate_digest !== candidate.candidate_digest ||
    !["append", "reject"].includes(String(value.decision)) ||
    value.state !== (value.decision === "append" ? "applied" : "rejected") ||
    !Array.isArray(value.created_section_ids) ||
    !value.created_section_ids.every(executionId) ||
    !time(value.resolved_at) ||
    !commandShape(value.command)
  )
    fail();
  const result = value as AuthoringWordImportResult;
  const command = result.command;
  if (
    command.request.decision !== result.decision ||
    command.request.candidate_digest !== candidate.candidate_digest ||
    !Array.isArray(command.request.acknowledged_issue_ids) ||
    !command.request.acknowledged_issue_ids.every(executionSha) ||
    !wordImportReasonValid(command.request.reason) ||
    (pending &&
      (result.candidate_id !== pending.candidateId ||
        command.actor_id !== scope.memberId ||
        command.idempotency_key !== pending.key ||
        command.if_match !== pending.etag ||
        !sameWordImportRequest(command.request, pending.body)))
  )
    fail();
  if (result.decision === "append") {
    const acknowledged = [...command.request.acknowledged_issue_ids].sort();
    if (
      result.draft_revision !== candidate.base_draft_revision + 1 ||
      !executionId(result.snapshot_id) ||
      !executionSha(result.snapshot_digest) ||
      command.if_match !== candidate.base_draft_etag ||
      candidate.blocker_count !== 0 ||
      !sameWordImportRequest(
        acknowledged,
        candidate.issues
          .filter((issue) => issue.severity === "warning")
          .map((issue) => issue.id)
          .sort(),
      ) ||
      !sameWordImportRequest(
        result.created_section_ids,
        candidate.sections.map((section) => section.section_id),
      )
    )
      fail();
  } else if (
    result.created_section_ids.length ||
    result.draft_revision !== null ||
    result.snapshot_id !== null ||
    result.snapshot_digest !== null
  )
    fail();
  return result;
}

export function wordImportSectionOrder(
  candidate: AuthoringWordImportCandidate,
) {
  const result: {
    section: AuthoringWordImportCandidate["sections"][number];
    depth: number;
  }[] = [];
  function visit(parent: string | null, depth: number) {
    for (const section of candidate.sections
      .filter((item) => item.parent_key === parent)
      .sort((a, b) => a.ordinal - b.ordinal)) {
      result.push({ section, depth });
      visit(section.key, depth + 1);
    }
  }
  visit(null, 0);
  return result;
}
