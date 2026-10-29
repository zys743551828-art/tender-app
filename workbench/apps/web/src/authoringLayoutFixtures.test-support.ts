// Explicit synthetic HTTP state for component/browser layout checks only.
// It does not call a provider, convert originals, or establish business quality.
import type {
  AuthoringCapabilities,
  AuthoringTreeView,
  DraftView,
  SaveDraft,
  SectionView,
  WorkConversationView,
  WorkMessageView,
} from "./contracts";
import { generationCapabilities } from "./authoringGenerationFixtures.test-support";
import { importCapabilities } from "./authoringWordImportFixtures.test-support";

const id = (n: number) =>
  `20000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
export const layoutScope = {
  memberId: id(1),
  bidId: id(2),
  draftId: id(3),
  sectionId: id(4),
  nextSectionId: id(5),
};
const digest = "a".repeat(64);
const titles = ["施工组织与进度", "质量保障措施"];
export function authoringLayoutFixture() {
  const scope = layoutScope;
  const sections: SectionView[] = titles.map((title, i) => ({
    id: id(4 + i),
    draft_id: scope.draftId,
    revision: 1,
    schema_digest: digest,
    writing_plan_id: null,
    content: {
      type: "doc",
      attrs: { title, ordinal: i, rule_ids: [], source_refs: [] },
      content: [
        {
          type: "heading",
          attrs: { id: id(40 + i), level: 2 },
          content: [{ type: "text", text: title }],
        },
        ...Array.from({ length: 5 }, (_, n) => ({
          type: "paragraph" as const,
          attrs: { id: id(50 + i * 10 + n) },
          content: [
            {
              type: "text" as const,
              text: `合成界面验收段落 ${n + 1}：正文保持可编辑；工期、工程量与来源仍需以真实招标条款核对。这里不表示实际投标资料已通过审查。`,
            },
          ],
        })),
      ],
    },
  }));
  const draft: DraftView = {
    id: scope.draftId,
    bid_id: scope.bidId,
    revision: 1,
    snapshot_id: id(6),
    sections: sections.map((section, i) => ({
      id: section.id,
      title: titles[i],
      ordinal: i,
      revision: 1,
      rule_ids: [],
      save_state: "saved",
    })),
  };
  const capabilities: AuthoringCapabilities = {
    schema_digest: digest,
    schema: { version: 1, nodes: [], marks: [], metadata: [] },
    default_template_version_id: id(8),
    formats: ["docx"],
    supports_external_docx_import: false,
    supported_nodes: ["paragraph", "heading"],
    unsupported: [],
  };
  const conversation: WorkConversationView = {
    id: id(10),
    bid_id: scope.bidId,
    scope: "project",
    is_main: true,
    state: "active",
    revision: 1,
    title: "合成项目主会话",
    stream_id: null,
    created_at: "2026-01-01T00:00:00Z",
  };
  const messages: WorkMessageView[] = Array.from({ length: 12 }, (_, n) => ({
    id: id(100 + n),
    bid_id: scope.bidId,
    conversation_id: conversation.id,
    client_message_id: null,
    created_by: scope.memberId,
    recorded: true,
    assistant_operation_id: null,
    formal_scoring_input: false,
    role: n % 2 ? "assistant" : "user",
    parts: [
      {
        type: "text",
        text:
          n === 11
            ? "当前参考回复：逐段核对进度安排，修改预览后再明确采用。"
            : `第 ${n + 1} 条合成历史讨论：本消息不自动改正文或解决风险。`,
      },
    ],
    created_at: `2026-01-01T00:${String(n).padStart(2, "0")}:00Z`,
  }));
  const state = {
    saveMode: "ok" as "ok" | "offline" | "lost_ack",
    writes: [] as {
      path: string;
      key: string | null;
      etag: string | null;
      body: unknown;
    }[],
    unexpected: [] as string[],
    appliedSaves: 0,
    draft,
    sections,
    messages,
  };
  const receipts = new Map<string, unknown>();
  function response(
    data: unknown,
    status = 200,
    etag = `"draft:${draft.revision}"`,
  ) {
    return new Response(JSON.stringify(data), {
      status,
      headers: { "Content-Type": "application/json", ETag: etag },
    });
  }
  const unavailable = {
    code: "SYNTHETIC_LAYOUT_ONLY",
    message: "此合成界面核对不调用生成或原件转换。",
  };
  const fetcher: typeof fetch = async (input, options = {}) => {
    const url = new URL(
      typeof input === "string" || input instanceof URL ? input : input.url,
      window.location.href,
    );
    const route = url.pathname.replace(/^\/api\/v1/, "");
    const method = options.method ?? "GET";
    if (method !== "GET") {
      const headers = new Headers(options.headers),
        body = options.body ? JSON.parse(String(options.body)) : null;
      const write = {
        path: route,
        key: headers.get("Idempotency-Key"),
        etag: headers.get("If-Match"),
        body,
      };
      state.writes.push(write);
      if (
        method === "PATCH" &&
        route === `/bids/${scope.bidId}/drafts/${scope.draftId}`
      ) {
        if (state.saveMode === "offline")
          throw new TypeError("合成断网：尚未取得保存确认");
        if (write.key && receipts.has(write.key))
          return response(receipts.get(write.key));
        const request = body as SaveDraft;
        for (const change of request.changes) {
          const section = sections.find(
            (item) => item.id === change.section_id,
          )!;
          section.content = structuredClone(change.content);
          section.revision++;
          const summary = draft.sections.find(
            (item) => item.id === section.id,
          )!;
          summary.revision = section.revision;
          summary.title = String(section.content.attrs.title);
        }
        draft.revision++;
        state.appliedSaves++;
        const saved = {
          draft_id: draft.id,
          draft_revision: draft.revision,
          snapshot_id: draft.snapshot_id,
          sections: [],
        };
        if (write.key) receipts.set(write.key, saved);
        if (state.saveMode === "lost_ack") {
          state.saveMode = "ok";
          throw new TypeError("合成保存已提交但回执丢失");
        }
        return response(saved);
      }
      state.unexpected.push(`${method} ${route}`);
      throw new Error(`Unconfigured synthetic write: ${method} ${route}`);
    }
    if (route === `/bids/${scope.bidId}`)
      return response({
        id: scope.bidId,
        title: "整份投标文件 · 合成编制项目",
        phase: "working",
        material_revision: 1,
        archived_at: null,
        stream_id: null,
      });
    if (route.endsWith("/review-state"))
      return response({
        bid_id: scope.bidId,
        request: null,
        current_review: null,
      });
    if (route.endsWith("/settings")) return response({ price_formula: null });
    if (route === "/bids")
      return response({ items: [], has_more: false, next_cursor: null });
    if (route === "/authoring/capabilities") return response(capabilities);
    if (route === "/authoring/rich-capabilities")
      return response({
        schema_digest: "b".repeat(64),
        schema: {},
        build_schema_digest: "c".repeat(64),
        image_upload_max_bytes: 8388608,
        renderer_configured: false,
        runtime_verified_by_this_read: false,
        table_pdf_geometry: "unverified",
        pagination_modes: [
          { mode: "chapter_start_new_page", page_count_impact: "每章另起一页" },
        ],
      });
    if (route === "/authoring/generation-batch-capabilities")
      return response({
        ...generationCapabilities,
        enabled: false,
        unavailable_reason: unavailable,
        price: null,
        estimates: [],
      });
    if (route === "/authoring/word-import-capabilities")
      return response({
        ...importCapabilities,
        enabled: false,
        unavailable_reason: unavailable,
      });
    if (route === `/bids/${scope.bidId}/drafts`)
      return response({
        items: [{ ...draft, title: "投标正文合成草稿" }],
        next_cursor: null,
        has_more: false,
      });
    if (route === `/bids/${scope.bidId}/drafts/${scope.draftId}`)
      return response(draft);
    if (route === `/bids/${scope.bidId}/draft-snapshots/${draft.snapshot_id}`)
      return response({
        snapshot_id: draft.snapshot_id,
        snapshot_digest: digest,
        title: "投标正文合成草稿",
        sections: sections.map((section) => section.content),
      });
    if (route === `/bids/${scope.bidId}/drafts/${scope.draftId}/structure`) {
      const tree: AuthoringTreeView = {
        draft_id: draft.id,
        draft_revision: draft.revision,
        snapshot_id: draft.snapshot_id,
        structure_version_id: id(7),
        nodes: draft.sections.map((section) => ({
          section_id: section.id,
          parent_id: null,
          ordinal: section.ordinal,
          node_type: "chapter",
          deleted: false,
          section_revision: section.revision,
          plan_version_id: null,
          template_family_id: null,
          template_key: null,
          title: section.title,
          rule_ids: [],
          source_refs: [],
          plan: null,
          plan_content_basis_state: "none",
          actual_page_range: null,
        })),
        directory_template_version_id: id(8),
        style_template_version_id: id(9),
        metadata: {},
        page_budget: {
          planned_total: 0,
          unknown_section_ids: sections.map((item) => item.id),
          actual_total: null,
          actual_ranges_state: "unknown",
        },
      };
      return response(tree);
    }
    if (route.startsWith("/sections/")) {
      const section = sections.find((item) => route === `/sections/${item.id}`);
      if (section) return response(section);
      if (route.endsWith("/revisions"))
        return response({ items: [], next_cursor: null });
    }
    if (route.endsWith("/builds"))
      return response({ items: [], next_cursor: null });
    if (route === "/authoring/templates")
      return response({
        items: [],
        next_cursor: null,
        coverage: "partial",
        notice: "合成模板目录",
      });
    if (route.startsWith("/authoring/template-versions/"))
      return response({
        id: route.split("/").at(-1),
        family_id: id(20),
        name: "合成内置模板",
        kind: route.endsWith(id(9)) ? "layout" : "outline",
        revision: 1,
        config: route.endsWith(id(9))
          ? {
              schema_version: 1,
              page: "A4",
              font: "Noto Sans CJK SC",
              font_size_halfpoints: 22,
              margin_top_twips: 1440,
              margin_right_twips: 1440,
              margin_bottom_twips: 1440,
              margin_left_twips: 1440,
              paragraph_after_twips: 0,
              cover_enabled: false,
              cover_title: "正文",
              header_text: "",
              footer_text: "",
              page_number: true,
              chapter_numbering: "decimal",
              toc_enabled: true,
            }
          : { schema_version: 1, nodes: [] },
        previous_version_id: null,
      });
    if (route.endsWith("/rules")) return response({ rules: [] });
    if (route.endsWith("/materials"))
      return response({ documents: [], conflicts: [] });
    if (route.endsWith("/conversations/main"))
      return response(conversation, 200, '"conversation:1"');
    if (route.endsWith("/messages"))
      return response({ items: messages, has_more: false, before: null });
    if (route === "/assistant/jobs") return response({ items: [] });
    if (route === "/assistant/sources")
      return response({
        items: [],
        coverage: "partial",
        notice: "仅合成来源列表；没有真实原件。",
      });
    state.unexpected.push(route);
    throw new Error(`Unconfigured synthetic read: ${route}`);
  };
  return { state, fetcher, capabilities, scope };
}
