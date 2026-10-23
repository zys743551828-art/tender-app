import { expect, it } from "vitest";
import { jsonDigest } from "./editorSchema";
import {
  packageLocation,
  parsePackageLocation,
  validPackageDirectory,
  validatePackageNavigationInventory,
  validatePackageNavigationView,
} from "./packageNavigation";
import {
  submissionFixture,
  submissionId as id,
  submissionScope,
} from "./packageSubmissionFixtures.test-support";

const target = { packageId: id(3), revisionId: id(4), inventoryId: id(5) };
it("rejects extra path segments instead of treating them as the same package workspace", () => {
  expect(parsePackageLocation(`/bids/${id(1)}/packages/other`).ok).toBe(false);
});
it("encodes and restores the explicit immutable chain without current or latest defaults", () => {
  expect(parsePackageLocation(packageLocation(id(1), target))).toEqual({
    ok: true,
    target,
  });
  expect(parsePackageLocation(packageLocation(id(1), null))).toEqual({
    ok: true,
    target: null,
  });
  expect(
    parsePackageLocation(
      packageLocation(id(1), { ...target, inventoryId: null }),
    ),
  ).toEqual({ ok: true, target: { ...target, inventoryId: null } });
});
it.each([
  `package=${id(3)}`,
  `revision=${id(4)}`,
  `inventory=${id(5)}`,
  `package=${id(3)}&revision=${id(4)}&revision=${id(6)}`,
  `package=${id(3)}&revision=${id(4)}&inventory=`,
  `package=${id(3)}&revision=latest`,
  `package=..%2Fother&revision=${id(4)}`,
  `package=${id(3)}&revision=${id(4)}&review=${id(6)}`,
  `package=${id(3)}&revision=${id(4)}?ignored=true`,
])("rejects ambiguous or invalid URL query %s", (query) => {
  expect(parsePackageLocation(`/bids/${id(1)}/packages?${query}`).ok).toBe(
    false,
  );
});
it("checks exact package scope and manifest digest even when a supplied foreign digest is internally valid", async () => {
  const f = await submissionFixture(true);
  const t = {
    packageId: f.target.manifest.package_id,
    revisionId: f.target.manifest.revision_id,
    inventoryId: null,
  };
  expect(
    await validatePackageNavigationView(f.target, submissionScope.bidId, t),
  ).toBe(f.target);
  const foreign = structuredClone(f.target);
  foreign.manifest.scope.bid_id = id(700);
  foreign.digest = await jsonDigest(foreign.manifest);
  await expect(
    validatePackageNavigationView(foreign, submissionScope.bidId, t),
  ).rejects.toThrow(/身份或摘要不一致/);
  await expect(
    validatePackageNavigationView(
      { ...f.target, digest: "f".repeat(64) },
      submissionScope.bidId,
      t,
    ),
  ).rejects.toThrow();
});
it("does not attach an inventory from another revision or a changed package digest", async () => {
  const f = await submissionFixture(true),
    inventory = f.selection.inventory!;
  expect(
    await validatePackageNavigationInventory(
      inventory,
      f.target,
      inventory.manifest.id,
    ),
  ).toBe(inventory);
  const changed = structuredClone(inventory);
  changed.manifest.target_revision_id = id(701);
  changed.digest = await jsonDigest(changed.manifest);
  await expect(
    validatePackageNavigationInventory(
      changed,
      f.target,
      inventory.manifest.id,
    ),
  ).rejects.toThrow(/范围或摘要/);
  await expect(
    validatePackageNavigationInventory(
      { ...inventory, digest: "f".repeat(64) },
      f.target,
      inventory.manifest.id,
    ),
  ).rejects.toThrow();
});
it("requires a scoped directory and coherent pagination before treating a response as an empty catalog", () => {
  const page = {
    items: [
      {
        id: id(3),
        bid_id: id(1),
        kind: "bid",
        revision_id: id(4),
        revision: 1,
        digest: "a".repeat(64),
      },
    ],
    has_more: false,
    next_cursor: null,
  };
  expect(validPackageDirectory(page, id(1), "bid")).toBe(true);
  expect(validPackageDirectory(page, id(2), "bid")).toBe(false);
  expect(
    validPackageDirectory(
      { items: [], has_more: true, next_cursor: null },
      id(1),
      "bid",
    ),
  ).toBe(false);
  expect(
    validPackageDirectory(
      { items: [], has_more: true, next_cursor: "next" },
      id(1),
      "bid",
    ),
  ).toBe(true);
  expect(validPackageDirectory(undefined, id(1), "bid")).toBe(false);
});
