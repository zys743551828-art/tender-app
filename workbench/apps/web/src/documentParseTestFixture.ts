/** Explicit synthetic protocol fixture. No OCR/model or real document was processed. */
import type {
  DocumentParseContext,
  DocumentParsePage,
  DocumentParseStarted,
  DocumentParseView,
  DocumentView,
  DownloadGrant,
} from "./contracts";
import type {
  DocumentParseScope,
  PendingDocumentParse,
} from "./documentParseProtocol";
import { frozenManifestDigest } from "./packageFrozenInput";
export const documentParseTestId = (value: number) =>
  `00000000-0000-4000-8000-${value.toString(16).padStart(12, "0")}`;
export async function documentParseTestFixture() {
  const scope: DocumentParseScope = {
      memberId: documentParseTestId(1),
      bidId: documentParseTestId(2),
      documentId: documentParseTestId(3),
    },
    bytes = new TextEncoder().encode(
      "%PDF-1.4\nexplicit synthetic bytes, not a rendered or parsed PDF",
    ),
    sha = Array.from(
      new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
      (byte) => byte.toString(16).padStart(2, "0"),
    ).join("");
  const context: DocumentParseContext["context"] = {
    protocol: "document-parse-context/1",
    bid_id: scope.bidId,
    document_version_id: scope.documentId,
    document: {
      sha256: sha,
      byte_size: bytes.length,
      media_type: "application/pdf",
      filename: "合成解析样例.pdf",
      file_id: documentParseTestId(4),
      file_revision: 2,
      role: "body",
      artifact_kind: "bid_body",
      locator_digest: "1".repeat(64),
    },
    qualification: { kind: "verified_upload", identity_digest: "2".repeat(64) },
    source: {
      root_id: documentParseTestId(5),
      state: "unregistered",
      authority_digest: await frozenManifestDigest([]),
    },
    method: {
      protocol: "document-parse-method/1",
      mode: "physical_text_only",
      parser_digest: "3".repeat(64),
      config_digest: "4".repeat(64),
      implementation_digest: "5".repeat(64),
      max_bytes: 104857600,
      max_pages: 1000,
    },
    word_coverage_claimed: false,
    current_body_changed: false,
    automatically_started_review: false,
  };
  const wrapper: DocumentParseContext = {
      context,
      context_digest: await frozenManifestDigest(context),
    },
    pending: PendingDocumentParse = {
      key: documentParseTestId(6),
      body: {
        context_digest: wrapper.context_digest,
        reason: "核对合成样例的页内文本",
      },
    },
    request: DocumentParseView = {
      protocol: "document-parse-request/1",
      id: documentParseTestId(7),
      bid_id: scope.bidId,
      document_version_id: scope.documentId,
      actor_id: scope.memberId,
      created_at: "2026-10-20T11:12:13.123456+00:00",
      context,
      context_digest: wrapper.context_digest,
      reason: pending.body.reason,
      operation: {
        id: documentParseTestId(8),
        kind: "parse-document",
        state: "queued",
        input_digest: wrapper.context_digest,
        handler_version: "document-parse/1",
        error_code: null,
        created_at: "2026-10-20T11:12:13.123456+00:00",
        finished_at: null,
      },
      result: null,
      current_body_changed: false,
      automatically_started_review: false,
    },
    completed: DocumentParseView = {
      ...structuredClone(request),
      operation: {
        ...request.operation,
        state: "succeeded",
        finished_at: "2026-10-20T11:12:14.000000+00:00",
      },
      result: {
        parse_run_id: documentParseTestId(9),
        document_version_id: scope.documentId,
        source_digest: sha,
        parser_digest: context.method.parser_digest,
        config_digest: context.method.config_digest,
        parsed_digest: "6".repeat(64),
        coverage: "partial",
        page_count: 2,
        evidence_count: 3,
        gaps: ["合成样例图像内容未覆盖"],
        gap_count: 1,
        word_coverage_claimed: false,
      },
    },
    document: DocumentView = {
      id: scope.documentId,
      bid_id: scope.bidId,
      filename: context.document.filename,
      role: "body",
      artifact_kind: "bid_body",
      sha256: sha,
      byte_size: bytes.length,
      media_type: "application/pdf",
      obtained_at: request.created_at,
      parse_coverage: "partial",
      file_id: context.document.file_id,
      file_revision: 2,
      previous_version_id: documentParseTestId(10),
      file_head_revision: 2,
      file_head_version_id: scope.documentId,
      source_relation: null,
    },
    grant: DownloadGrant = {
      artifact_id: scope.documentId,
      download_url: "/synthetic/parse-original",
      expires_at: "2026-10-20T12:12:14+00:00",
      filename: context.document.filename,
      artifact_kind: "bid_body",
      presentation_revision: null,
    };
  const ack = async (
    body = pending.body,
    selected = request,
    reused = false,
  ): Promise<DocumentParseStarted> => ({
    protocol: "document-parse-start/1",
    actor_id: scope.memberId,
    command_id: documentParseTestId(11),
    request_digest: await frozenManifestDigest({
      body: { bid_id: scope.bidId, ...body },
      if_match: null,
    }),
    reused,
    request: selected,
  });
  const page = (items = [completed]): DocumentParsePage => ({
    bid_id: scope.bidId,
    document_version_id: scope.documentId,
    items,
    has_more: false,
    next_cursor: null,
  });
  return {
    scope,
    wrapper,
    pending,
    request,
    completed,
    document,
    grant,
    bytes,
    ack,
    page,
  };
}
