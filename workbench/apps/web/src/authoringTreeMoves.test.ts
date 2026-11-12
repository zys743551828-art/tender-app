import { expect, it } from "vitest";
import { resolveTreeMove, treeMoveKey } from "./authoringTreeMoves";
import type { AuthoringTreeView } from "./contracts";
function node(
  id: string,
  parent: string | null = null,
  ordinal = 0,
): AuthoringTreeView["nodes"][number] {
  return {
    section_id: id,
    parent_id: parent,
    ordinal,
    node_type: "chapter",
    deleted: false,
    section_revision: 1,
    plan_version_id: null,
    template_family_id: null,
    template_key: null,
    title: id,
    rule_ids: [],
    source_refs: [],
    plan: null,
    plan_content_basis_state: "none",
    actual_page_range: null,
  };
}
function tree(nodes: AuthoringTreeView["nodes"]): AuthoringTreeView {
  return {
    draft_id: "draft",
    draft_revision: 1,
    snapshot_id: "snapshot",
    structure_version_id: "structure",
    nodes,
    directory_template_version_id: "directory",
    style_template_version_id: "style",
    metadata: {},
    page_budget: {
      planned_total: 0,
      unknown_section_ids: [],
      actual_total: null,
      actual_ranges_state: "unknown",
    },
  };
}

it.each([
  ["a", "c", "after", 2],
  ["c", "a", "before", 0],
  ["a", "c", "before", 1],
  ["c", "a", "after", 1],
] as const)(
  "同级 %s -> %s %s 排除来源后序号正确",
  (sourceId, targetId, placement, ordinal) => {
    const nodes = [node("a", null, 0), node("b", null, 1), node("c", null, 2)];
    const before = structuredClone(nodes);
    expect(resolveTreeMove(nodes, { sourceId, targetId, placement })).toEqual({
      op: "move",
      section_id: sourceId,
      parent: null,
      ordinal,
    });
    expect(nodes).toEqual(before);
  },
);
it("跨级前后和放入末尾保留完整子树", () => {
  const nodes = [
    node("a"),
    node("b", null, 1),
    node("c", "b"),
    node("d", "b", 1),
    node("child", "a"),
  ];
  expect(
    resolveTreeMove(nodes, {
      sourceId: "a",
      targetId: "c",
      placement: "before",
    }),
  ).toMatchObject({ parent: { section_id: "b" }, ordinal: 0 });
  expect(
    resolveTreeMove(nodes, {
      sourceId: "a",
      targetId: "c",
      placement: "after",
    }),
  ).toMatchObject({ parent: { section_id: "b" }, ordinal: 1 });
  expect(
    resolveTreeMove(nodes, {
      sourceId: "a",
      targetId: "b",
      placement: "inside",
    }),
  ).toMatchObject({ parent: { section_id: "b" }, ordinal: 2 });
  expect(
    resolveTreeMove(nodes, {
      sourceId: "c",
      targetId: "a",
      placement: "after",
    }),
  ).toMatchObject({ parent: null, ordinal: 1 });
});
it.each([
  ["a", "a", "inside"],
  ["a", "child", "before"],
  ["a", "child", "after"],
  ["a", "child", "inside"],
  ["missing", "a", "before"],
  ["a", "deleted", "inside"],
] as const)(
  "拒绝自环/后代/失效范围 %s %s %s",
  (sourceId, targetId, placement) => {
    expect(() =>
      resolveTreeMove(
        [node("a"), node("child", "a"), { ...node("deleted"), deleted: true }],
        { sourceId, targetId, placement },
      ),
    ).toThrow();
  },
);
it("已有同级位置和末尾子章无变化需明确说明", () => {
  const nodes = [node("a"), node("b", null, 1), node("c", "b")];
  for (const intent of [
    { sourceId: "a", targetId: "b", placement: "before" },
    { sourceId: "b", targetId: "a", placement: "after" },
    { sourceId: "c", targetId: "b", placement: "inside" },
  ] as const)
    expect(() => resolveTreeMove(nodes, intent)).toThrow("无需移动");
});
it("六层边界含来源整棵子树，不能只检查根", () => {
  const chain = Array.from({ length: 5 }, (_, i) =>
    node(`n${i}`, i ? `n${i - 1}` : null),
  );
  expect(
    resolveTreeMove([...chain, node("source", null, 1)], {
      sourceId: "source",
      targetId: "n4",
      placement: "inside",
    }),
  ).toMatchObject({ parent: { section_id: "n4" } });
  expect(() =>
    resolveTreeMove(
      [...chain, node("source", null, 1), node("child", "source")],
      { sourceId: "source", targetId: "n4", placement: "inside" },
    ),
  ).toThrow("六层");
});
it("500节点可移动，不修改输入且拒绝坏拓扑", () => {
  const nodes = Array.from({ length: 500 }, (_, i) => node(`n${i}`, null, i));
  expect(
    resolveTreeMove(nodes, {
      sourceId: "n0",
      targetId: "n499",
      placement: "after",
    }).ordinal,
  ).toBe(499);
  expect(nodes[0].ordinal).toBe(0);
  expect(() =>
    resolveTreeMove([node("a", "b"), node("b", "a")], {
      sourceId: "a",
      targetId: "b",
      placement: "inside",
    }),
  ).toThrow("循环");
  expect(() =>
    resolveTreeMove([node("a", "gone"), node("b")], {
      sourceId: "a",
      targetId: "b",
      placement: "inside",
    }),
  ).toThrow("不存在");
});
it("移动身份忽略正文修订但固定拓扑标题类型删除及草稿", () => {
  const original = tree([node("a"), node("b", null, 1)]),
    key = treeMoveKey(original);
  expect(
    treeMoveKey({
      ...original,
      draft_revision: 2,
      snapshot_id: "new",
      structure_version_id: "new",
      nodes: [original.nodes[1], { ...original.nodes[0], section_revision: 9 }],
    }),
  ).toBe(key);
  for (const patch of [
    { title: "new" },
    { parent_id: "b" },
    { ordinal: 2 },
    { node_type: "appendix" as const },
    { deleted: true },
  ])
    expect(
      treeMoveKey({
        ...original,
        nodes: [{ ...original.nodes[0], ...patch }, original.nodes[1]],
      }),
    ).not.toBe(key);
  expect(treeMoveKey({ ...original, draft_id: "other" })).not.toBe(key);
});
