import type {
  PackageExecutionInputView,
  PackagePreparedFactPage,
} from "./contracts";
import type { FreezeScope } from "./packageFrozenInput";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
const previewText = (v: unknown) =>
  typeof v === "string" && v.length <= 480 && Array.from(v).length <= 240;
export function matchesPreparedFacts(
  v: PackagePreparedFactPage,
  scope: FreezeScope,
  frozenId: string,
  prepared: PackageExecutionInputView,
  previousCursor: string | null,
) {
  if (
    !recordObject(v) ||
    !exactKeys(v, [
      "bid_id",
      "package_id",
      "revision_id",
      "inventory_id",
      "frozen_input_id",
      "execution_input_id",
      "execution_input_digest",
      "facts_digest",
      "fact_set_id",
      "fact_count",
      "items",
      "has_more",
      "next_cursor",
    ])
  )
    return false;
  const c = prepared.manifest.execution_context;
  if (
    v.bid_id !== scope.bidId ||
    v.package_id !== scope.packageId ||
    v.revision_id !== scope.revisionId ||
    v.inventory_id !== scope.inventoryId ||
    v.frozen_input_id !== frozenId ||
    v.execution_input_id !== prepared.manifest.id ||
    v.execution_input_digest !== prepared.digest ||
    v.facts_digest !== c.facts_digest ||
    v.fact_set_id !== c.fact_set_id ||
    v.fact_count !== c.fact_count ||
    !Number.isSafeInteger(v.fact_count) ||
    v.fact_count < 0 ||
    (v.fact_count > 0 && !executionId(v.fact_set_id)) ||
    !Array.isArray(v.items) ||
    v.items.length > 20 ||
    v.items.length > v.fact_count ||
    typeof v.has_more !== "boolean"
  )
    return false;
  if (
    v.has_more
      ? typeof v.next_cursor !== "string" ||
        !v.next_cursor ||
        v.next_cursor.length > 4096 ||
        v.next_cursor === previousCursor ||
        v.items.length === 0
      : v.next_cursor !== null
  )
    return false;
  if (previousCursor === null && v.fact_count > 0 && !v.items.length)
    return false;
  return v.items.every(
    (item, index) =>
      recordObject(item) &&
      exactKeys(item, [
        "fact_id",
        "fact_item_digest",
        "name",
        "subject",
        "scope",
        "value_preview",
        "unit",
        "preview_truncated",
      ]) &&
      executionId(item.fact_id) &&
      executionSha(item.fact_item_digest) &&
      [item.name, item.subject, item.scope, item.value_preview].every(
        previewText,
      ) &&
      (item.unit === null || previewText(item.unit)) &&
      typeof item.preview_truncated === "boolean" &&
      (index === 0 || v.items[index - 1].fact_id < item.fact_id),
  );
}
