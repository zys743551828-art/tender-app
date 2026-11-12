import {
  cleanup,
  act,
  fireEvent,
  render,
  screen,
  within,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AuthoringChapterTree } from "./AuthoringChapterTree";
import { treeMoveKey } from "./authoringTreeMoves";
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

beforeEach(() => sessionStorage.clear());
afterEach(cleanup);
function setup(nodes = [node("a"), node("child", "a"), node("b", null, 1)]) {
  const props = {
    tree: tree(nodes),
    navigationLocked: false,
    moveDisabled: false,
    onChoose: vi.fn(async () => {}),
    onMove: vi.fn(async () => {}),
    storageKey: "test-folds",
  };
  return { props, ...render(<AuthoringChapterTree {...props} />) };
}
const handle = (id: string) =>
  screen.getByRole("button", { name: `选择移动章节：${id}` });
function dragStart(id: string) {
  fireEvent.dragStart(handle(id), {
    dataTransfer: { effectAllowed: "none", getData: () => "external" },
  });
}
function drop(id: string) {
  fireEvent.drop(handle(id).closest("li")!);
}
it("折叠只持久导航状态，选中子章的祖先保持展开", () => {
  const view = setup();
  fireEvent.click(screen.getByRole("button", { name: "收起a的子章" }));
  expect(handle.bind(null, "child")).toThrow();
  expect(sessionStorage.getItem("test-folds")).toBe('["a"]');
  view.rerender(<AuthoringChapterTree {...view.props} sectionId="child" />);
  expect(handle("child")).toBeVisible();
  expect(screen.getByRole("button", { name: "收起a的子章" })).toBeDisabled();
  expect(view.props.onChoose).not.toHaveBeenCalled();
  expect(view.props.onMove).not.toHaveBeenCalled();
});
it("移动手柄键盘选择来源并聚焦表单，不切正文；表单和拖放产生相同意图", async () => {
  const view = setup(),
    user = userEvent.setup();
  handle("child").focus();
  await user.keyboard("{Enter}");
  expect(screen.getByRole("combobox", { name: "移动章节" })).toHaveFocus();
  expect(view.props.onChoose).not.toHaveBeenCalled();
  await user.selectOptions(
    screen.getByRole("combobox", { name: "目标章节" }),
    "b",
  );
  await user.selectOptions(
    screen.getByRole("combobox", { name: "移动位置" }),
    "after",
  );
  await user.click(screen.getByRole("button", { name: "预览所选章节移动" }));
  expect(view.props.onMove).toHaveBeenLastCalledWith(
    { sourceId: "child", targetId: "b", placement: "after" },
    treeMoveKey(view.props.tree),
  );
  dragStart("child");
  drop("b");
  expect(view.props.onMove).toHaveBeenCalledTimes(2);
});
it("外来拖放与结构漂移不产生移动，旧表单失效；正文保存不算结构漂移", async () => {
  const view = setup(),
    user = userEvent.setup();
  drop("b");
  expect(view.props.onMove).not.toHaveBeenCalled();
  await user.selectOptions(
    screen.getByRole("combobox", { name: "移动章节" }),
    "child",
  );
  await user.selectOptions(
    screen.getByRole("combobox", { name: "目标章节" }),
    "b",
  );
  dragStart("child");
  const saved = {
    ...view.props.tree,
    draft_revision: 2,
    nodes: view.props.tree.nodes.map((n) => ({ ...n, section_revision: 2 })),
  };
  view.rerender(<AuthoringChapterTree {...view.props} tree={saved} />);
  drop("b");
  expect(view.props.onMove).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(handle("child")).toBeEnabled());
  dragStart("child");
  view.rerender(
    <AuthoringChapterTree
      {...view.props}
      tree={{
        ...saved,
        nodes: saved.nodes.map((n) =>
          n.section_id === "b" ? { ...n, title: "renamed" } : n,
        ),
      }}
    />,
  );
  drop("renamed");
  expect(view.props.onMove).toHaveBeenCalledTimes(1);
  expect(
    screen.getByRole("button", { name: "预览所选章节移动" }),
  ).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent("章节目录已变化");
});
it.each(["moveDisabled", "navigationLocked"] as const)(
  "%s锁定拒绝拖放与表单提交",
  (key) => {
    const view = setup();
    dragStart("child");
    view.rerender(
      <AuthoringChapterTree {...view.props} {...{ [key]: true }} />,
    );
    drop("b");
    fireEvent.submit(screen.getByRole("form", { name: "章节移动预览" }));
    expect(view.props.onMove).not.toHaveBeenCalled();
    expect(handle("child")).toBeDisabled();
  },
);
it("500节点及已删除节点，保持原有章/修订/计划文案", () => {
  const nodes = Array.from({ length: 500 }, (_, i) => node(`n${i}`, null, i));
  const view = setup([...nodes, { ...node("deleted"), deleted: true }]);
  expect(
    within(screen.getByRole("list", { name: "当前章节层级" })).getAllByRole(
      "listitem",
    ),
  ).toHaveLength(500);
  expect(
    screen.queryByRole("button", { name: "选择移动章节：deleted" }),
  ).toBeNull();
  expect(screen.getAllByText(/修订 1.*未填.*未建计划/)).toHaveLength(500);
  expect(view.props.onMove).not.toHaveBeenCalled();
});

it("scope切换不继承折叠/移动手势，过期表单强制提交也不发送", async () => {
  const view = setup(),
    user = userEvent.setup();
  await user.selectOptions(
    screen.getByRole("combobox", { name: "移动章节" }),
    "child",
  );
  await user.selectOptions(
    screen.getByRole("combobox", { name: "目标章节" }),
    "b",
  );
  fireEvent.click(screen.getByRole("button", { name: "收起a的子章" }));
  dragStart("a");
  view.rerender(
    <AuthoringChapterTree {...view.props} storageKey="other-scope" />,
  );
  expect(handle("child")).toBeVisible();
  drop("b");
  fireEvent.submit(screen.getByRole("form", { name: "章节移动预览" }));
  expect(view.props.onMove).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveTextContent("重新选择");
  expect(sessionStorage.getItem("other-scope")).toBeNull();
});
it("自移只提示原因不调用父预览，已有折叠在重开后恢复", async () => {
  const first = setup();
  fireEvent.click(screen.getByRole("button", { name: "收起a的子章" }));
  first.unmount();
  const view = setup(),
    user = userEvent.setup();
  expect(screen.getByRole("button", { name: "展开a的子章" })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
  await user.selectOptions(
    screen.getByRole("combobox", { name: "移动章节" }),
    "b",
  );
  await user.selectOptions(
    screen.getByRole("combobox", { name: "目标章节" }),
    "b",
  );
  await user.click(screen.getByRole("button", { name: "预览所选章节移动" }));
  expect(screen.getByRole("alert")).toHaveTextContent("自身");
  expect(view.props.onMove).not.toHaveBeenCalled();
});

it("仅有效内部拖放高亮精确目标，取消/结束/换树清理且不向祖先冒泡", () => {
  const view = setup();
  const row = (id: string) => handle(id).closest(".chapter-tree-row")!;
  fireEvent.dragOver(handle("child"));
  expect(view.container.querySelectorAll(".drop-target")).toHaveLength(0);
  dragStart("b");
  fireEvent.dragOver(handle("child"));
  expect(row("child")).toHaveClass("drop-target");
  expect(row("a")).not.toHaveClass("drop-target");
  expect(view.container.querySelectorAll(".drop-target")).toHaveLength(1);
  fireEvent.keyDown(handle("b"), { key: "Escape" });
  expect(row("child")).not.toHaveClass("drop-target");
  drop("child");
  expect(view.props.onMove).not.toHaveBeenCalled();
  dragStart("b");
  fireEvent.dragOver(handle("child"));
  fireEvent.dragEnd(handle("b"));
  expect(row("child")).not.toHaveClass("drop-target");
  dragStart("b");
  fireEvent.dragOver(handle("child"));
  view.rerender(
    <AuthoringChapterTree
      {...view.props}
      tree={{
        ...view.props.tree,
        nodes: view.props.tree.nodes.map((n) => ({
          ...n,
          title: n.title + "new",
        })),
      }}
    />,
  );
  expect(view.container.querySelectorAll(".drop-target")).toHaveLength(0);
  expect(view.container.querySelectorAll(".chapter-fold-spacer")).toHaveLength(
    2,
  );
});
it("旧scope迟到失败不污染新scope，也不改变父回执", async () => {
  const view = setup();
  let reject!: (error: Error) => void;
  view.props.onMove.mockImplementationOnce(
    () =>
      new Promise<void>((_resolve, rejectPromise) => {
        reject = rejectPromise;
      }),
  );
  dragStart("child");
  drop("b");
  expect(view.props.onMove).toHaveBeenCalledTimes(1);
  view.rerender(
    <AuthoringChapterTree {...view.props} storageKey="new-scope" />,
  );
  expect(handle("child")).toBeEnabled();
  await act(async () => reject(new Error("OLD_SCOPE_ERROR")));
  expect(screen.queryByText("OLD_SCOPE_ERROR")).toBeNull();
  expect(handle("child")).toBeEnabled();
});
