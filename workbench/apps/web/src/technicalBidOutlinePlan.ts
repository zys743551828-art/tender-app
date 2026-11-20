import type { BidPackage_scope, TechnicalOutlineRequest } from "./contracts";
import type { CapturePackageReference } from "./authoringInputCatalogProtocol";
import type { PackageRequirementInventoryView } from "./contracts";
import { executionId } from "./executionInputValidation";

const headings = [
  ["overview", "工程概况与施工部署", /概况|范围|部署|重难点/],
  ["method", "主要施工方法与技术措施", /工法|工艺|技术措施|施工方法|专项方案/],
  ["schedule", "施工进度与资源配置", /工期|进度|资源|机械|设备|劳动力/],
  ["quality", "质量管理与验收", /质量|验收|检验|检测/],
  ["safety", "安全文明施工与环境保护", /安全|文明施工|环保|环境|应急/],
] as const;

type Heading = (typeof headings)[number];
type Row = {
  ruleId: string;
  statement: string;
  evidenceIds: string[];
  suggested: Heading[0][];
};

export function technicalOutline(inventory: PackageRequirementInventoryView) {
  const rows: Row[] = [];
  let pending = 0;
  for (const binding of inventory.manifest.requirements) {
    const { requirement } = binding;
    if (requirement.applicability === "not_applicable") continue;
    const categories = requirement.categories;
    if (
      !binding.annotation.mapped ||
      !categories.some((x) => x !== "未分类" && x !== "unclassified")
    ) {
      pending++;
      continue;
    }
    if (!categories.some((x) => x === "technical" || x === "技术")) continue;
    const statement = binding.rule_snapshot.statement;
    const evidenceIds = binding.rule_snapshot.evidence_ids;
    if (
      !binding.source_bound ||
      binding.decision_snapshot?.decision !== "confirmed" ||
      binding.rule_snapshot.provenance_status !== "effective" ||
      requirement.applicability !== "applicable" ||
      typeof statement !== "string" ||
      !statement.trim() ||
      !executionId(binding.rule_id) ||
      binding.rule_id !== requirement.requirement_id ||
      !Array.isArray(evidenceIds) ||
      evidenceIds.length === 0 ||
      !evidenceIds.every(executionId)
    ) {
      pending++;
      continue;
    }
    rows.push({
      ruleId: binding.rule_id,
      statement,
      evidenceIds: [...new Set<string>(evidenceIds)],
      suggested: headings
        .filter(([, , pattern]) => pattern.test(statement))
        .map(([key]) => key),
    });
  }
  return {
    rows,
    pending,
    chapters: headings
      .filter(([key]) => rows.some((row) => row.suggested.includes(key)))
      .map(([key, title]) => ({ key, title })),
  };
}

type InventoryRef = { id: string; digest: string };
export type OutlineBasis = {
  target: CapturePackageReference;
  authority: CapturePackageReference;
  inventory: InventoryRef;
};
export function sameLot(a: BidPackage_scope, b: BidPackage_scope) {
  return (
    a.bid_id === b.bid_id &&
    a.engineering_project_id === b.engineering_project_id &&
    a.lot_id === b.lot_id &&
    a.round_id === b.round_id
  );
}

/** A capture ref and an outline API ref use different digest field names. */
export function technicalOutlineRequest(
  revision: number,
  basis: OutlineBasis,
  keys: TechnicalOutlineRequest["chapter_keys"],
): TechnicalOutlineRequest {
  const outlinePackage = ({
    package_id,
    revision_id,
    manifest_digest,
  }: CapturePackageReference) => ({
    package_id,
    revision_id,
    digest: manifest_digest,
  });
  return {
    base_draft_revision: revision,
    basis: {
      target: outlinePackage(basis.target),
      authority: outlinePackage(basis.authority),
      inventory: { id: basis.inventory.id, digest: basis.inventory.digest },
    },
    chapter_keys: keys,
  };
}
