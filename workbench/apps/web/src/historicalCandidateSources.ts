import type { ExactPackageAction } from "./authoringExactProtocol";
import type {
  AuthoringExactRevisionView,
  DraftSaved,
  HistoricalCandidateTrace,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";

export type HistoricalCandidateProof = {
  saved: DraftSaved;
  action: ExactPackageAction;
  qualification: AuthoringExactRevisionView;
};

export function historicalSourcesPath({
  action,
  saved,
  qualification,
}: HistoricalCandidateProof) {
  const query = new URLSearchParams({
    snapshot_id: saved.snapshot_id,
    snapshot_digest: saved.snapshot_digest,
    qualification_digest: qualification.digest,
    action_id: action.action_id,
  });
  return `/bids/${action.target_bid_id}/authoring/section-revisions/${qualification.manifest.section_revision_id}/candidate-source-trace?${query}`;
}

const positive = (n: unknown) => Number.isSafeInteger(n) && Number(n) > 0;
function fail(): never {
  throw new Error("原候选引用与本次采纳的固定身份不一致，没有显示其他原页。");
}

// UUID v5 is a deterministic parse identity (not a signature). Keep the same
// namespace/name as packages.rag.indexing.parse_source_id.
export async function candidateParseSourceId(parseRunId: string) {
  const namespace = "8d6cdd5c1a2845c6ac26e293b1d16f42";
  const name = new TextEncoder().encode(`document-parse:${parseRunId}`);
  const input = new Uint8Array(16 + name.length);
  for (let i = 0; i < 16; i++) {
    input[i] = Number.parseInt(namespace.slice(i * 2, i * 2 + 2), 16);
  }
  input.set(name, 16);
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-1", input));
  digest[6] = (digest[6] & 0x0f) | 0x50;
  digest[8] = (digest[8] & 0x3f) | 0x80;
  const hex = Array.from(digest.subarray(0, 16), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    hex.slice(12, 16),
    hex.slice(16, 20),
    hex.slice(20),
  ].join("-");
}

export async function checkedHistoricalSources(
  value: unknown,
  { action, saved, qualification }: HistoricalCandidateProof,
) {
  const expected = qualification.manifest;
  if (
    !recordObject(value) ||
    !exactKeys(value, [
      "protocol",
      "bid_id",
      "action_id",
      "action_digest",
      "candidate_digest",
      "snapshot_id",
      "snapshot_digest",
      "section_revision_id",
      "qualification_digest",
      "node",
      "citations",
      "historic_only",
      "original_bytes_reverified",
      "current_effectivity_verified",
      "content_correctness_certified",
      "publication_authorized",
      "trace_digest",
    ]) ||
    value.protocol !== "authoring-historical-candidate-trace/1" ||
    value.bid_id !== action.target_bid_id ||
    value.action_id !== action.action_id ||
    value.action_digest !== action.request_digest ||
    value.candidate_digest !== expected.origin.candidate_digest ||
    value.snapshot_id !== saved.snapshot_id ||
    value.snapshot_digest !== saved.snapshot_digest ||
    value.section_revision_id !== expected.section_revision_id ||
    value.qualification_digest !== qualification.digest ||
    value.historic_only !== true ||
    value.original_bytes_reverified !== false ||
    value.current_effectivity_verified !== false ||
    value.content_correctness_certified !== false ||
    value.publication_authorized !== false ||
    !executionSha(value.trace_digest) ||
    !Array.isArray(value.citations) ||
    value.citations.length > 500 ||
    !recordObject(value.node) ||
    !exactKeys(value.node, [
      "node_id",
      "node_type",
      "before_digest",
      "after_digest",
    ]) ||
    typeof value.node.node_id !== "string" ||
    !value.node.node_id ||
    value.node.node_id.length > 128 ||
    (value.node.node_type !== "heading" &&
      value.node.node_type !== "paragraph") ||
    !executionSha(value.node.before_digest) ||
    !executionSha(value.node.after_digest)
  )
    fail();
  const header = value.node;
  const prior = action.preview.before.content.filter(
    (node) => node.attrs.id === header.node_id,
  );
  const after = action.preview.after.content.filter(
    (node) => node.attrs.id === header.node_id,
  );
  if (
    prior.length !== 1 ||
    after.length !== 1 ||
    prior[0].type !== header.node_type ||
    after[0].type !== header.node_type ||
    (await jsonDigest(prior[0])) !== header.before_digest ||
    (await jsonDigest(after[0])) !== header.after_digest
  )
    fail();

  const parseIdentityChecks = [];
  const evidenceIds = [];
  const seen = new Set<string>();
  const authorised = new Set(
    action.preview.after.attrs.source_refs.map((record) =>
      [
        record.evidence_id,
        record.document_version_id,
        record.source_id,
        record.source_revision,
      ].join(":"),
    ),
  );
  for (const entry of value.citations) {
    if (
      !recordObject(entry) ||
      !exactKeys(entry, [
        "evidence_id",
        "document_version_id",
        "parse_run_id",
        "physical_page",
        "evidence_digest",
        "source_id",
        "source_revision",
        "memberships",
      ]) ||
      !executionId(entry.evidence_id) ||
      !executionId(entry.document_version_id) ||
      !executionId(entry.parse_run_id) ||
      !executionId(entry.source_id) ||
      !executionSha(entry.evidence_digest) ||
      !positive(entry.physical_page) ||
      !positive(entry.source_revision) ||
      seen.has(entry.evidence_id) ||
      !authorised.has(
        [
          entry.evidence_id,
          entry.document_version_id,
          entry.source_id,
          entry.source_revision,
        ].join(":"),
      ) ||
      !Array.isArray(entry.memberships) ||
      !entry.memberships.length ||
      entry.memberships.length > 2
    )
      fail();
    seen.add(entry.evidence_id);
    evidenceIds.push(entry.evidence_id);
    parseIdentityChecks.push(
      candidateParseSourceId(entry.parse_run_id).then(
        (expectedId) => entry.source_id === expectedId,
      ),
    );
    const roles = new Set<string>();
    for (const member of entry.memberships) {
      if (
        !recordObject(member) ||
        !exactKeys(member, [
          "role",
          "package_id",
          "revision_id",
          "manifest_digest",
        ]) ||
        (member.role !== "authority" && member.role !== "target") ||
        roles.has(member.role) ||
        !executionId(member.package_id) ||
        !executionId(member.revision_id) ||
        !executionSha(member.manifest_digest)
      )
        fail();
      roles.add(member.role);
    }
  }
  const added = after[0].content ?? [];
  if (
    added.length > 1 ||
    (added.length === 1 &&
      (added[0].type !== "text" || typeof added[0].text !== "string")) ||
    !(await Promise.all(parseIdentityChecks)).every(Boolean) ||
    (await jsonDigest({
      protocol: "package-authoring-candidate/1",
      input: expected.input,
      node_id: header.node_id,
      before_digest: header.before_digest,
      replacement_text: added[0]?.type === "text" ? added[0].text : "",
      evidence_ids: evidenceIds,
    })) !== expected.origin.candidate_digest
  )
    fail();
  const { trace_digest: expectedTrace, ...payload } = value;
  if ((await jsonDigest(payload)) !== expectedTrace) fail();
  return value as unknown as HistoricalCandidateTrace;
}
