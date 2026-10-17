import { EditorState, TextSelection } from "prosemirror-state";
import { splitBlock } from "prosemirror-commands";
import { expect, it } from "vitest";
import {
  blockStyle,
  editorSchema,
  jsonDigest,
  stableNodeIds,
} from "./editorSchema";

const paragraph = {
  type: "paragraph",
  attrs: { id: "node-1" },
  content: [
    {
      type: "text",
      text: "工期 240 天，条件见附件。",
      marks: [{ type: "bold" }],
    },
  ],
};
it("段落拆分后保留原节点身份并给新段落唯一身份，要求和来源不因文字编辑消失", () => {
  const content = {
    type: "doc",
    attrs: {
      title: "施工进度",
      ordinal: 0,
      rule_ids: ["rule-1"],
      source_refs: [
        {
          source_id: "source-1",
          source_revision: 2,
          evidence_id: "evidence-1",
          document_version_id: "version-1",
        },
      ],
    },
    content: [paragraph],
  };
  let state = EditorState.create({
    schema: editorSchema,
    doc: editorSchema.nodeFromJSON(content),
    plugins: [stableNodeIds],
  });
  state = state.apply(
    state.tr.setSelection(TextSelection.create(state.doc, 5)),
  );
  expect(
    splitBlock(state, (transaction) => {
      state = state.applyTransaction(transaction).state;
    }),
  ).toBe(true);
  const saved = state.doc.toJSON();
  expect(saved.content).toHaveLength(2);
  expect(saved.content[0].attrs.id).toBe("node-1");
  expect(saved.content[1].attrs.id).not.toBe("node-1");
  expect(saved.attrs).toEqual(content.attrs);
  expect(
    saved.content
      .map(
        (node: { content?: { text?: string }[] }) =>
          node.content?.map((part) => part.text ?? "").join("") ?? "",
      )
      .join(""),
  ).toBe(paragraph.content[0].text);
});
it("补丁节点摘要与服务端UTF-8排序JSON算法一致，中文和标记不被当成不同选区", async () => {
  expect(await jsonDigest(paragraph)).toBe(
    "0c8c9214e159920d5d6402ea3c93ac284315f0523e62138d86a6c3edcee3dbb4",
  );
});
it("切换段落与标题保留稳定节点身份和原文字标记，补丁边界不因格式变化重建", () => {
  let state = EditorState.create({
    doc: editorSchema.nodeFromJSON({ type: "doc", content: [paragraph] }),
    plugins: [stableNodeIds],
  });
  state = state.apply(
    state.tr.setSelection(TextSelection.create(state.doc, 5)),
  );
  const dispatch = (transaction: Parameters<typeof state.apply>[0]) => {
    state = state.applyTransaction(transaction).state;
  };
  expect(blockStyle(2)(state, dispatch)).toBe(true);
  expect(state.doc.firstChild?.type.name).toBe("heading");
  expect(state.doc.firstChild?.attrs).toMatchObject({ id: "node-1", level: 2 });
  expect(state.doc.firstChild?.firstChild?.marks[0].type.name).toBe("bold");
  expect(blockStyle()(state, dispatch)).toBe(true);
  expect(state.doc.firstChild?.type.name).toBe("paragraph");
  expect(state.doc.firstChild?.attrs.id).toBe("node-1");
});
it("不接收目标之外的表格或外部图片节点，避免伪装无损Word编辑", () => {
  expect(() =>
    editorSchema.nodeFromJSON({ type: "table", content: [] }),
  ).toThrow();
  expect(() =>
    editorSchema.nodeFromJSON({
      type: "image",
      attrs: { src: "https://external.example/private.png" },
    }),
  ).toThrow();
});
