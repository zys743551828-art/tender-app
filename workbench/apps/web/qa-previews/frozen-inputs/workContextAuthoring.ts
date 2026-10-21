// Synthetic full-record UI fixtures; native PG/S3 acceptance is recorded separately.
import type {
  AuthoringWorkContext,
  WorkContextAnySelection,
  WorkContextChoicePage,
  WorkContextRelationPage,
} from "../../src/contracts";
import { jsonDigest } from "../../src/editorSchema";
import { importCandidate } from "../../src/authoringWordImportFixtures.test-support";
import type { WorkContextTarget } from "../../src/workContextNavigation";
import { workContextSelectionId } from "../../src/workContextDirectoryProtocol";

export const contextId = (n: number) =>
  `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
export const contextMember = contextId(101);
export async function sealAuthoringContext(c: AuthoringWorkContext) {
  c.selection_digest = await jsonDigest(c.selection);
  const basis: Record<string, unknown> = { ...c };
  delete basis.observed_at;
  delete basis.observation_digest;
  c.observation_digest = await jsonDigest(basis);
  return c;
}
export function contextTarget(c: AuthoringWorkContext): WorkContextTarget {
  return {
    kind: c.selection.kind,
    id: workContextSelectionId(c.selection),
    selectionDigest: c.selection_digest,
  };
}
export async function authoringContextFixture() {
  const source = importCandidate();
  const bid = contextId(102),
    draft = contextId(103);
  const selected = {
    kind: "draft_snapshot" as const,
    bid_id: bid,
    draft_id: draft,
    draft_revision: 7,
    snapshot_id: contextId(104),
    snapshot_digest: "a".repeat(64),
  };
  const sections = await Promise.all(
    source.sections.map(async (s, i) => {
      const content = structuredClone(s.content) as NonNullable<
        AuthoringWorkContext["document"]
      >["sections"][number]["content"];
      content.attrs.ordinal = i;
      return {
        section_id: contextId(110 + i),
        section_revision_id: contextId(120 + i),
        section_revision: 2,
        schema_digest: "b".repeat(64),
        digest: await jsonDigest(content),
        ordinal: i,
        title: s.title,
        content,
      };
    }),
  );
  const snapshot = {
    bid_id: bid,
    draft_id: draft,
    draft_revision: 7,
    snapshot_id: selected.snapshot_id,
    snapshot_digest: selected.snapshot_digest,
    title: "合成项目已保存方案",
    created_at: "2026-10-21T05:00:00Z",
    section_count: sections.length,
  };
  const neutral = {
    status: "unknown" as const,
    selected_digest: null,
    observed_digest: null,
    reason: "REFERENCES_MATCH_QUALIFICATION_UNASSESSED",
  };
  const saved = await sealAuthoringContext({
    version: "authoring-work-context/1",
    selection: selected,
    selection_digest: "",
    observed_at: "2026-10-21T06:00:00Z",
    observation_digest: "",
    snapshot,
    document: {
      sections,
      outline: sections.map((s, i) => ({
        section_id: s.section_id,
        parent_id: i === 1 ? sections[0].section_id : null,
        ordinal: 0,
        node_type: "chapter",
      })),
      images: [],
      editable: false,
    },
    build: null,
    current_observation: {
      draft_head: {
        ...neutral,
        status: "changed",
        reason: "DRAFT_HEAD_CHANGED",
      },
      sources: neutral,
      assets: { ...neutral, status: "not_applicable", reason: "NO_IMAGES" },
    },
    summary: {
      perspective: "saved_authoring_history",
      whole_package_blocking_risk_count: null,
      whole_package_passed: null,
      formal_scoring: {
        status: "scope_not_selected",
        scope_id: null,
        numeric_prediction: null,
      },
      official_labels_read: false,
      primary_action: "open_selected_snapshot",
      action_mode: "navigation_only",
    },
    native_targets: {
      draft_snapshot: selected,
      current_draft: { kind: "draft", bid_id: bid, draft_id: draft },
      build: null,
      build_relations: null,
    },
    original_bytes_reverified: false,
    qualification_assessed: false,
    limitations: [
      "EXPLICIT_SYNTHETIC_UI_FIXTURE",
      "ORIGINAL_BYTES_NOT_REVERIFIED",
    ],
  });
  const built = structuredClone(saved);
  built.selection = {
    ...selected,
    kind: "build",
    build_id: contextId(130),
    build_input_id: contextId(131),
    input_digest: "c".repeat(64),
    manifest_digest: "d".repeat(64),
    writer_kind: "authoring-rich/1",
  };
  built.document = null;
  built.build = {
    operation_id: contextId(132),
    operation_state: "succeeded",
    created_at: "2026-10-21T05:30:00Z",
    outputs: [
      {
        format: "docx",
        requested: true,
        state: "succeeded",
        document: {
          document_version_id: contextId(133),
          sha256: "e".repeat(64),
          byte_size: 2345,
          media_type:
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          publication_proof_digest: "f".repeat(64),
        },
        gaps: [],
      },
      {
        format: "pdf",
        requested: true,
        state: "failed",
        document: null,
        gaps: ["合成转换失败，未发布 PDF"],
      },
    ],
  };
  built.summary.primary_action = "view_selected_build";
  built.native_targets.build = built.selection;
  built.native_targets.build_relations = {
    kind: "build_package_relations",
    bid_id: bid,
    build_id: built.selection.build_id,
  };
  await sealAuthoringContext(built);
  const { kind: _kind, ...seed } = built.selection;
  void _kind;
  const relations: WorkContextRelationPage = {
    version: "package-work-context-relations/1",
    seed,
    target: "package_revision",
    observed_at: saved.observed_at,
    observation_digest: "3".repeat(64),
    items: [
      {
        id: "1".repeat(64),
        kind: "adopted_into",
        output: {
          document_version_id: contextId(133),
          format: "docx",
          sha256: "e".repeat(64),
        },
        package_revision: {
          kind: "package_revision",
          bid_id: bid,
          package_id: contextId(140),
          revision_id: contextId(141),
          package_digest: "2".repeat(64),
        },
        package_revision_number: 3,
        proof_digest: "4".repeat(64),
        adoption_command_id: contextId(142),
        adopted_at: "2026-10-21T05:40:00Z",
        current_package_head: neutral,
        current_source_basis: neutral,
        qualification_assessed: false,
      },
    ],
    total: 1,
    has_more: false,
    next_cursor: null,
    complete_observation: true,
    original_bytes_reverified: false,
    qualification_assessed: false,
  };
  return { bid, member: contextMember, saved, built, relations };
}
export async function contextChoicePage(
  selections: WorkContextAnySelection[],
  kind: WorkContextChoicePage["kind"],
  bid: string,
): Promise<WorkContextChoicePage> {
  return {
    version: "work-context-choice-page/1",
    bid_id: bid,
    kind,
    filters: { draft_id: null, package_id: null, revision_id: null },
    observed_at: "2026-10-21T06:00:00Z",
    observation_digest: "8".repeat(64),
    items: await Promise.all(
      selections.map(async (s, i) => ({
        kind: s.kind,
        id: workContextSelectionId(s),
        label: `合成${kind === "draft_snapshot" ? "已保存草稿" : "阶段记录"} ${i + 1}`,
        created_at: "2026-10-21T05:00:00Z",
        status:
          kind === "draft_snapshot"
            ? "saved"
            : kind === "package_submission"
              ? "standard"
              : "succeeded",
        selection: s,
        selection_digest: await jsonDigest(s),
      })),
    ),
    total: selections.length,
    has_more: false,
    next_cursor: null,
    complete_observation: true,
    directory_basis: "native_record_identity_and_state",
    selection_requires_resolution: true,
    qualification_assessed: false,
  };
}
