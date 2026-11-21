import { expect, it } from "vitest";
import type { PackageRequirementInventoryView } from "./contracts";
import { technicalOutline } from "./technicalBidOutlinePlan";

const id = (i: number) =>
  "11111111-1111-4111-8111-" + String(i).padStart(12, "0");
type Binding =
  PackageRequirementInventoryView["manifest"]["requirements"][number];
function rule(
  n: number,
  statement: string,
  options?: Partial<Binding>,
): Binding {
  return {
    rule_id: id(n),
    rule_snapshot: {
      statement,
      provenance_status: "effective",
      evidence_ids: [id(n + 10)],
    },
    source_bound: true,
    decision_snapshot: { decision: "confirmed" },
    requirement: {
      requirement_id: id(n),
      categories: ["technical"],
      applicability: "applicable",
    },
    annotation: { mapped: true },
    ...options,
  } as Binding;
}
it("only suggests headings from supported and confirmed technical rows; unknown and unmapped are visible", () => {
  const inventory = {
    manifest: {
      requirements: [
        rule(1, "工期不超过150天，竣工验收满足质量要求"),
        rule(2, "按指定要求", {
          rule_snapshot: {
            statement: "应使用规定方法",
            provenance_status: "effective",
            evidence_ids: [id(15)],
          },
        }),
        rule(3, "安全措施", { source_bound: false }),
        rule(4, "工程概况", { decision_snapshot: { decision: "rejected" } }),
        rule(5, "质量管理", {
          requirement: { ...rule(5, "").requirement, categories: ["business"] },
        }),
        rule(6, "技术方案", {
          rule_snapshot: {
            statement: "技术方案",
            provenance_status: "superseded",
            evidence_ids: [id(16)],
          },
        }),
      ],
    },
  } as PackageRequirementInventoryView;
  const result = technicalOutline(inventory);
  expect(result.chapters.map((c) => c.key)).toEqual(["schedule", "quality"]);
  expect(result.pending).toBe(3);
  expect(
    result.rows.map((r) => [r.ruleId, r.evidenceIds, r.suggested]),
  ).toEqual([
    [id(1), [id(11)], ["schedule", "quality"]],
    [id(2), [id(15)], []],
  ]);
});
