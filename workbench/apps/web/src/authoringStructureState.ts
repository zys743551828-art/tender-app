import type {
  AuthoringTreeView,
  AuthoringJsonValue,
  AuthoringPlanSave,
  AuthoringSourceReference,
} from "./contracts";
export type TreeNode = AuthoringTreeView["nodes"][number];
export function treeOrder<
  T extends Pick<TreeNode, "section_id" | "parent_id" | "ordinal" | "deleted">,
>(nodes: T[], deleted = false) {
  const available = nodes.filter((n) => n.deleted === deleted);
  const result: { node: T; depth: number }[] = [];
  const seen = new Set<string>();
  function visit(parent: string | null, depth: number) {
    for (const node of available
      .filter((n) => n.parent_id === parent)
      .sort(
        (a, b) =>
          a.ordinal - b.ordinal || a.section_id.localeCompare(b.section_id),
      )) {
      if (seen.has(node.section_id)) continue;
      seen.add(node.section_id);
      result.push({ node, depth });
      visit(node.section_id, depth + 1);
    }
  }
  visit(null, 0);
  for (const node of available)
    if (!seen.has(node.section_id)) {
      result.push({ node, depth: 0 });
      seen.add(node.section_id);
    }
  return result;
}
export function record(
  value: AuthoringJsonValue | undefined,
): Record<string, AuthoringJsonValue> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value
    : {};
}
export function strings(value: AuthoringJsonValue | undefined) {
  return Array.isArray(value)
    ? value.filter((v): v is string => typeof v === "string")
    : [];
}
export function sourceRefs(
  value: AuthoringJsonValue | undefined,
): AuthoringSourceReference[] {
  if (!Array.isArray(value)) return [];
  return value.filter((v) => {
    const r = record(v);
    return (
      typeof r.source_id === "string" &&
      typeof r.source_revision === "number" &&
      typeof r.evidence_id === "string" &&
      typeof r.document_version_id === "string"
    );
  }) as AuthoringSourceReference[];
}
export function initialPlan(
  node: TreeNode,
  draftRevision: number,
): AuthoringPlanSave {
  const p = node.plan?.payload ?? {};
  return {
    base_draft_revision: draftRevision,
    base_plan_revision: node.plan?.revision ?? 0,
    state: node.plan?.state ?? "not_started",
    goal: typeof p.goal === "string" ? p.goal : "",
    key_points: strings(p.key_points),
    rule_ids: strings(p.rule_ids),
    source_refs: sourceRefs(p.source_refs),
    pending_facts: strings(p.pending_facts),
    planned_pages: node.plan?.planned_pages ?? null,
    budget_basis:
      p.budget_basis === "requirement" || p.budget_basis === "template"
        ? p.budget_basis
        : "manual",
    budget_rule_id:
      typeof p.budget_rule_id === "string" ? p.budget_rule_id : null,
    budget_note: typeof p.budget_note === "string" ? p.budget_note : "",
  };
}
