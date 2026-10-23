import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
import { recordedCommandStorageKey } from "./recordedCommandStorage";
import {
  historicalImportEtag,
  historicalSame,
  normalizeHistoricalRequest,
  type HistoricalPending,
} from "./historicalImportProtocol";

export type HistoricalRecovery = {
  version: 1;
  memberId: string;
  pending: HistoricalPending | null;
  lastBatchId: string | null;
};
export const historicalStorageKey = (memberId: string) =>
  recordedCommandStorageKey("historical-import", memberId, "batches");
export function readHistoricalRecovery(memberId: string): HistoricalRecovery {
  const raw = sessionStorage.getItem(historicalStorageKey(memberId));
  if (!raw) return { version: 1, memberId, pending: null, lastBatchId: null };
  try {
    const value: unknown = JSON.parse(raw);
    if (
      !recordObject(value) ||
      !exactKeys(value, ["version", "memberId", "pending", "lastBatchId"]) ||
      value.version !== 1 ||
      value.memberId !== memberId ||
      !(value.lastBatchId === null || executionId(value.lastBatchId))
    )
      throw new Error();
    const p = value.pending;
    if (p !== null) {
      if (
        !recordObject(p) ||
        typeof p.key !== "string" ||
        !/^[\x20-\x7e]{1,128}$/.test(p.key)
      )
        throw new Error();
      if (p.kind === "preview") {
        if (
          !exactKeys(p, ["kind", "key", "body", "etag"]) ||
          p.etag !== null ||
          !historicalSame(normalizeHistoricalRequest(p.body), p.body)
        )
          throw new Error();
      } else if (p.kind === "confirm") {
        if (
          !exactKeys(p, [
            "kind",
            "key",
            "body",
            "etag",
            "batchId",
            "baseRevision",
            "manifestBlobId",
            "manifestDigest",
          ]) ||
          !executionId(p.batchId) ||
          typeof p.baseRevision !== "number" ||
          !Number.isSafeInteger(p.baseRevision) ||
          p.baseRevision < 1 ||
          !executionId(p.manifestBlobId) ||
          !executionSha(p.manifestDigest) ||
          !recordObject(p.body) ||
          !exactKeys(p.body, []) ||
          p.etag !== historicalImportEtag(p.batchId, p.baseRevision)
        )
          throw new Error();
      } else throw new Error();
    }
    return value as HistoricalRecovery;
  } catch {
    throw new Error(
      "本地导入恢复记录损坏或不属于当前成员，请保留记录，不能另发相同导入。",
    );
  }
}
export function writeHistoricalRecovery(value: HistoricalRecovery) {
  try {
    sessionStorage.setItem(
      historicalStorageKey(value.memberId),
      JSON.stringify(value),
    );
  } catch {
    throw new Error(
      "浏览器无法保存导入恢复记录。请释放此站点存储空间；本次不会另发未经记录的请求。",
    );
  }
}
