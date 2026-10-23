import type {
  WorkContextAnySelection,
  WorkContextChoicePage,
  WorkContextRelationPage,
  AuthoringWorkContext,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
import {
  validAuthoringSelection,
  type ExactBuildSelection,
  contextOperationNames,
} from "./workContextAuthoringProtocol";
import {
  validWorkContextSelection,
  contextTime,
  validContextDimension,
} from "./workContextProtocol";
import type {
  WorkContextKind,
  WorkContextTarget,
} from "./workContextNavigation";

const keys = (
  value: unknown,
  fields: string[],
): value is Record<string, unknown> =>
  recordObject(value) && exactKeys(value, fields);
const integer = (v: unknown, min: number, max: number) =>
  Number.isSafeInteger(v) && Number(v) >= min && Number(v) <= max;
function fail(): never {
  throw new Error(
    "阶段目录的身份、分页范围或原生关联证明不能核验，请重新读取目录。",
  );
}
export function workContextSelectionId(s: WorkContextAnySelection) {
  return s.kind === "draft_snapshot"
    ? s.snapshot_id
    : s.kind === "build"
      ? s.build_id
      : s.kind === "package_review_run"
        ? s.run_id
        : s.submission_id;
}
export function contextChoiceTarget(
  choice: WorkContextChoicePage["items"][number],
): WorkContextTarget {
  return {
    kind: choice.kind,
    id: choice.id,
    selectionDigest: choice.selection_digest,
  };
}
function paging(v: Record<string, unknown>, maximum: number) {
  if (
    !integer(v.total, 0, maximum) ||
    typeof v.has_more !== "boolean" ||
    !Array.isArray(v.items) ||
    v.items.length > 50 ||
    v.items.length > Number(v.total) ||
    v.complete_observation !== true ||
    !executionSha(v.observation_digest) ||
    !contextTime(v.observed_at) ||
    (v.has_more
      ? typeof v.next_cursor !== "string" ||
        !v.next_cursor ||
        v.next_cursor.length > 4096 ||
        !v.items.length
      : v.next_cursor !== null)
  )
    fail();
}

export async function validateWorkContextChoices(
  value: unknown,
  bid: string,
  kind: WorkContextKind,
): Promise<WorkContextChoicePage> {
  if (
    !keys(value, [
      "version",
      "bid_id",
      "kind",
      "filters",
      "observed_at",
      "observation_digest",
      "items",
      "total",
      "has_more",
      "next_cursor",
      "complete_observation",
      "directory_basis",
      "selection_requires_resolution",
      "qualification_assessed",
    ]) ||
    value.version !== "work-context-choice-page/1" ||
    value.bid_id !== bid ||
    value.kind !== kind ||
    !keys(value.filters, ["draft_id", "package_id", "revision_id"]) ||
    Object.values(value.filters).some((v) => v !== null) ||
    value.directory_basis !== "native_record_identity_and_state" ||
    value.selection_requires_resolution !== true ||
    value.qualification_assessed !== false
  )
    fail();
  paging(value, 1000);
  const ids = new Set<string>();
  for (const item of value.items as unknown[]) {
    if (
      !keys(item, [
        "kind",
        "id",
        "label",
        "created_at",
        "status",
        "selection",
        "selection_digest",
      ]) ||
      item.kind !== kind ||
      !executionId(item.id) ||
      ids.has(item.id) ||
      typeof item.label !== "string" ||
      !item.label ||
      item.label.length > 300 ||
      !contextTime(item.created_at) ||
      !executionSha(item.selection_digest) ||
      (!validAuthoringSelection(item.selection, bid) &&
        !validWorkContextSelection(item.selection, bid)) ||
      item.selection.kind !== kind ||
      workContextSelectionId(item.selection) !== item.id ||
      (await jsonDigest(item.selection)) !== item.selection_digest
    )
      fail();
    ids.add(item.id);
    const statuses =
      kind === "draft_snapshot"
        ? ["saved"]
        : kind === "package_submission"
          ? ["standard", "offline_fact"]
          : Object.keys(contextOperationNames);
    if (!statuses.includes(String(item.status))) fail();
  }
  return value as WorkContextChoicePage;
}

export async function validateWorkContextRelations(
  value: unknown,
  selected: ExactBuildSelection,
  outputs: NonNullable<AuthoringWorkContext["build"]>["outputs"],
): Promise<WorkContextRelationPage> {
  if (
    !keys(value, [
      "version",
      "seed",
      "target",
      "observed_at",
      "observation_digest",
      "items",
      "total",
      "has_more",
      "next_cursor",
      "complete_observation",
      "original_bytes_reverified",
      "qualification_assessed",
    ]) ||
    value.version !== "package-work-context-relations/1" ||
    value.target !== "package_revision" ||
    value.original_bytes_reverified !== false ||
    value.qualification_assessed !== false ||
    !recordObject(value.seed) ||
    !validAuthoringSelection(
      { kind: "build", ...value.seed },
      selected.bid_id,
    ) ||
    (await jsonDigest({ kind: "build", ...value.seed })) !==
      (await jsonDigest(selected))
  )
    fail();
  paging(value, 2000);
  const ids = new Set<string>();
  for (const relation of value.items as unknown[]) {
    if (
      !keys(relation, [
        "id",
        "kind",
        "output",
        "package_revision",
        "package_revision_number",
        "proof_digest",
        "adoption_command_id",
        "adopted_at",
        "current_package_head",
        "current_source_basis",
        "qualification_assessed",
      ]) ||
      !executionSha(relation.id) ||
      ids.has(relation.id) ||
      !["adopted_into", "contains_output"].includes(String(relation.kind)) ||
      !executionSha(relation.proof_digest) ||
      !integer(relation.package_revision_number, 1, Number.MAX_SAFE_INTEGER) ||
      relation.qualification_assessed !== false ||
      !validContextDimension(relation.current_package_head) ||
      !validContextDimension(relation.current_source_basis) ||
      !keys(relation.output, ["document_version_id", "format", "sha256"]) ||
      !executionId(relation.output.document_version_id) ||
      !["docx", "pdf"].includes(String(relation.output.format)) ||
      !executionSha(relation.output.sha256) ||
      !keys(relation.package_revision, [
        "kind",
        "bid_id",
        "package_id",
        "revision_id",
        "package_digest",
      ]) ||
      relation.package_revision.kind !== "package_revision" ||
      relation.package_revision.bid_id !== selected.bid_id ||
      !executionId(relation.package_revision.package_id) ||
      !executionId(relation.package_revision.revision_id) ||
      !executionSha(relation.package_revision.package_digest)
    )
      fail();
    if (
      relation.kind === "adopted_into"
        ? !executionId(relation.adoption_command_id) ||
          !contextTime(relation.adopted_at)
        : relation.adoption_command_id !== null || relation.adopted_at !== null
    )
      fail();
    const output = relation.output;
    if (
      !outputs.some(
        (saved) =>
          saved.format === output.format &&
          saved.state === "succeeded" &&
          saved.document !== null &&
          saved.document.document_version_id === output.document_version_id &&
          saved.document.sha256 === output.sha256,
      )
    )
      fail();
    ids.add(relation.id);
  }
  return value as WorkContextRelationPage;
}
