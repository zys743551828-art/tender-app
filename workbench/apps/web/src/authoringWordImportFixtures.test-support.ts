// Synthetic interface fixtures only; never a real Word import or business acceptance.
import type {
  AuthoringRichDocument,
  AuthoringWordImportCandidate,
  AuthoringWordImportCapabilities,
  AuthoringWordImportResult,
  DraftView,
  WordOriginalView,
} from "./contracts";
import type { ApiResult } from "./api";

export const importId = (value: number) =>
  `00000000-0000-4000-8000-${String(value).padStart(12, "0")}`;
export const importScope = {
  memberId: importId(1),
  bidId: importId(2),
  draftId: importId(3),
};
export const importHead: ApiResult<DraftView> = {
  data: {
    id: importScope.draftId,
    bid_id: importScope.bidId,
    revision: 7,
    snapshot_id: importId(4),
    sections: [
      {
        id: importId(9),
        title: "原有方案",
        ordinal: 0,
        revision: 3,
        rule_ids: [],
        save_state: "saved",
      },
    ],
  },
  etag: '"draft-7"',
};
export const importCapabilities: AuthoringWordImportCapabilities = {
  enabled: true,
  unavailable_reason: null,
  method_digest: "b".repeat(64),
  method: { profile: "bounded-docx-test" },
  supported: ["段落、标题、列表、规则表格和PNG/JPEG图片"],
  limitations: ["不支持内容须明确确认或阻断；不宣称任意Word排版保真。"],
  limits: {
    max_docx_bytes: 33554432,
    max_candidate_bytes: 8388608,
    max_sections: 100,
    max_images: 50,
  },
  append_only: true,
  requires_registered_original: true,
  requires_loss_acknowledgement: true,
};
export const importOriginal: WordOriginalView = {
  id: importId(6),
  bid_id: importScope.bidId,
  file_id: importId(7),
  original_name: "合成施工方案.docx",
  role: "body",
  original_saved: true,
  source_sha256: "a".repeat(64),
  byte_size: 23000,
  inspection: {
    schema: "word-intake-inspection/1",
    container_validated: true,
    entry_count: 2,
    expanded_bytes: 50000,
    xml_part_count: 1,
    active_content_gaps: [],
    unsupported_layout_features: [],
    requested_fonts: [],
    conversion_eligible: true,
    text_digest: "c".repeat(64),
  },
  conversion: {
    state: "failed",
    operation_id: null,
    conversion_attempted: false,
    coverage: "failed",
    error_code: "WORD_RENDERER_NOT_CONFIGURED",
    retryable: false,
    gaps: [],
    pdf_document_version_id: null,
    controlled_render_verified: false,
  },
  message: "合成原件已保存",
  delivery_check_message: "Word交付未获对应检查资格",
  review_qualification: "not_established_by_conversion",
  primary_action: {
    action: "upload_modified_pdf",
    label: "上传此修改稿的PDF",
    context: {
      bid_id: importScope.bidId,
      role: "body",
      declared_source_document_version_id: importId(6),
      target: { kind: "new_file" },
    },
  },
  converted_pdf_action: null,
};
const paragraph = (id: number, value: string) => ({
  type: "paragraph" as const,
  attrs: { id: importId(id) },
  content: [{ type: "text" as const, text: value }],
});
function document(
  title: string,
  content: AuthoringRichDocument["content"],
): AuthoringRichDocument {
  return {
    type: "doc",
    attrs: { title, ordinal: 0, rule_ids: [], source_refs: [] },
    content,
  };
}
export function importCandidate(): AuthoringWordImportCandidate {
  return {
    candidate_id: importId(8),
    bid_id: importScope.bidId,
    draft_id: importScope.draftId,
    candidate_digest: "e".repeat(64),
    source: {
      document_version_id: importOriginal.id,
      digest: importOriginal.source_sha256,
      byte_size: importOriginal.byte_size,
      media_type:
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      filename: importOriginal.original_name,
      role: "body",
      file_id: importOriginal.file_id,
      file_revision: 2,
      intake_digest: "c".repeat(64),
    },
    base_draft_revision: 7,
    method_digest: importCapabilities.method_digest,
    state: "ready",
    created_at: "2026-10-21T12:00:00Z",
    created_by: importScope.memberId,
    section_count: 2,
    image_count: 0,
    warning_count: 1,
    blocker_count: 0,
    protocol: "authoring-word-import-candidate/1",
    base_snapshot_id: importId(4),
    base_draft_etag: importHead.etag!,
    before_digest: "d".repeat(64),
    existing_sections: [
      {
        section_id: importId(9),
        parent_id: null,
        ordinal: 0,
        title: "原有方案",
      },
    ],
    method: importCapabilities.method,
    sections: [
      {
        key: importId(10),
        parent_key: null,
        section_id: importId(11),
        parent_id: null,
        ordinal: 1,
        title: "施工组织",
        source_path: "word/document.xml/body/p[1]",
        content: document("施工组织", [
          paragraph(20, "先核对原件，再追加新章节。"),
        ]),
      },
      {
        key: importId(12),
        parent_key: importId(10),
        section_id: importId(13),
        parent_id: importId(11),
        ordinal: 0,
        title: "进度安排",
        source_path: "word/document.xml/body/p[2]",
        content: document("进度安排", [
          {
            type: "table",
            attrs: {
              id: importId(21),
              column_widths_twips: [2400, 2400],
              caption: "原稿进度表",
            },
            content: [
              {
                type: "tableRow",
                attrs: { id: importId(22) },
                content: [
                  {
                    type: "tableCell",
                    attrs: {
                      id: importId(23),
                      colspan: 2,
                      rowspan: 1,
                      header: true,
                    },
                    content: [paragraph(24, "合并表头")],
                  },
                ],
              },
              {
                type: "tableRow",
                attrs: { id: importId(25) },
                content: [
                  {
                    type: "tableCell",
                    attrs: {
                      id: importId(26),
                      colspan: 1,
                      rowspan: 1,
                      header: false,
                    },
                    content: [paragraph(27, "第一阶段")],
                  },
                  {
                    type: "tableCell",
                    attrs: {
                      id: importId(28),
                      colspan: 1,
                      rowspan: 1,
                      header: false,
                    },
                    content: [paragraph(29, "120天")],
                  },
                ],
              },
            ],
          },
        ]),
      },
    ],
    mapping: [
      {
        source_path: "word/document.xml/body/p[1]",
        section_key: importId(10),
        node_id: importId(20),
        kind: "paragraph",
      },
      {
        source_path: "word/document.xml/body/tbl[1]",
        section_key: importId(12),
        node_id: importId(21),
        kind: "table",
      },
    ],
    images: [],
    issues: [
      {
        id: "f".repeat(64),
        code: "EXPLICIT_STYLE_LOSS",
        severity: "warning",
        source_path: "word/styles.xml",
        message: "原稿段前间距不在当前支持范围，将采用草稿版式。",
      },
    ],
    can_apply: true,
    current_validity: "rechecked_on_append",
    append_only: true,
    reason: "核对本次原件后追加",
    preparation: {
      command_id: importId(14),
      actor_id: importScope.memberId,
      idempotency_key: importId(5),
      request_digest: "a".repeat(64),
      request: {
        source_document_version_id: importOriginal.id,
        source_digest: importOriginal.source_sha256,
        source_byte_size: importOriginal.byte_size,
        base_draft_revision: 7,
        method_digest: importCapabilities.method_digest,
        reason: "核对本次原件后追加",
      },
      if_match: importHead.etag,
    },
    resolution: null,
  };
}
export function importResolution(
  candidate: AuthoringWordImportCandidate,
  options: RequestInit,
): AuthoringWordImportResult {
  const body = JSON.parse(String(options.body));
  const append = body.decision === "append";
  return {
    bid_id: importScope.bidId,
    draft_id: importScope.draftId,
    candidate_id: candidate.candidate_id,
    candidate_digest: candidate.candidate_digest,
    decision: body.decision,
    state: append ? "applied" : "rejected",
    created_section_ids: append
      ? candidate.sections.map((section) => section.section_id)
      : [],
    draft_revision: append ? 8 : null,
    snapshot_id: append ? importId(15) : null,
    snapshot_digest: append ? "9".repeat(64) : null,
    resolved_at: "2026-10-21T12:05:00Z",
    command: {
      command_id: importId(16),
      actor_id: importScope.memberId,
      idempotency_key: new Headers(options.headers).get("Idempotency-Key")!,
      request_digest: "8".repeat(64),
      request: body,
      if_match: new Headers(options.headers).get("If-Match"),
    },
  };
}

export const importImageBytes = Uint8Array.from(
  atob(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGPUqIhiYGBgYmBgYGBgAAALsAD+RwelUQAAAABJRU5ErkJggg==",
  ),
  (character) => character.charCodeAt(0),
);
export function importCandidateWithImage(): AuthoringWordImportCandidate {
  const value = importCandidate();
  value.image_count = 1;
  value.images = [
    {
      key: importId(30),
      source_part: "word/media/image1.png",
      source_digest:
        "d18ee36432593f54cfb63f898fb3e56ed2f9044d3952026136bbbefb7615a0ef",
      source_byte_size: 79,
      source_media_type: "image/png",
      media_type: "image/png",
      digest:
        "d18ee36432593f54cfb63f898fb3e56ed2f9044d3952026136bbbefb7615a0ef",
      byte_size: 79,
      width_px: 2,
      height_px: 2,
    },
  ];
  (value.sections[0].content as AuthoringRichDocument).content.push({
    type: "image",
    attrs: {
      id: importId(32),
      asset_id: importId(30),
      asset_revision: 1,
      asset_version_id: importId(31),
      width_twips: 1440,
      height_twips: 1440,
      alt: "合成示意图",
      caption: "已绑定原件图片的候选预览",
    },
  });
  value.mapping.push({
    source_path: "word/document.xml/body/p[3]/drawing",
    section_key: value.sections[0].key,
    node_id: importId(32),
    kind: "image",
  });
  return value;
}
