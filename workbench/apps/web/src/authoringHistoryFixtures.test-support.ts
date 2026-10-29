// Explicit synthetic fixtures for the real history UI; not production records.
import type {
  AuthoringHistoricalSectionView,
  AuthoringImageView,
  AuthoringRevisionPage,
  AuthoringRichDocument,
  DraftSaved,
} from "./contracts";
import type { AuthoringHead } from "./SectionEditor";
import { jsonDigest } from "./editorSchema";
import {
  importCandidate,
  importCandidateWithImage,
  importId,
  importImageBytes,
  importScope,
} from "./authoringWordImportFixtures.test-support";

export const historyScope = {
  ...importScope,
  sectionId: importId(90),
};
export const historyTail = "完整历史正文的最后一句仍须保留。";
export const historyLongText = "历史正文完整保留。".repeat(12000) + historyTail;
export const historyJson = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });

export async function historyFixture(
  options: { image?: boolean; long?: boolean } = {},
) {
  const source = options.image ? importCandidateWithImage() : importCandidate();
  const content = structuredClone(
    source.sections[0].content,
  ) as AuthoringRichDocument;
  content.attrs.ordinal = 7;
  content.attrs.title = "历史施工方案";
  content.content.unshift({
    type: "paragraph",
    attrs: { id: importId(91) },
    content: [
      {
        type: "text",
        text: options.long ? historyLongText : "所选历史正文完整保留。",
      },
    ],
  });
  content.content.push(
    ...structuredClone(
      (importCandidate().sections[1].content as AuthoringRichDocument).content,
    ),
  );
  const imageProof = {
    protocol: "authoring-raster-normalization/1",
    output_digest:
      "d18ee36432593f54cfb63f898fb3e56ed2f9044d3952026136bbbefb7615a0ef",
    output_byte_size: importImageBytes.length,
    output_media_type: "image/png",
    width_px: 2,
    height_px: 2,
  };
  const image: AuthoringImageView = {
    id: importId(31),
    bid_id: historyScope.bidId,
    asset_id: importId(30),
    revision: 1,
    previous_revision: null,
    previous_version_id: null,
    state: "active",
    reason: "合成历史图片",
    original_blob_id: importId(40),
    normalized_blob_id: importId(41),
    original_media_type: "image/png",
    width_px: 2,
    height_px: 2,
    normalization_proof: imageProof,
    source_refs: [],
    digest: "a".repeat(64),
    created_by: historyScope.memberId,
    created_at: "2026-10-21T10:00:00Z",
    title: "合成历史图片",
    head_revision: 2,
    head_version_id: importId(42),
    is_current: false,
    etag: '"image-2"',
  };
  const history: AuthoringHistoricalSectionView = {
    version: "authoring-historical-section/1",
    bid_id: historyScope.bidId,
    draft_id: historyScope.draftId,
    section_id: historyScope.sectionId,
    section_revision_id: importId(102),
    revision: 2,
    schema_digest: "b".repeat(64),
    digest: await jsonDigest(content),
    content,
    created_by: historyScope.memberId,
    created_at: "2026-10-21T10:02:00Z",
    images: options.image
      ? [
          {
            asset_id: image.asset_id,
            asset_revision: image.revision,
            asset_version_id: image.id,
            version_digest: image.digest,
            normalized_sha256: imageProof.output_digest,
            media_type: "image/png",
          },
        ]
      : [],
    read_only: true,
    source_qualification_assessed: false,
    restoration_authorized: false,
  };
  const plain = (text: string): AuthoringRichDocument => ({
    type: "doc",
    attrs: { title: "施工方案", ordinal: 7, rule_ids: [], source_refs: [] },
    content: [
      {
        type: "paragraph",
        attrs: { id: importId(92) },
        content: [{ type: "text", text }],
      },
    ],
  });
  const original = plain("更早一版的明确正文。"),
    current = plain("当前已保存正文，恢复前应予保留。");
  const versions = new Map<number, AuthoringHistoricalSectionView>([
    [
      1,
      {
        ...history,
        revision: 1,
        section_revision_id: importId(101),
        content: original,
        digest: await jsonDigest(original),
        images: [],
        created_at: "2026-10-21T10:01:00Z",
      },
    ],
    [2, history],
    [
      3,
      {
        ...history,
        revision: 3,
        section_revision_id: importId(103),
        content: current,
        digest: await jsonDigest(current),
        images: [],
        created_at: "2026-10-21T10:03:00Z",
      },
    ],
  ]);
  const head: AuthoringHead = {
    draft: {
      id: historyScope.draftId,
      bid_id: historyScope.bidId,
      revision: 3,
      snapshot_id: importId(203),
      sections: [
        {
          id: historyScope.sectionId,
          title: "施工方案",
          ordinal: 0,
          revision: 3,
          rule_ids: [],
          save_state: "saved",
        },
      ],
    },
    section: {
      id: historyScope.sectionId,
      draft_id: historyScope.draftId,
      revision: 3,
      schema_digest: "b".repeat(64),
      content: current,
      writing_plan_id: null,
    },
    etag: '"draft-3"',
  };
  type Call = {
    path: string;
    method: string;
    body: unknown;
    headers: Record<string, string>;
  };
  const state = {
    history,
    image,
    imageProof,
    bytes: importImageBytes.slice(),
    head,
    versions,
    calls: [] as Call[],
    writes: [] as Call[],
    unexpected: [] as string[],
    page: null as AuthoringRevisionPage | null,
    more: null as AuthoringRevisionPage | null,
    restoreMode: "success" as
      | "success"
      | "conflict"
      | "source_stale"
      | "network_once",
    flushAllowed: true,
    flushes: 0,
    refreshes: 0,
  };
  const entry = (value: AuthoringHistoricalSectionView) => ({
    revision: value.revision,
    created_at: value.created_at,
    digest: value.digest,
    created_by: value.created_by,
  });
  const defaultPage = (): AuthoringRevisionPage => ({
    items: [...state.versions.values()]
      .sort((a, b) => b.revision - a.revision)
      .map(entry),
    next_cursor: null,
  });
  const fetcher = async (
    input: string | URL | Request,
    init: RequestInit = {},
  ) => {
    const path = String(input),
      method = init.method ?? "GET";
    const call = {
      path,
      method,
      body: init.body ? JSON.parse(String(init.body)) : null,
      headers: Object.fromEntries(new Headers(init.headers).entries()),
    };
    state.calls.push(call);
    if (method !== "GET") state.writes.push(call);
    if (
      method === "GET" &&
      path === `/api/v1/sections/${historyScope.sectionId}/revisions`
    )
      return historyJson(state.page ?? defaultPage());
    if (
      method === "GET" &&
      path.startsWith(
        `/api/v1/sections/${historyScope.sectionId}/revisions?before=`,
      )
    )
      return historyJson(state.more ?? { items: [], next_cursor: null });
    const prefix = `/api/v1/bids/${historyScope.bidId}/drafts/${historyScope.draftId}/sections/${historyScope.sectionId}/revisions/`;
    if (method === "GET" && path.startsWith(prefix)) {
      const url = new URL(path, "http://localhost");
      const value = state.versions.get(Number(url.pathname.split("/").at(-1)));
      if (!value)
        return historyJson(
          { code: "NOT_FOUND", message: "未找到所选历史修订" },
          404,
        );
      if (url.searchParams.get("expected_digest") !== value.digest)
        return historyJson(
          { code: "AUTHORING_HISTORY_CHANGED", message: "所选历史摘要不一致" },
          412,
        );
      return historyJson(value);
    }
    const imagePath = `/api/v1/bids/${historyScope.bidId}/authoring-images/${image.asset_id}/versions/${image.id}`;
    if (method === "GET" && path === imagePath) return historyJson(state.image);
    if (method === "GET" && path === imagePath + "/bytes/normalized")
      return new Response(state.bytes.slice(), {
        headers: { "Content-Type": "image/png" },
      });
    if (
      method === "POST" &&
      path ===
        `/api/v1/bids/${historyScope.bidId}/sections/${historyScope.sectionId}/restore`
    ) {
      if (state.restoreMode === "network_once") {
        state.restoreMode = "success";
        throw new TypeError("explicit synthetic network interruption");
      }
      if (state.restoreMode === "conflict")
        return historyJson(
          {
            code: "PRECONDITION_FAILED",
            message: "当前草稿已有新版本，请核对后重试。",
          },
          412,
        );
      if (state.restoreMode === "source_stale")
        return historyJson(
          {
            code: "AUTHORING_SOURCE_STALE",
            message: "历史来源已撤回，不能恢复为当前正文。",
          },
          409,
        );
      const old = state.versions.get(
        Number((call.body as { revision: number }).revision),
      )!;
      const next = state.head.draft.revision + 1;
      const saved: DraftSaved = {
        draft_id: historyScope.draftId,
        draft_revision: next,
        snapshot_id: importId(200 + next),
        snapshot_digest: "c".repeat(64),
      };
      state.head = {
        draft: {
          ...state.head.draft,
          revision: next,
          snapshot_id: saved.snapshot_id,
          sections: [{ ...state.head.draft.sections[0], revision: next }],
        },
        section: {
          ...state.head.section,
          revision: next,
          content: old.content,
        },
        etag: `"draft-${next}"`,
      };
      state.versions.set(next, {
        ...old,
        revision: next,
        section_revision_id: importId(100 + next),
        created_at: "2026-10-21T10:04:00Z",
      });
      return historyJson(saved);
    }
    state.unexpected.push(`${method} ${path}`);
    return historyJson(
      { code: "SYNTHETIC_UNEXPECTED", message: "未声明的测试请求" },
      500,
    );
  };
  return { state, fetcher, entry, defaultPage };
}
