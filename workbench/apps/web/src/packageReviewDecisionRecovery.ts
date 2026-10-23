import { dependencyPlanScope } from "./dependencyPlanProtocol";
import { exactKeys, recordObject } from "./executionInputValidation";
import { recordedCommandStorageKey } from "./recordedCommandStorage";
import type {
  PackageReviewDecisionProps,
  PendingPackageReviewDecision,
} from "./packageReviewDecisionProtocol";
import {
  packageReviewDecisionQuotes,
  validPendingPackageReviewDecision,
} from "./packageReviewDecisionProtocol";

export type PackageReviewDecisionDraft = {
  reason: string;
  quoteIndexes: number[];
};
export const packageReviewDecisionScope = (p: PackageReviewDecisionProps) => ({
  ...dependencyPlanScope(p),
  runId: p.run.id,
  inputDigest: p.run.input_digest,
  resultDigest: p.run.result!.digest,
});
export type PackageReviewDecisionRecord = {
  version: 1;
  scope: ReturnType<typeof packageReviewDecisionScope>;
  pending: PendingPackageReviewDecision | null;
  drafts: Record<string, PackageReviewDecisionDraft>;
};
export const packageReviewDecisionStorageKey = (
  s: ReturnType<typeof packageReviewDecisionScope>,
) =>
  recordedCommandStorageKey(
    "package-review-decision",
    s.memberId,
    s.bidId,
    s.packageId,
    s.revisionId,
    s.inventoryId,
    s.frozenId,
    s.frozenDigest,
    s.preparedId,
    s.preparedDigest,
    s.runId,
    s.inputDigest,
    s.resultDigest,
  );
export function loadPackageReviewDecisionRecord(
  p: PackageReviewDecisionProps,
): PackageReviewDecisionRecord {
  const scope = packageReviewDecisionScope(p),
    raw = sessionStorage.getItem(packageReviewDecisionStorageKey(scope));
  if (raw === null) return { version: 1, scope, pending: null, drafts: {} };
  const fail = () => {
    throw new Error(
      "人工处置恢复记录损坏或原结果不符，已阻止新保存；请保留记录核对，仍可读取服务器状态与历史。",
    );
  };
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return fail();
  }
  if (!recordObject(value)) return fail();
  const savedScope = value.scope;
  if (
    !exactKeys(value, ["version", "scope", "pending", "drafts"]) ||
    value.version !== 1 ||
    !recordObject(savedScope) ||
    !exactKeys(savedScope, Object.keys(scope)) ||
    Object.entries(scope).some(([key, item]) => savedScope[key] !== item) ||
    (value.pending !== null &&
      !validPendingPackageReviewDecision(value.pending, p.run)) ||
    !recordObject(value.drafts)
  )
    return fail();
  const rows = new Map(
    p.run.result!.manifest.matrix.map((row) => [row.requirement_id, row]),
  );
  for (const [id, draft] of Object.entries(value.drafts)) {
    const row = rows.get(id);
    if (
      !row ||
      !recordObject(draft) ||
      !exactKeys(draft, ["reason", "quoteIndexes"]) ||
      typeof draft.reason !== "string" ||
      Array.from(draft.reason).length > 2000 ||
      !Array.isArray(draft.quoteIndexes) ||
      draft.quoteIndexes.length > 40 ||
      new Set(draft.quoteIndexes).size !== draft.quoteIndexes.length
    )
      return fail();
    const quotes = packageReviewDecisionQuotes(row);
    if (
      !draft.quoteIndexes.every(
        (index) =>
          Number.isSafeInteger(index) && index >= 0 && index < quotes.length,
      )
    )
      return fail();
  }
  return value as unknown as PackageReviewDecisionRecord;
}
export function storePackageReviewDecisionRecord(
  record: PackageReviewDecisionRecord,
) {
  try {
    sessionStorage.setItem(
      packageReviewDecisionStorageKey(record.scope),
      JSON.stringify(record),
    );
  } catch {
    throw new Error(
      "浏览器未能更新人工处置恢复记录。原请求可能已经受理，请保留原幂等键并核对服务器记录。",
    );
  }
}
