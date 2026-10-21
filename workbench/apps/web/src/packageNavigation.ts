import type {
  BidPackageHeadPage,
  BidPackageStoredView,
  PackageRequirementInventoryView,
} from "./contracts";
import { jsonDigest } from "./editorSchema";
import {
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";

export type PackageNavigationTarget = {
  packageId: string;
  revisionId: string;
  inventoryId: string | null;
};
export type PackageLocation =
  | { ok: true; target: PackageNavigationTarget | null }
  | { ok: false; message: string };
const invalid = (): PackageLocation => ({
  ok: false,
  message:
    "整包链接不完整或包含重复、无效的身份。请核对原链接；未改用当前包、最新修订或其他清单。",
});
export function parsePackageLocation(route: string): PackageLocation {
  const [pathname, ...search] = route.split("?");
  if (!/^\/bids\/[^/?#]+\/packages$/.test(pathname) || search.length > 1)
    return invalid();
  const query = new URLSearchParams(search[0] ?? "");
  const keys = ["package", "revision", "inventory"];
  if (
    [...query.keys()].some(
      (key) => !keys.includes(key) || query.getAll(key).length !== 1,
    )
  )
    return invalid();
  if (!query.size) return { ok: true, target: null };
  const packageId = query.get("package"),
    revisionId = query.get("revision"),
    inventoryId = query.get("inventory");
  if (
    !executionId(packageId) ||
    !executionId(revisionId) ||
    (inventoryId !== null && !executionId(inventoryId))
  )
    return invalid();
  return { ok: true, target: { packageId, revisionId, inventoryId } };
}
export function packageLocation(
  bidId: string,
  target: PackageNavigationTarget | null,
) {
  if (!target) return `/bids/${encodeURIComponent(bidId)}/packages`;
  const query = new URLSearchParams({
    package: target.packageId,
    revision: target.revisionId,
  });
  if (target.inventoryId !== null) query.set("inventory", target.inventoryId);
  const path = `/bids/${encodeURIComponent(bidId)}/packages?${query}`;
  if (!parsePackageLocation(path).ok)
    throw new Error("不能创建身份无效的整包链接。");
  return path;
}
export function samePackageTarget(
  a: PackageNavigationTarget | null,
  b: PackageNavigationTarget | null,
) {
  return a === null || b === null
    ? a === b
    : a.packageId === b.packageId &&
        a.revisionId === b.revisionId &&
        a.inventoryId === b.inventoryId;
}
export function validPackageDirectory(
  value: unknown,
  bidId: string,
  kind: "bid" | "authority",
): value is BidPackageHeadPage {
  if (
    !recordObject(value) ||
    !Array.isArray(value.items) ||
    typeof value.has_more !== "boolean" ||
    (value.has_more
      ? typeof value.next_cursor !== "string" || !value.next_cursor
      : value.next_cursor !== null)
  )
    return false;
  return (
    value.items.every(
      (item) =>
        recordObject(item) &&
        executionId(item.id) &&
        item.bid_id === bidId &&
        item.kind === kind &&
        executionId(item.revision_id) &&
        executionSha(item.digest) &&
        Number.isSafeInteger(item.revision) &&
        Number(item.revision) > 0,
    ) && new Set(value.items.map((item) => item.id)).size === value.items.length
  );
}
export async function validatePackageNavigationView(
  value: BidPackageStoredView,
  bidId: string,
  target: PackageNavigationTarget,
) {
  const m = value?.manifest;
  if (
    !m ||
    m.scope?.bid_id !== bidId ||
    m.package_id !== target.packageId ||
    m.revision_id !== target.revisionId ||
    !["bid", "authority"].includes(m.kind) ||
    (target.inventoryId !== null && m.kind !== "bid") ||
    !executionSha(value.digest) ||
    !Array.isArray(m.members) ||
    !value.identity ||
    m.members.some((member) => member.scope?.bid_id !== bidId) ||
    (await jsonDigest(m)) !== value.digest
  )
    throw new Error(
      "链接所指包修订的身份或摘要不一致，未展示或替换为其他版本。",
    );
  return value;
}
export async function validatePackageNavigationInventory(
  value: PackageRequirementInventoryView,
  packageView: BidPackageStoredView,
  inventoryId: string,
) {
  const m = value?.manifest,
    p = packageView.manifest;
  if (
    !m ||
    m.id !== inventoryId ||
    m.bid_id !== p.scope.bid_id ||
    m.package_id !== p.package_id ||
    m.target_revision_id !== p.revision_id ||
    m.package_digest !== packageView.digest ||
    !executionSha(value.digest) ||
    (await jsonDigest(m)) !== value.digest
  )
    throw new Error("链接所指清单的范围或摘要不一致，未改用当前清单。");
  return value;
}

export type PackageNavigationState = {
  busy: boolean;
  dirty: boolean;
  pending: boolean;
};
export const emptyPackageNavigationState: PackageNavigationState = {
  busy: false,
  dirty: false,
  pending: false,
};
