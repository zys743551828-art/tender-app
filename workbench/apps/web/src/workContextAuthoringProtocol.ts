import type {
  AuthoringWorkContext,
  WorkContextBuildSelection,
  WorkContextDraftSelection,
} from "./contracts";
type WorkContextAuthoringSelection =
  | WorkContextBuildSelection
  | WorkContextDraftSelection;
import { jsonDigest } from "./editorSchema";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
import { readAuthoringContent } from "./richEditorSchema";
import { contextTime, validContextDimension } from "./workContextProtocol";
import type { WorkContextTarget } from "./workContextNavigation";

const keys = (v: unknown, names: string[]): v is Record<string, unknown> =>
  recordObject(v) && exactKeys(v, names);
const integer = (
  v: unknown,
  min: number,
  max = Number.MAX_SAFE_INTEGER,
): v is number =>
  Number.isSafeInteger(v) && Number(v) >= min && Number(v) <= max;
const text = (v: unknown, max: number): v is string =>
  typeof v === "string" && v.length > 0 && v.length <= max;
const same = (a: unknown, b: unknown) =>
  JSON.stringify(a) === JSON.stringify(b);
const snapshotKeys = [
  "bid_id",
  "draft_id",
  "draft_revision",
  "snapshot_id",
  "snapshot_digest",
];
const buildKeys = [
  "build_id",
  "build_input_id",
  "input_digest",
  "manifest_digest",
  "writer_kind",
];
export const contextOperationNames = {
  queued: "已排队",
  running: "正在处理",
  cancel_requested: "正在等待取消结果",
  succeeded: "处理已完成",
  failed: "处理失败",
  cancelled: "已取消",
} as const;

export function validAuthoringSelection(
  v: unknown,
  bid: string,
): v is WorkContextAuthoringSelection {
  if (!recordObject(v) || !["draft_snapshot", "build"].includes(String(v.kind)))
    return false;
  return (
    exactKeys(v, [
      "kind",
      ...snapshotKeys,
      ...(v.kind === "build" ? buildKeys : []),
    ]) &&
    v.bid_id === bid &&
    ["bid_id", "draft_id", "snapshot_id"].every((k) => executionId(v[k])) &&
    integer(v.draft_revision, 1) &&
    executionSha(v.snapshot_digest) &&
    (v.kind === "draft_snapshot" ||
      (executionId(v.build_id) &&
        executionId(v.build_input_id) &&
        executionSha(v.input_digest) &&
        executionSha(v.manifest_digest) &&
        text(v.writer_kind, 100)))
  );
}

export function snapshotSelection(
  v: WorkContextAuthoringSelection,
): WorkContextDraftSelection {
  return {
    kind: "draft_snapshot",
    bid_id: v.bid_id,
    draft_id: v.draft_id,
    draft_revision: v.draft_revision,
    snapshot_id: v.snapshot_id,
    snapshot_digest: v.snapshot_digest,
  };
}
function fail(): never {
  throw new Error(
    "所选草稿或生成记录的完整身份、历史正文或输出证明不能核验，请保留原选择后重试。",
  );
}

async function validDocument(
  document: AuthoringWorkContext["document"],
  metadata: AuthoringWorkContext["snapshot"],
) {
  if (
    !keys(document, ["sections", "outline", "images", "editable"]) ||
    document.editable !== false ||
    !Array.isArray(document.sections) ||
    document.sections.length !== metadata.section_count ||
    document.sections.length > 500 ||
    !Array.isArray(document.images) ||
    document.images.length > 10000
  )
    fail();
  const sections = new Set<string>(),
    imageVersions = new Map<string, Record<string, unknown>>();
  for (const img of document.images) {
    if (
      !keys(img, [
        "asset_id",
        "asset_revision",
        "asset_version_id",
        "version_digest",
        "normalized_sha256",
        "media_type",
      ]) ||
      !executionId(img.asset_id) ||
      !executionId(img.asset_version_id) ||
      !integer(img.asset_revision, 1) ||
      !executionSha(img.version_digest) ||
      !executionSha(img.normalized_sha256) ||
      img.media_type !== "image/png" ||
      imageVersions.has(img.asset_version_id)
    )
      fail();
    imageVersions.set(img.asset_version_id, img);
  }
  const usedImages = new Set<string>();
  for (const [ordinal, section] of document.sections.entries()) {
    if (
      !keys(section, [
        "section_id",
        "section_revision_id",
        "section_revision",
        "schema_digest",
        "digest",
        "ordinal",
        "title",
        "content",
      ]) ||
      !executionId(section.section_id) ||
      !executionId(section.section_revision_id) ||
      !integer(section.section_revision, 1) ||
      !executionSha(section.schema_digest) ||
      !executionSha(section.digest) ||
      section.ordinal !== ordinal ||
      !text(section.title, 200) ||
      sections.has(section.section_id)
    )
      fail();
    sections.add(section.section_id);
    const content = readAuthoringContent(section.content, true);
    if (
      content.attrs.title !== section.title ||
      (await jsonDigest(section.content)) !== section.digest
    )
      fail();
    content.descendants((node) => {
      if (node.type.name !== "image") return;
      const img = imageVersions.get(node.attrs.asset_version_id);
      if (
        !img ||
        img.asset_id !== node.attrs.asset_id ||
        img.asset_revision !== node.attrs.asset_revision
      )
        fail();
      usedImages.add(node.attrs.asset_version_id);
    });
  }
  if (usedImages.size !== imageVersions.size) fail();
  if (document.outline !== null) {
    if (
      !Array.isArray(document.outline) ||
      document.outline.length !== sections.size
    )
      fail();
    const nodes = new Map<
      string,
      { section_id: string; parent_id: string | null; ordinal: number }
    >();
    const siblings = new Map<string | null, number[]>();
    for (const node of document.outline) {
      if (
        !keys(node, ["section_id", "parent_id", "ordinal", "node_type"]) ||
        !executionId(node.section_id) ||
        !sections.has(node.section_id) ||
        nodes.has(node.section_id) ||
        (node.parent_id !== null && !executionId(node.parent_id)) ||
        !integer(node.ordinal, 0, 499) ||
        !["chapter", "appendix"].includes(String(node.node_type))
      )
        fail();
      nodes.set(node.section_id, {
        section_id: node.section_id,
        parent_id: node.parent_id,
        ordinal: node.ordinal,
      });
      siblings.set(node.parent_id, [
        ...(siblings.get(node.parent_id) ?? []),
        node.ordinal,
      ]);
    }
    for (const n of nodes.values()) {
      const seen = new Set<string>();
      let next: typeof n | undefined = n;
      while (next) {
        if (seen.has(next.section_id) || seen.size >= 6) fail();
        seen.add(next.section_id);
        if (next.parent_id !== null && !nodes.has(next.parent_id)) fail();
        next = next.parent_id === null ? undefined : nodes.get(next.parent_id);
      }
    }
    if (
      [...siblings.values()].some((list) =>
        list.sort((a, b) => a - b).some((v, i) => v !== i),
      )
    )
      fail();
    const ordered: string[] = [];
    function visit(parent: string | null) {
      for (const node of [...nodes.values()]
        .filter((n) => n.parent_id === parent)
        .sort((a, b) => a.ordinal - b.ordinal)) {
        ordered.push(node.section_id);
        visit(node.section_id);
      }
    }
    visit(null);
    if (
      !same(
        ordered,
        document.sections.map((s) => s.section_id),
      )
    )
      fail();
  }
}

function validBuild(build: AuthoringWorkContext["build"]) {
  if (
    !keys(build, [
      "operation_id",
      "operation_state",
      "created_at",
      "outputs",
    ]) ||
    !executionId(build.operation_id) ||
    !Object.hasOwn(contextOperationNames, String(build.operation_state)) ||
    !contextTime(build.created_at) ||
    !Array.isArray(build.outputs) ||
    build.outputs.length < 1 ||
    build.outputs.length > 2
  )
    fail();
  const formats = new Set<string>();
  for (const out of build.outputs) {
    if (
      !keys(out, ["format", "requested", "state", "document", "gaps"]) ||
      !["docx", "pdf"].includes(String(out.format)) ||
      formats.has(String(out.format)) ||
      typeof out.requested !== "boolean" ||
      !["pending", "succeeded", "failed", "not_published"].includes(
        String(out.state),
      ) ||
      !Array.isArray(out.gaps) ||
      out.gaps.length > 100 ||
      !out.gaps.every((v) => text(v, 200))
    )
      fail();
    formats.add(String(out.format));
    if (out.state === "succeeded") {
      const file = out.document;
      if (
        !keys(file, [
          "document_version_id",
          "sha256",
          "byte_size",
          "media_type",
          "publication_proof_digest",
        ]) ||
        !executionId(file.document_version_id) ||
        !executionSha(file.sha256) ||
        !integer(file.byte_size, 1) ||
        !executionSha(file.publication_proof_digest) ||
        file.media_type !==
          (out.format === "pdf"
            ? "application/pdf"
            : "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
      )
        fail();
    } else if (out.document !== null) fail();
    if (
      build.operation_state === "failed" ||
      build.operation_state === "cancelled"
    ) {
      if (out.state !== "not_published") fail();
    } else if (build.operation_state !== "succeeded" && out.state !== "pending")
      fail();
  }
  if (
    !formats.has("docx") ||
    !build.outputs.some((o) => o.requested) ||
    (build.operation_state === "succeeded" &&
      (!build.outputs.some(
        (o) => o.format === "docx" && o.state === "succeeded",
      ) ||
        build.outputs.some(
          (o) => o.state !== "succeeded" && o.state !== "failed",
        )))
  )
    fail();
}

export async function validateAuthoringWorkContext(
  value: unknown,
  bid: string,
  target: WorkContextTarget,
): Promise<AuthoringWorkContext> {
  if (
    !keys(value, [
      "version",
      "selection",
      "selection_digest",
      "observed_at",
      "observation_digest",
      "snapshot",
      "document",
      "build",
      "current_observation",
      "summary",
      "native_targets",
      "original_bytes_reverified",
      "qualification_assessed",
      "limitations",
    ]) ||
    value.version !== "authoring-work-context/1" ||
    !validAuthoringSelection(value.selection, bid) ||
    value.selection.kind !== target.kind ||
    value.selection_digest !== target.selectionDigest ||
    !executionSha(value.selection_digest) ||
    !contextTime(value.observed_at) ||
    !executionSha(value.observation_digest) ||
    value.original_bytes_reverified !== false ||
    value.qualification_assessed !== false ||
    !Array.isArray(value.limitations) ||
    value.limitations.length > 30 ||
    !value.limitations.every((v) => text(v, 100))
  )
    fail();
  const s = value.selection;
  if ((s.kind === "draft_snapshot" ? s.snapshot_id : s.build_id) !== target.id)
    fail();
  if (
    !keys(value.snapshot, [
      ...snapshotKeys,
      "title",
      "created_at",
      "section_count",
    ]) ||
    !snapshotKeys.every(
      (k) =>
        value.snapshot &&
        (value.snapshot as Record<string, unknown>)[k] ===
          (s as unknown as Record<string, unknown>)[k],
    ) ||
    !text(value.snapshot.title, 200) ||
    !contextTime(value.snapshot.created_at) ||
    !integer(value.snapshot.section_count, 0, 500) ||
    !keys(value.current_observation, ["draft_head", "sources", "assets"]) ||
    !Object.values(value.current_observation).every(validContextDimension)
  )
    fail();
  const summary = value.summary;
  if (
    !keys(summary, [
      "perspective",
      "whole_package_blocking_risk_count",
      "whole_package_passed",
      "formal_scoring",
      "official_labels_read",
      "primary_action",
      "action_mode",
    ]) ||
    summary.perspective !== "saved_authoring_history" ||
    summary.whole_package_blocking_risk_count !== null ||
    summary.whole_package_passed !== null ||
    summary.official_labels_read !== false ||
    summary.action_mode !== "navigation_only" ||
    summary.primary_action !==
      (s.kind === "build" ? "view_selected_build" : "open_selected_snapshot") ||
    !keys(summary.formal_scoring, [
      "status",
      "scope_id",
      "numeric_prediction",
    ]) ||
    summary.formal_scoring.status !== "scope_not_selected" ||
    summary.formal_scoring.scope_id !== null ||
    summary.formal_scoring.numeric_prediction !== null
  )
    fail();
  const native = value.native_targets,
    snap = snapshotSelection(s);
  if (
    !keys(native, [
      "draft_snapshot",
      "current_draft",
      "build",
      "build_relations",
    ]) ||
    !validAuthoringSelection(native.draft_snapshot, bid) ||
    (await jsonDigest(native.draft_snapshot)) !== (await jsonDigest(snap)) ||
    !keys(native.current_draft, ["kind", "bid_id", "draft_id"]) ||
    native.current_draft.kind !== "draft" ||
    native.current_draft.bid_id !== bid ||
    native.current_draft.draft_id !== s.draft_id
  )
    fail();
  if (s.kind === "build") {
    if (
      !validAuthoringSelection(native.build, bid) ||
      (await jsonDigest(native.build)) !== (await jsonDigest(s)) ||
      !keys(native.build_relations, ["kind", "bid_id", "build_id"]) ||
      native.build_relations.kind !== "build_package_relations" ||
      native.build_relations.bid_id !== bid ||
      native.build_relations.build_id !== s.build_id ||
      value.document !== null
    )
      fail();
    validBuild(value.build as AuthoringWorkContext["build"]);
  } else {
    if (
      native.build !== null ||
      native.build_relations !== null ||
      value.build !== null
    )
      fail();
    await validDocument(
      value.document as AuthoringWorkContext["document"],
      value.snapshot as AuthoringWorkContext["snapshot"],
    );
  }
  const observed = { ...value };
  delete observed.observed_at;
  delete observed.observation_digest;
  if (
    (await jsonDigest(s)) !== target.selectionDigest ||
    (await jsonDigest(observed)) !== value.observation_digest
  )
    fail();
  return value as AuthoringWorkContext;
}

export type ExactBuildSelection = WorkContextBuildSelection;
