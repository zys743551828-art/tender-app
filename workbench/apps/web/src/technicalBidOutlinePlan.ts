import { api } from "./api";
import type { BidPackage_scope, RuleSetView } from "./contracts";
import {
  captureInventoryDirectory,
  captureInventoryView,
  capturePackageView,
} from "./authoringCaptureDirectoryProtocol";
import type { CapturePackageReference } from "./authoringInputCatalogProtocol";
import type {
  AuthoringTreeChangeRequest,
  AuthoringTreeView,
  PackageRequirementInventoryView,
} from "./contracts";
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

export function appendOutline(
  tree: AuthoringTreeView,
  chapters: ReadonlyArray<{ key: string; title: string }>,
  basisDigest: string,
): AuthoringTreeChangeRequest {
  const live = tree.nodes.filter((node) => !node.deleted);
  const names = new Set(
    live.map((node) => node.title.normalize("NFKC").trim()),
  );
  const changes: AuthoringTreeChangeRequest["changes"] = [];
  const rootCount = live.filter((node) => node.parent_id === null).length;
  for (const { key, title } of chapters) {
    const normalized = title.normalize("NFKC").trim();
    if (names.has(normalized)) continue;
    const ordinal = rootCount + changes.length;
    if (ordinal >= 500 || live.length + changes.length >= 500)
      throw new Error("章节数量达到目录限制，请先人工调整目录。");
    names.add(normalized);
    changes.push({
      op: "add",
      client_key: "technical-bid-" + basisDigest + "-" + key,
      title,
      node_type: "chapter",
      parent: null,
      ordinal,
    });
  }
  if (!changes.length)
    throw new Error("没有需要追加的新章；现有章节不会被覆盖。");
  return { base_draft_revision: tree.draft_revision, changes };
}

type InventoryRef = { id: string; digest: string };
export type OutlineBasis = {
  target: CapturePackageReference;
  authority: CapturePackageReference;
  inventory: InventoryRef;
};
const packagePath = (bid: string, p: CapturePackageReference) =>
  `/bids/${bid}/packages/${p.package_id}/revisions/${p.revision_id}`;

export async function verifyCurrentOutline(bid: string, basis: OutlineBasis) {
  const targetPath = packagePath(bid, basis.target);
  const sourcePath = packagePath(bid, basis.authority);
  const directory = targetPath + "/requirement-inventories";
  const [
    { data: page },
    { data: inventory },
    { data: rules },
    target,
    authority,
  ] = await Promise.all([
    api<unknown>(directory + "?limit=20"),
    api<unknown>(directory + "/" + basis.inventory.id),
    api<RuleSetView>(`/bids/${bid}/rules`),
    api<unknown>(targetPath.slice(0, targetPath.indexOf("/revisions/"))).then(
      (r) => capturePackageView(r.data, bid, "target", basis.target),
    ),
    api<unknown>(sourcePath.slice(0, sourcePath.indexOf("/revisions/"))).then(
      (r) => capturePackageView(r.data, bid, "authority", basis.authority),
    ),
  ]);
  const checked = await captureInventoryView(
    inventory,
    target,
    authority,
    basis.inventory,
  );
  const fresh = new Map(rules?.rules?.map((rule) => [rule.id, rule]));
  const rows = technicalOutline(checked).rows;
  if (
    !sameLot(target.manifest.scope, authority.manifest.scope) ||
    captureInventoryDirectory(page).current_inventory_id !==
      basis.inventory.id ||
    rules?.bid_id !== bid ||
    rules.id !== checked.manifest.rule_set_id ||
    rows.some(({ ruleId, statement, evidenceIds }) => {
      const rule = fresh.get(ruleId);
      return (
        rule?.confirmation !== "confirmed" ||
        rule.provenance_status !== "effective" ||
        rule.statement !== statement ||
        evidenceIds.some((evidence) => !rule.evidence_ids.includes(evidence))
      );
    })
  )
    throw new Error(
      "当前要求清单、来源或确认决定已变更，未继续大纲操作。请刷新并重新选择。",
    );
  return checked;
}
export function sameLot(a: BidPackage_scope, b: BidPackage_scope) {
  return (
    a.bid_id === b.bid_id &&
    a.engineering_project_id === b.engineering_project_id &&
    a.lot_id === b.lot_id &&
    a.round_id === b.round_id
  );
}
