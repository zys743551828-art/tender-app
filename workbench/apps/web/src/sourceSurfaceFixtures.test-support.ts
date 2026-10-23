import type {
  DocumentEvidenceView,
  DocumentView,
  DownloadGrant,
  RetrievalResult,
} from "./contracts";

export const sourceDocument: DocumentView = {
  id: "source-v1",
  bid_id: "source-bid",
  filename: "合成工期要求.pdf",
  role: "tender",
  artifact_kind: "source_original",
  sha256: "a".repeat(64),
  byte_size: 700,
  media_type: "application/pdf",
  obtained_at: "2026-10-21T00:00:00Z",
  parse_coverage: "partial",
  file_id: "source-file",
  file_revision: 1,
  previous_version_id: null,
  file_head_revision: 1,
  file_head_version_id: "source-v1",
  source_relation: null,
};
export const sourceEvidence: DocumentEvidenceView = {
  document_version_id: sourceDocument.id,
  parse_run_id: "source-parse",
  coverage: "partial",
  gaps: ["合成资料仅覆盖三页文字，不证明规则完整。"],
  items: [1, 2, 3].map((page) => ({
    id: `source-evidence-${page}`,
    document_version_id: sourceDocument.id,
    parse_run_id: "source-parse",
    physical_page: page,
    printed_label: null,
    quote: `合成第${page}页：总工期240日历天，雨季条件另见附件。`,
    kind: "text",
    source_status: "published",
    bbox: null,
    page_width: 612,
    page_height: 792,
    rotation: 0,
  })),
};
export const sourceGrant: DownloadGrant = {
  artifact_id: sourceDocument.id,
  download_url: "/synthetic.pdf",
  expires_at: "2099-01-01T00:00:00Z",
  filename: sourceDocument.filename,
  artifact_kind: "source_original",
  presentation_revision: null,
};
export const sourceRetrieval: RetrievalResult = {
  trace_id: "source-trace",
  policy_digest: "explicit-synthetic-policy",
  coverage: "partial",
  gaps: ["合成检索，未覆盖图像与规则全集。"],
  hits: [
    {
      chunk_id: "source-chunk",
      source_version_id: sourceDocument.id,
      parse_run_id: "source-parse",
      physical_page: 3,
      citation_id: "source-citation",
      excerpt: sourceEvidence.items[2].quote,
      embedding_profile_id: "synthetic-not-a-model",
      rank: 1,
    },
  ],
};

export function sourceSurfaceFixture() {
  const state = { calls: [] as string[], unexpected: [] as string[] };
  const fetcher: typeof fetch = async (input, init) => {
    const pathname = new URL(String(input), window.location.origin).pathname;
    state.calls.push(`${init?.method ?? "GET"} ${pathname}`);
    const routes: Record<string, unknown> = {
      "/api/v1/retrievals": sourceRetrieval,
      [`/api/v1/documents/${sourceDocument.id}`]: sourceDocument,
      [`/api/v1/documents/${sourceDocument.id}/evidence`]: sourceEvidence,
      [`/api/v1/artifacts/${sourceDocument.id}/download`]: sourceGrant,
    };
    if (!(pathname in routes)) {
      state.unexpected.push(pathname);
      throw new Error(`Unconfigured synthetic source route: ${pathname}`);
    }
    return new Response(JSON.stringify(routes[pathname]), {
      headers: { "Content-Type": "application/json" },
    });
  };
  return { state, fetcher };
}
