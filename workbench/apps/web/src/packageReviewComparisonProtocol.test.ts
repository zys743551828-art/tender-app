import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { packageReviewComparisonFixture } from "../qa-previews/frozen-inputs/packageReviewComparison";
import {
  packageReviewComparisonHeader,
  validateCompletePackageReviewComparison,
  validatePackageReviewComparisonPage,
} from "./packageReviewComparisonProtocol";
import { frozenManifestDigest } from "./packageFrozenInput";
import { changeId as id } from "../qa-previews/frozen-inputs/factChange";

beforeEach(async () => {
  const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
    "node:crypto",
  );
  vi.stubGlobal("crypto", webcrypto);
});
afterEach(() => vi.unstubAllGlobals());
it("separates definition, machine and human changes while preserving an exact complete comparison digest", async () => {
  const f = await packageReviewComparisonFixture();
  const page = await validatePackageReviewComparisonPage(f.page(), f.request);
  expect(page.counts).toMatchObject({
    unchanged: 2,
    machine_row_changed: 1,
    verdict_changed: 1,
  });
  await expect(
    validateCompletePackageReviewComparison(page, page.items),
  ).resolves.toBeUndefined();
  expect(page.risk_resolution_assessed).toBe(false);
});
it.each([
  "wrong-bid",
  "swapped-runs",
  "definition",
  "machine-change",
  "transition",
  "overstated-total",
  "qualifications",
  "duplicate-row",
  "wrong-human",
])("rejects a mismatched or overstated comparison: %s", async (kind) => {
  const f = await packageReviewComparisonFixture(),
    p = structuredClone(f.page());
  if (kind === "wrong-bid") p.right.scope.bid_id = id(999);
  if (kind === "swapped-runs") [p.left, p.right] = [p.right, p.left];
  if (kind === "definition") p.items[0].definition_change = "changed";
  if (kind === "machine-change") p.items[0].machine_row_changed = false;
  if (kind === "transition") p.items[0].verdict_transition!.changed = false;
  if (kind === "overstated-total") p.counts.unchanged++;
  if (kind === "qualifications")
    Object.assign(p, { risk_resolution_assessed: true });
  if (kind === "duplicate-row") p.items[1] = p.items[0];
  if (kind === "wrong-human")
    Object.assign(p.items[0], { left_human: { state: "resolved" } });
  await expect(
    validatePackageReviewComparisonPage(p, f.request),
  ).rejects.toThrow();
});
it("accepts a frozen not-applicable row without target parts and rejects a satisfied interpretation", async () => {
  const f = await packageReviewComparisonFixture(),
    p = structuredClone(f.page());
  const a = p.items[1].left!,
    b = p.items[1].right!;
  for (const row of [a, b])
    Object.assign(row, {
      applicability: "not_applicable",
      target_part_ids: [],
      verdict: "not_applicable",
      limitations: [],
    });
  p.items[1].verdict_transition = {
    from: "not_applicable",
    to: "not_applicable",
    changed: false,
  };
  p.comparison_digest = await frozenManifestDigest({
    ...packageReviewComparisonHeader(p),
    items: p.items,
  });
  await expect(
    validatePackageReviewComparisonPage(p, f.request),
  ).resolves.toEqual(p);
  a.verdict = "satisfied";
  await expect(
    validatePackageReviewComparisonPage(p, f.request),
  ).rejects.toThrow();
});
it("binds all pages to the same immutable runs and human snapshot and verifies the final full manifest", async () => {
  const f = await packageReviewComparisonFixture(23),
    a = await validatePackageReviewComparisonPage(f.page(), f.request),
    b = await validatePackageReviewComparisonPage(f.page(20), f.request, 20, a);
  await expect(
    validateCompletePackageReviewComparison(b, [...a.items, ...b.items]),
  ).resolves.toBeUndefined();
  const changed = structuredClone(b);
  changed.right.human_heads_digest = "0".repeat(64);
  await expect(
    validatePackageReviewComparisonPage(changed, f.request, 20, a),
  ).rejects.toThrow(/快照已变化/);
  const tampered = structuredClone(b);
  tampered.items[0].right!.statement = "合成被替换的原判断";
  await expect(
    validateCompletePackageReviewComparison(tampered, [
      ...a.items,
      ...tampered.items,
    ]),
  ).rejects.toThrow();
});
