import { beforeEach, expect, it } from "vitest";
import { clearRecordedCommands } from "./recordedCommandStorage";
import {
  historicalStorageKey,
  readHistoricalRecovery,
  writeHistoricalRecovery,
  type HistoricalRecovery,
} from "./historicalImportRecovery";
import {
  importFixture,
  importId,
  importMember,
} from "./historicalImportFixtures.test-support";

beforeEach(() => sessionStorage.clear());
async function saved(): Promise<HistoricalRecovery> {
  const f = await importFixture();
  return {
    version: 1,
    memberId: importMember,
    pending: { kind: "preview", key: importId(500), body: f.body, etag: null },
    lastBatchId: null,
  };
}
it("restores exact normalized preview input only under the same member and clears it through account cleanup", async () => {
  const record = await saved();
  record.pending!.key = "10eef7cb314a4dc29514d33d7d4541d0";
  writeHistoricalRecovery(record);
  expect(readHistoricalRecovery(importMember)).toEqual(record);
  expect(readHistoricalRecovery(importId(99)).pending).toBeNull();
  clearRecordedCommands(importMember);
  expect(readHistoricalRecovery(importMember)).toEqual(record);
  clearRecordedCommands();
  expect(readHistoricalRecovery(importMember).pending).toBeNull();
});
it("rejects corrupt recovery and noncanonical persisted input instead of replacing the original request", async () => {
  const record = await saved();
  for (const value of [
    "broken",
    { ...record, memberId: importId(2) },
    { ...record, pending: { ...record.pending, etag: '"unexpected"' } },
    {
      ...record,
      pending: {
        ...record.pending,
        body: {
          records: [
            {
              ...(record.pending!.kind === "preview"
                ? record.pending!.body.records[0]
                : {}),
              submitted_at: "2025-01-01T09:00:00.12+08:00",
            },
          ],
        },
      },
    },
  ]) {
    sessionStorage.setItem(
      historicalStorageKey(importMember),
      typeof value === "string" ? value : JSON.stringify(value),
    );
    expect(() => readHistoricalRecovery(importMember)).toThrow(/恢复记录/);
  }
});
it("keeps the original empty confirm body, source identity and strong ETag across remount", async () => {
  const f = await importFixture(),
    record: HistoricalRecovery = {
      version: 1,
      memberId: importMember,
      lastBatchId: f.batch.id,
      pending: {
        kind: "confirm",
        key: importId(501),
        body: {},
        etag: f.etag,
        batchId: f.batch.id,
        baseRevision: 1,
        manifestBlobId: f.batch.manifest_blob_id,
        manifestDigest: f.source.manifest_digest,
      },
    };
  writeHistoricalRecovery(record);
  expect(readHistoricalRecovery(importMember)).toEqual(record);
  sessionStorage.setItem(
    historicalStorageKey(importMember),
    JSON.stringify({
      ...record,
      pending: { ...record.pending, body: { records: [] } },
    }),
  );
  expect(() => readHistoricalRecovery(importMember)).toThrow();
});
