import type {
  PackageReviewFrozenInputPage,
  PackageReviewFrozenInputView,
} from "./contracts";
import type { FreezeScope } from "./packageFrozenInput";
import { validFrozenInputId } from "./packageFrozenInput";

export type FrozenInputSummary = PackageReviewFrozenInputPage["items"][number];
const sha = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);

// Retain the server's microseconds when checking the descending (time, UUID) boundary.
function time(value: string): bigint {
  const fraction = /\.(\d+)(?:Z|[+-]\d\d:\d\d)$/.exec(value)?.[1] ?? "";
  if (
    typeof value !== "string" ||
    !Number.isFinite(Date.parse(value)) ||
    fraction.length > 6
  )
    throw new Error("历史目录的冻结时间无效，未采用该页。");
  return (
    BigInt(Date.parse(value)) * 1000n + BigInt(fraction.padEnd(6, "0").slice(3))
  );
}
function follows(row: FrozenInputSummary, previous: FrozenInputSummary) {
  const a = time(row.frozen_at),
    b = time(previous.frozen_at);
  return a < b || (a === b && row.id < previous.id);
}

export function matchesFrozenInputSummary(
  value: PackageReviewFrozenInputView,
  item: FrozenInputSummary,
): boolean {
  const m = value.manifest;
  return (
    value.digest === item.digest &&
    m.id === item.id &&
    m.actor_id === item.actor_id &&
    m.input_digest === item.input_digest &&
    m.context_digest === item.context_digest &&
    time(m.frozen_at) === time(item.frozen_at)
  );
}

export function validateFrozenInputPage(
  value: PackageReviewFrozenInputPage,
  scope: FreezeScope,
  previous: FrozenInputSummary[] = [],
  usedCursors: string[] = [],
): void {
  if (
    !value ||
    value.bid_id !== scope.bidId ||
    value.package_id !== scope.packageId ||
    value.revision_id !== scope.revisionId ||
    value.inventory_id !== scope.inventoryId ||
    !Array.isArray(value.items) ||
    value.items.length > 20 ||
    typeof value.has_more !== "boolean" ||
    (value.has_more
      ? !value.items.length ||
        typeof value.next_cursor !== "string" ||
        !value.next_cursor.length ||
        value.next_cursor.length > 4096 ||
        usedCursors.includes(value.next_cursor)
      : value.next_cursor !== null)
  )
    throw new Error("历史目录作用域或分页响应不符，未采用该页。");
  const ids = new Set(previous.map((row) => row.id));
  let last = previous.at(-1);
  for (const row of value.items) {
    if (
      !row ||
      !validFrozenInputId(row.id) ||
      !validFrozenInputId(row.actor_id) ||
      ![row.digest, row.input_digest, row.context_digest].every(sha) ||
      ids.has(row.id) ||
      (last && !follows(row, last))
    )
      throw new Error("历史目录记录重复、顺序或摘要不符，未采用该页。");
    time(row.frozen_at);
    ids.add(row.id);
    last = row;
  }
}
