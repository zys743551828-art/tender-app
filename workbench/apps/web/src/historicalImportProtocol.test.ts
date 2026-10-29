import { expect, it } from "vitest";
import { ApiError } from "./api";
import { jsonDigest } from "./editorSchema";
import {
  definitiveHistoricalFailure,
  historicalDateTime,
  historicalImportEtag,
  normalizeHistoricalRequest,
  parseHistoricalFile,
  validateHistoricalBatch,
  validateHistoricalDirectory,
  validateHistoricalReceipt,
  validateHistoricalSource,
  type HistoricalPending,
} from "./historicalImportProtocol";
import {
  importConfirmed,
  importFixture,
  importId,
  importMember,
  importReceipt,
  importRecord,
} from "./historicalImportFixtures.test-support";

it("normalizes UUID and datetime spelling without losing offset, microseconds, exact zero or decimal scale", () => {
  const row = importRecord();
  row.bid_id = "ABCDEFAB-0000-4000-8000-000000000002";
  row.submitted_at = "2025-01-01T09:00:00.12+08:00";
  row.known_at = "2025-01-03T01:00:00.000000+00:00";
  row.maximum = "10.0000";
  const result = normalizeHistoricalRequest({ records: [row] }).records[0];
  expect(result).toMatchObject({
    bid_id: row.bid_id.toLowerCase(),
    submitted_at: "2025-01-01T09:00:00.120000+08:00",
    known_at: "2025-01-03T01:00:00Z",
    value: "0",
    maximum: "10.0000",
  });
  expect(historicalDateTime("2025-01-01T00:00:00.000001-04:00")).toBe(
    "2025-01-01T00:00:00.000001-04:00",
  );
  expect(
    normalizeHistoricalRequest({ records: [importRecord(2)] }).records[0].value,
  ).toBeNull();
});
it.each([
  "2025-01-01T00:00:00",
  "2025-02-29T00:00:00Z",
  "2024-02-30T00:00:00Z",
  "2025-01-01T00:00:00.1234567Z",
  "2025-01-01T24:00:00Z",
  "2025-01-01T00:00:00+24:00",
])("rejects invalid or lossy datetime input %s", (value) => {
  expect(() => historicalDateTime(value)).toThrow();
});
it("rejects duplicate records, missing nullable fields, extra fields and unknown-as-zero before persistence", () => {
  const row = importRecord();
  expect(() => normalizeHistoricalRequest({ records: [row, row] })).toThrow(
    /重复/,
  );
  expect(() =>
    normalizeHistoricalRequest({ records: [{ ...row, extra: true }] }),
  ).toThrow(/字段/);
  const { known_at, ...missing } = row;
  expect(known_at).not.toBeNull();
  expect(() => normalizeHistoricalRequest({ records: [missing] })).toThrow(
    /字段/,
  );
  expect(() =>
    normalizeHistoricalRequest({
      records: [{ ...row, score_kind: "unknown", value: "0" }],
    }),
  ).toThrow(/未知成绩/);
  expect(() => parseHistoricalFile('{"records":')).toThrow(/JSON/);
  expect(() =>
    normalizeHistoricalRequest({
      records: Array.from({ length: 1001 }, (_, i) => importRecord(i + 1)),
    }),
  ).toThrow(/1000/);
});
it("binds a saved preview ACK to member, command target, exact normalized request, key and null precondition", async () => {
  const f = await importFixture(),
    pending: HistoricalPending = {
      kind: "preview",
      key: importId(500),
      body: f.body,
      etag: null,
    };
  const receipt = await importReceipt(f.batch, pending);
  await expect(
    validateHistoricalReceipt(receipt, importMember, pending, f.etag),
  ).resolves.toEqual(receipt);
  for (const patch of [
    { actor_id: importId(999) },
    { target_id: importId(998) },
    { idempotency_key: importId(997) },
    { if_match: '"new"' },
    { request_digest: "f".repeat(64) },
  ])
    await expect(
      validateHistoricalReceipt(
        { ...receipt, command: { ...receipt.command, ...patch } },
        importMember,
        pending,
        f.etag,
      ),
    ).rejects.toThrow();
  await expect(
    validateHistoricalReceipt(
      { ...receipt, mode: "confirmed_import" },
      importMember,
      pending,
      f.etag,
    ),
  ).rejects.toThrow();
});
it("binds partial-confirm ACK to the original batch revision and preserves per-row failures", async () => {
  const f = await importFixture(),
    pending: HistoricalPending = {
      kind: "confirm",
      key: importId(501),
      body: {},
      etag: f.etag,
      batchId: f.batch.id,
      baseRevision: 1,
      manifestBlobId: f.batch.manifest_blob_id,
      manifestDigest: f.source.manifest_digest,
    };
  const result = importConfirmed(f.batch, true),
    receipt = await importReceipt(result, pending),
    etag = historicalImportEtag(result.id, 2);
  expect(
    (await validateHistoricalReceipt(receipt, importMember, pending, etag))
      .counts,
  ).toEqual({ total: 2, pending: 0, imported: 1, errors: 1 });
  await expect(
    validateHistoricalReceipt(
      { ...receipt, manifest_blob_id: importId(999) },
      importMember,
      pending,
      etag,
    ),
  ).rejects.toThrow();
  await expect(
    validateHistoricalReceipt(
      receipt,
      importMember,
      { ...pending, etag: '"latest"' },
      etag,
    ),
  ).rejects.toThrow();
});
it("checks the exact saved manifest independently of the server's business deduplication fingerprint", async () => {
  const f = await importFixture();
  expect(f.batch.records[0].source_digest).not.toBe(
    await jsonDigest(f.body.records[0]),
  );
  await expect(validateHistoricalSource(f.source, f.batch)).resolves.toEqual(
    f.source,
  );
  await expect(
    validateHistoricalSource(
      { ...f.source, manifest_digest: "f".repeat(64) },
      f.batch,
    ),
  ).rejects.toThrow();
  await expect(
    validateHistoricalSource({ ...f.source, batch_id: importId(9) }, f.batch),
  ).rejects.toThrow();
  const changed = {
    ...f.source,
    request: {
      records: f.body.records.map((row, i) =>
        i ? row : { ...row, bid_id: importId(998) },
      ),
    },
  };
  changed.manifest_digest = await jsonDigest({
    schema: "historical-import/1",
    records: changed.request.records,
  });
  await expect(validateHistoricalSource(changed, f.batch)).rejects.toThrow();
});
it("rejects inconsistent counts, cross-batch rows and non-progressing record or directory pagination", async () => {
  const f = await importFixture(101);
  expect(validateHistoricalBatch(f.batch, { etag: f.etag })).toEqual(f.batch);
  for (const patch of [
    { next_offset: 0 },
    { next_offset: null },
    { counts: { ...f.batch.counts, total: 102 } },
    { records: f.batch.records.map((row) => ({ ...row, state: "imported" })) },
    { records: [{ ...f.batch.records[0], batch_id: importId(999) }] },
  ])
    expect(() =>
      validateHistoricalBatch({ ...f.batch, ...patch }, { etag: f.etag }),
    ).toThrow();
  expect(() =>
    validateHistoricalDirectory({ items: [], next_offset: 20 }, 0),
  ).toThrow();
});
it("releases only proven top-level rejection and retains unknown, generic schema and storage outcomes", () => {
  for (const [status, code] of [
    [422, "IMPORT_MANIFEST_TOO_LARGE"],
    [422, "IMPORT_DUPLICATE_RECORD_ID"],
    [422, "IMPORT_ORIGINAL_BUDGET_EXCEEDED"],
    [409, "IMPORT_ALREADY_CONFIRMED"],
    [412, "REVISION_CONFLICT"],
  ] as const)
    expect(
      definitiveHistoricalFailure(new ApiError("rejected", status, code)),
    ).toBe(true);
  for (const [status, code] of [
    [0, "NETWORK_ERROR"],
    [422, "INVALID_REQUEST"],
    [412, "UNKNOWN_PRECONDITION"],
    [503, "OBJECT_STORAGE_UNAVAILABLE"],
    [409, "IMPORT_MANIFEST_INVALID"],
    [409, "IDEMPOTENCY_CONFLICT"],
    [409, "COMMAND_INCOMPLETE"],
    [403, "FORBIDDEN"],
  ] as const)
    expect(
      definitiveHistoricalFailure(new ApiError("unknown", status, code)),
    ).toBe(false);
});
