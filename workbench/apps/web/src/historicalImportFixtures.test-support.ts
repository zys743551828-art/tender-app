// Synthetic UI fixtures. Actual PostgreSQL and object-byte acceptance is separate.
import type {
  HistoricalImportBatch,
  HistoricalImportReceipt,
  HistoricalImportRecord,
  HistoricalImportRequest,
  HistoricalImportSource,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  historicalImportEtag,
  historicalPreviewTarget,
  type HistoricalPending,
} from "./historicalImportProtocol";

export const importId = (n: number) =>
  `30000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
export const importMember = importId(1);
export function importRecord(n = 1): HistoricalImportRecord {
  return {
    external_record_id: `历史-${String(n).padStart(4, "0")}`,
    bid_id: importId(2),
    actual_document_version_id: importId(3 + n),
    submitted_at: "2025-01-01T09:00:00.123456+08:00",
    evidence_ref: importId(20),
    explanation: "已提交合成正文，保留确切证明。",
    score_kind: n === 1 ? "technical_total" : "unknown",
    value: n === 1 ? "0" : null,
    maximum: n === 1 ? "10.00" : null,
    source_version_id: n === 1 ? importId(21) : null,
    known_at: n === 1 ? "2025-01-03T09:00:00.000001+08:00" : null,
  };
}
export async function importFixture(count = 2) {
  const body: HistoricalImportRequest = {
    records: Array.from({ length: count }, (_, i) => importRecord(i + 1)),
  };
  const batch: HistoricalImportBatch = {
    id: importId(100),
    mode: "dry_run",
    revision: 1,
    manifest_blob_id: importId(101),
    records: body.records.slice(0, 100).map((record, index) => ({
      batch_id: importId(100),
      external_record_id: record.external_record_id,
      source_digest: ((index % 9) + 1).toString().repeat(64),
      state: "pending",
      bid_id: record.bid_id,
      errors: [],
    })),
    next_offset: count > 100 ? 100 : null,
    counts: { total: count, pending: count, imported: 0, errors: 0 },
    formal_sample_admission: "separate_verified_technical_label_check",
    standard_submission_gate_checked: false,
  };
  const source: HistoricalImportSource = {
    batch_id: batch.id,
    manifest_blob_id: batch.manifest_blob_id,
    manifest_digest: await jsonDigest({
      schema: "historical-import/1",
      records: body.records,
    }),
    request: body,
    source_matches_saved_manifest: true,
  };
  return {
    body,
    batch,
    source,
    etag: historicalImportEtag(batch.id, batch.revision),
  };
}
export function importConfirmed(
  batch: HistoricalImportBatch,
  failedLast = false,
): HistoricalImportBatch {
  return {
    ...batch,
    mode: "confirmed_import",
    revision: batch.revision + 1,
    records: batch.records.map((row, index) => ({
      ...row,
      state:
        failedLast && index === batch.records.length - 1
          ? "failed"
          : "imported",
      errors:
        failedLast && index === batch.records.length - 1
          ? ["IMPORT_ORIGINAL_CORRUPTED"]
          : [],
    })),
    counts: {
      ...batch.counts,
      pending: 0,
      imported: batch.counts.total - (failedLast ? 1 : 0),
      errors: failedLast ? 1 : 0,
    },
  };
}
export async function importReceipt(
  batch: HistoricalImportBatch,
  pending: HistoricalPending,
): Promise<HistoricalImportReceipt> {
  return {
    ...batch,
    command: {
      command_id: importId(300),
      actor_id: importMember,
      idempotency_key: pending.key,
      command_kind:
        pending.kind === "preview"
          ? "preview-historical-import"
          : "confirm-historical-import",
      target_id:
        pending.kind === "preview" ? historicalPreviewTarget : pending.batchId,
      request_digest: await jsonDigest({
        body: pending.body,
        if_match: pending.etag,
      }),
      if_match: pending.etag,
    },
  };
}
