import { expect, it } from "vitest";
import {
  createTable,
  mergeTable,
  splitTableCell,
  tableGrid,
} from "./richTableTools";
import {
  richEditorSchema,
  serializeAuthoringContent,
  validateEditableContent,
} from "./richEditorSchema";

it("跨行列合并与拆分保留全部段落和已有稳定身份", () => {
  const table = createTable(3, 3, 7500, "施工安排", true);
  table.content.forEach((row, y) =>
    row.content.forEach((cell, x) => {
      cell.content[0].content = [{ type: "text", text: `${y + 1}/${x + 1}` }];
    }),
  );
  const merged = mergeTable(table, 1, 1, 2, 2);
  expect(merged.content[0].content[0].attrs).toEqual({
    ...table.content[0].content[0].attrs,
    rowspan: 2,
    colspan: 2,
  });
  expect(
    merged.content[0].content[0].content.map((block) => block.content?.[0]),
  ).toEqual(
    ["1/1", "1/2", "2/1", "2/2"].map((text) => ({ type: "text", text })),
  );
  expect(merged.content[2]).toEqual(table.content[2]);
  expect(() => mergeTable(merged, 2, 2, 2, 2)).toThrow("切过已有合并单元格");
  const split = splitTableCell(merged, 2, 2);
  expect(split.content[0].content[0].attrs).toEqual(
    table.content[0].content[0].attrs,
  );
  expect(split.content[0].content[0].content).toEqual(
    merged.content[0].content[0].content,
  );
  expect(split.content[2]).toEqual(table.content[2]);
  expect(tableGrid(split).origins).toHaveLength(9);
  expect(table.content[0].content[0].attrs.colspan).toBe(1);
});

it("跨全部行合并后空行与空段落可精确保留，不被 PM JSON 省略破坏协议", () => {
  const table = mergeTable(createTable(2, 2, 6000, "整表", false), 1, 1, 2, 2);
  const raw = {
    type: "doc",
    attrs: { title: "章节", ordinal: 0, rule_ids: [], source_refs: [] },
    content: [table],
  };
  validateEditableContent(raw);
  const doc = richEditorSchema.nodeFromJSON(raw);
  expect(serializeAuthoringContent(doc)).toEqual(raw);
});

it.each(["overlap", "hole", "overflow"])(
  "有 %s 的表格不会作为可保存内容",
  (mode) => {
    const table = createTable(2, 2, 6000, "待核对", false);
    if (mode === "overlap") table.content[0].content[0].attrs.rowspan = 2;
    if (mode === "hole") table.content[0].content.pop();
    if (mode === "overflow") table.content[0].content[0].attrs.colspan = 3;
    expect(() => tableGrid(table)).toThrow("章节结构无法完整核对");
  },
);

it("重复表头必须显式声明且保留序列化身份", () => {
  const ordinary = createTable(3, 2, 5000, "", true);
  const repeating = createTable(3, 2, 5000, "", true, true);
  const document = (table: typeof repeating) => ({
    type: "doc",
    attrs: { title: "表格", ordinal: 0, rule_ids: [], source_refs: [] },
    content: [table],
  });
  expect(ordinary.attrs).not.toHaveProperty("pagination");
  expect(repeating.attrs.pagination).toEqual({
    protocol: "authoring-table-pagination/1",
    repeat_header_rows: 1,
  });
  for (const table of [ordinary, repeating]) {
    expect(
      serializeAuthoringContent(richEditorSchema.nodeFromJSON(document(table))),
    ).toEqual(document(table));
  }
  expect(() => createTable(3, 2, 5000, "", false, true)).toThrow();
  expect(() => createTable(1, 2, 5000, "", true, true)).toThrow();
  expect(() => createTable(13, 2, 5000, "", true, true)).toThrow();
  expect(() => mergeTable(repeating, 1, 1, 1, 2)).toThrow();
  for (const pagination of [
    null,
    {},
    { protocol: "authoring-table-pagination/1", repeat_header_rows: true },
    { ...repeating.attrs.pagination, extra: true },
  ]) {
    expect(() =>
      validateEditableContent({
        ...document(repeating),
        content: [{ ...repeating, attrs: { ...repeating.attrs, pagination } }],
      }),
    ).toThrow();
  }
});
