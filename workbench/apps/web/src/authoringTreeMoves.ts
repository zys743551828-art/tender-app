import type {
  AuthoringTreeChangeRequest,
  AuthoringTreeView,
} from "./contracts";
export type TreeMoveIntent = {
  sourceId: string;
  targetId: string;
  placement: "before" | "after" | "inside";
};
type Nodes = AuthoringTreeView["nodes"];
export function treeMoveKey(tree: AuthoringTreeView): string {
  return JSON.stringify([
    tree.draft_id,
    [...tree.nodes]
      .sort((a, b) => a.section_id.localeCompare(b.section_id))
      .map((n) => [
        n.section_id,
        n.parent_id,
        n.ordinal,
        n.title,
        n.node_type,
        n.deleted,
      ]),
  ]);
}
export function resolveTreeMove(
  nodes: Nodes,
  intent: TreeMoveIntent,
): Extract<AuthoringTreeChangeRequest["changes"][number], { op: "move" }> {
  const active = nodes.filter((n) => !n.deleted);
  const byId = new Map(active.map((n) => [n.section_id, n]));
  if (byId.size !== active.length || active.length > 500)
    throw new Error("章节目录身份或数量无法核对，请重新读取。");
  function ancestry(id: string): string[] {
    const result: string[] = [];
    let current: string | null = id;
    while (current !== null) {
      if (result.includes(current))
        throw new Error("章节目录存在循环，请重新读取。");
      const node = byId.get(current);
      if (!node) throw new Error("章节或上级已删除或不存在，请重新选择。");
      result.push(current);
      current = node.parent_id;
    }
    return result;
  }
  for (const node of active) ancestry(node.section_id);
  const source = byId.get(intent.sourceId),
    target = byId.get(intent.targetId);
  if (!source || !target)
    throw new Error("移动章节或目标已删除或不存在，请重新选择。");
  if (!["before", "after", "inside"].includes(intent.placement))
    throw new Error("请选择有效的移动位置。");
  if (source.section_id === target.section_id)
    throw new Error("不能把章节移动到自身。");
  if (ancestry(target.section_id).includes(source.section_id))
    throw new Error("不能把章节移动到自己的子章中。");
  const parentId =
    intent.placement === "inside" ? target.section_id : target.parent_id;
  const parentDepth = parentId === null ? 0 : ancestry(parentId).length;
  const subtreeHeight = Math.max(
    ...active.map((n) => {
      const path = ancestry(n.section_id);
      const index = path.indexOf(source.section_id);
      return index < 0 ? 0 : index + 1;
    }),
  );
  if (parentDepth + subtreeHeight > 6)
    throw new Error("移动后将超过六层章节，请选择更浅的上级。");
  const siblings = active
    .filter(
      (n) => n.parent_id === parentId && n.section_id !== source.section_id,
    )
    .sort(
      (a, b) =>
        a.ordinal - b.ordinal || a.section_id.localeCompare(b.section_id),
    );
  const ordinal =
    intent.placement === "inside"
      ? siblings.length
      : siblings.findIndex((n) => n.section_id === target.section_id) +
        (intent.placement === "after" ? 1 : 0);
  const original = active
    .filter((n) => n.parent_id === source.parent_id)
    .sort(
      (a, b) =>
        a.ordinal - b.ordinal || a.section_id.localeCompare(b.section_id),
    );
  if (
    source.parent_id === parentId &&
    original.findIndex((n) => n.section_id === source.section_id) === ordinal
  )
    throw new Error("章节已在这个位置，无需移动。");
  return {
    op: "move",
    section_id: source.section_id,
    parent: parentId === null ? null : { section_id: parentId },
    ordinal,
  };
}
