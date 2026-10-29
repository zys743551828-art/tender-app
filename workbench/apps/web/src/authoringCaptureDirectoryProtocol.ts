import type {
  BidPackageHeadPage,
  BidPackageRevisionSummaryPage,
  BidPackageStoredView,
  PackageRequirementInventoryPage,
  PackageRequirementInventoryView,
} from "./contracts";
import {
  exactKeys,
  executionId as uuid,
  executionSha as sha,
  recordObject as object,
} from "./executionInputValidation";
import {
  authoringInteger as integer,
  authoringTimestamp,
} from "./packageAuthoringInputProtocol";
import {
  validatePackageNavigationInventory,
  validatePackageNavigationView,
  validPackageDirectory,
} from "./packageNavigation";
import {
  captureFailure,
  type CapturePackageReference,
} from "./authoringInputCatalogProtocol";

function page(
  v: unknown,
  keys = ["items", "has_more", "next_cursor"],
): asserts v is {
  items: unknown[];
  has_more: boolean;
  next_cursor: string | null;
} & Record<string, unknown> {
  if (
    !object(v) ||
    !exactKeys(v, keys) ||
    !Array.isArray(v.items) ||
    v.items.length > 100 ||
    typeof v.has_more !== "boolean" ||
    (v.has_more
      ? !v.items.length ||
        typeof v.next_cursor !== "string" ||
        !v.next_cursor ||
        v.next_cursor.length > 4096
      : v.next_cursor !== null)
  )
    captureFailure("包或清单目录分页不能核验。");
}
export function capturePackageDirectory(
  v: unknown,
  bid: string,
  kind: "bid" | "authority",
): BidPackageHeadPage {
  page(v);
  if (
    !validPackageDirectory(v, bid, kind) ||
    v.items.some(
      (item) =>
        !exactKeys(item, [
          "id",
          "bid_id",
          "kind",
          "revision_id",
          "revision",
          "digest",
        ]),
    )
  )
    captureFailure();
  return v;
}
export function captureRevisionDirectory(
  v: unknown,
  packageId: string,
): BidPackageRevisionSummaryPage {
  page(v);
  let previous = Infinity;
  for (const row of v.items) {
    if (
      !object(row) ||
      !exactKeys(row, [
        "id",
        "package_id",
        "revision",
        "digest",
        "created_at",
      ]) ||
      !uuid(row.id) ||
      row.package_id !== packageId ||
      !integer(row.revision) ||
      row.revision >= previous ||
      !sha(row.digest) ||
      !authoringTimestamp(row.created_at)
    )
      captureFailure();
    previous = row.revision;
  }
  return v as unknown as BidPackageRevisionSummaryPage;
}
export async function capturePackageView(
  v: unknown,
  bid: string,
  role: "target" | "authority",
  selected: CapturePackageReference,
) {
  if (
    !object(v) ||
    !exactKeys(v, [
      "manifest",
      "digest",
      "identity",
      "storage_eligible",
      "review_ready",
    ])
  )
    captureFailure();
  const value = await validatePackageNavigationView(
    v as BidPackageStoredView,
    bid,
    {
      packageId: selected.package_id,
      revisionId: selected.revision_id,
      inventoryId: null,
    },
  );
  if (
    value.digest !== selected.manifest_digest ||
    value.manifest.kind !== (role === "target" ? "bid" : "authority")
  )
    captureFailure();
  return value;
}
export function captureInventoryDirectory(
  v: unknown,
): PackageRequirementInventoryPage {
  page(v, ["items", "has_more", "next_cursor", "current_inventory_id"]);
  if (v.current_inventory_id !== null && !uuid(v.current_inventory_id))
    captureFailure();
  for (const row of v.items)
    if (
      !object(row) ||
      !exactKeys(row, ["id", "digest", "created_at"]) ||
      !uuid(row.id) ||
      !sha(row.digest) ||
      !authoringTimestamp(row.created_at)
    )
      captureFailure();
  return v as unknown as PackageRequirementInventoryPage;
}
export async function captureInventoryView(
  v: unknown,
  target: BidPackageStoredView,
  authority: BidPackageStoredView,
  selected: { id: string; digest: string },
) {
  if (!object(v) || !exactKeys(v, ["manifest", "digest"])) captureFailure();
  const value = await validatePackageNavigationInventory(
    v as PackageRequirementInventoryView,
    target,
    selected.id,
  );
  const manifest = value.manifest;
  if (
    value.digest !== selected.digest ||
    manifest.authority_revision_id !== authority.manifest.revision_id ||
    manifest.authority_digest !== authority.digest ||
    !uuid(manifest.rule_set_id)
  )
    captureFailure("清单没有绑定明确选择的目标包和依据包，未替换其他清单。");
  return value;
}
