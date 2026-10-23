import { Schema } from "prosemirror-model";
import type { Node as EditorNode } from "prosemirror-model";
import type { SectionView } from "./contracts";
import { editorSchema } from "./editorSchema";

export type EditorDocument = SectionView["content"];
type RecordValue = Record<string, unknown>;
const record = (value: unknown): value is RecordValue =>
  !!value && typeof value === "object" && !Array.isArray(value);
const exact = (value: RecordValue, keys: string[]) =>
  Object.keys(value).length === keys.length &&
  keys.every((key) => key in value);
const positive = (value: unknown, maximum: number): value is number =>
  Number.isSafeInteger(value) && Number(value) > 0 && Number(value) <= maximum;
const uuid = (value: unknown) =>
  typeof value === "string" &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
function invalid(): never {
  throw new Error(
    "章节结构无法完整核对，原内容保留；请检查节点、表格合并或图片版本。",
  );
}

/** Separate opt-in schema: the old strict text producer still has no table/image nodes. */
export const richEditorSchema = new Schema({
  nodes: editorSchema.spec.nodes.append({
    table: {
      group: "block",
      content: "tableRow+",
      isolating: true,
      attrs: {
        id: { default: null },
        column_widths_twips: { default: [] },
        caption: { default: "" },
      },
      toDOM: (node) => [
        "table",
        {
          "data-node-id": node.attrs.id,
          "aria-label": node.attrs.caption || "正文表格",
        },
        [
          "colgroup",
          ...(node.attrs.column_widths_twips as number[]).map((width) => [
            "col",
            { style: `width:${width / 15}px` },
          ]),
        ],
        ["tbody", 0],
      ],
    },
    tableRow: {
      content: "tableCell*",
      attrs: { id: { default: null } },
      toDOM: (node) => ["tr", { "data-node-id": node.attrs.id }, 0],
    },
    tableCell: {
      content: "(paragraph|bulletList|orderedList)+",
      isolating: true,
      attrs: {
        id: { default: null },
        colspan: { default: 1 },
        rowspan: { default: 1 },
        header: { default: false },
      },
      toDOM: (node) => [
        node.attrs.header ? "th" : "td",
        {
          "data-node-id": node.attrs.id,
          colspan: node.attrs.colspan,
          rowspan: node.attrs.rowspan,
        },
        0,
      ],
    },
    image: {
      group: "block",
      atom: true,
      draggable: false,
      attrs: {
        id: { default: null },
        asset_id: {},
        asset_revision: {},
        asset_version_id: {},
        width_twips: {},
        height_twips: {},
        alt: {},
        caption: { default: "" },
      },
      toDOM: (node) => [
        "figure",
        { "data-node-id": node.attrs.id, class: "authoring-image-node" },
        [
          "figcaption",
          `图片：${node.attrs.alt}${node.attrs.caption ? ` · ${node.attrs.caption}` : ""}`,
        ],
      ],
      leafText: (node) => `[图片：${node.attrs.alt}]`,
    },
  }),
  marks: editorSchema.spec.marks,
});

/** Reject lossy ProseMirror coercion (unknown attrs/nodes) before accepting server/local JSON. */
export function validateEditableContent(
  content: unknown,
  rich = true,
): asserts content is EditorDocument {
  if (
    !record(content) ||
    !exact(content, ["type", "attrs", "content"]) ||
    content.type !== "doc" ||
    !record(content.attrs) ||
    !Array.isArray(content.content)
  )
    invalid();
  const documentAttrs = content.attrs;
  if (
    !exact(documentAttrs, ["title", "ordinal", "rule_ids", "source_refs"]) ||
    typeof documentAttrs.title !== "string" ||
    documentAttrs.title.length > 200 ||
    !Number.isSafeInteger(documentAttrs.ordinal) ||
    Number(documentAttrs.ordinal) < 0 ||
    Number(documentAttrs.ordinal) >= 500
  )
    invalid();
  if (
    !["rule_ids", "source_refs"].every(
      (key) =>
        Array.isArray(documentAttrs[key]) && documentAttrs[key].length <= 500,
    )
  )
    invalid();
  const ids = new Set<string>();
  let count = 0;
  const allowed: Record<string, string[]> = {
    doc: [
      "paragraph",
      "heading",
      "bulletList",
      "orderedList",
      ...(rich ? ["table", "image"] : []),
    ],
    paragraph: ["text", "hardBreak"],
    heading: ["text", "hardBreak"],
    bulletList: ["listItem"],
    orderedList: ["listItem"],
    listItem: ["paragraph", "bulletList", "orderedList"],
    table: ["tableRow"],
    tableRow: ["tableCell"],
    tableCell: ["paragraph", "bulletList", "orderedList"],
  };
  function visit(value: unknown, parent: string, depth: number) {
    if (
      !record(value) ||
      typeof value.type !== "string" ||
      !allowed[parent]?.includes(value.type) ||
      depth > 12 ||
      ++count > 10000
    )
      invalid();
    const kind = value.type;
    if (kind === "text") {
      if (
        Object.keys(value).some(
          (key) => !["type", "text", "marks"].includes(key),
        ) ||
        typeof value.text !== "string" ||
        (value.marks !== undefined &&
          (!Array.isArray(value.marks) ||
            !value.marks.every(
              (mark) =>
                record(mark) &&
                exact(mark, ["type"]) &&
                ["bold", "italic"].includes(String(mark.type)),
            )))
      )
        invalid();
      return;
    }
    if (kind === "hardBreak") {
      if (!exact(value, ["type"])) invalid();
      return;
    }
    if (
      !exact(
        value,
        kind === "image" ? ["type", "attrs"] : ["type", "attrs", "content"],
      ) ||
      !record(value.attrs)
    )
      invalid();
    const attrs = value.attrs;
    const keys =
      kind === "heading"
        ? ["id", "level"]
        : kind === "table"
          ? ["id", "column_widths_twips", "caption"]
          : kind === "tableCell"
            ? ["id", "colspan", "rowspan", "header"]
            : kind === "image"
              ? [
                  "id",
                  "asset_id",
                  "asset_revision",
                  "asset_version_id",
                  "width_twips",
                  "height_twips",
                  "alt",
                  "caption",
                ]
              : ["id"];
    if (
      !exact(attrs, keys) ||
      typeof attrs.id !== "string" ||
      !attrs.id ||
      attrs.id.length > 128 ||
      ids.has(attrs.id)
    )
      invalid();
    ids.add(attrs.id);
    if (kind === "heading" && !positive(attrs.level, 6)) invalid();
    if (kind === "image") {
      if (
        !uuid(attrs.asset_id) ||
        !uuid(attrs.asset_version_id) ||
        !positive(attrs.asset_revision, Number.MAX_SAFE_INTEGER) ||
        !positive(attrs.width_twips, 20000) ||
        !positive(attrs.height_twips, 20000) ||
        typeof attrs.alt !== "string" ||
        !attrs.alt.trim() ||
        attrs.alt.length > 1000 ||
        typeof attrs.caption !== "string" ||
        attrs.caption.length > 1000
      )
        invalid();
      return;
    }
    if (!Array.isArray(value.content)) invalid();
    if (
      kind === "tableCell" &&
      (!positive(attrs.colspan, 100) ||
        !positive(attrs.rowspan, 200) ||
        typeof attrs.header !== "boolean" ||
        !value.content.length)
    )
      invalid();
    value.content.forEach((child) => visit(child, kind, depth + 1));
    if (kind === "table") validateGrid(value);
  }
  content.content.forEach((node) => visit(node, "doc", 0));
  if (new TextEncoder().encode(JSON.stringify(content)).byteLength > 1_000_000)
    invalid();
}

function validateGrid(table: RecordValue) {
  const attrs = table.attrs as RecordValue;
  const widths = attrs.column_widths_twips;
  const rows = table.content as RecordValue[];
  if (
    !Array.isArray(widths) ||
    !widths.length ||
    widths.length > 100 ||
    !widths.every((width) => positive(width, 20000)) ||
    !rows.length ||
    rows.length > 200 ||
    rows.length * widths.length > 10000 ||
    typeof attrs.caption !== "string" ||
    attrs.caption.length > 1000
  )
    invalid();
  const grid = Array.from({ length: rows.length }, () =>
    Array.from({ length: widths.length }, () => false),
  );
  rows.forEach((row, y) => {
    let x = 0;
    (row.content as RecordValue[]).forEach((cell) => {
      const size = cell.attrs as { colspan: number; rowspan: number };
      while (x < widths.length && grid[y][x]) x++;
      if (x + size.colspan > widths.length || y + size.rowspan > rows.length)
        invalid();
      for (let yy = y; yy < y + size.rowspan; yy++)
        for (let xx = x; xx < x + size.colspan; xx++) {
          if (grid[yy][xx]) invalid();
          grid[yy][xx] = true;
        }
      x += size.colspan;
    });
    if (grid[y].some((occupied) => !occupied)) invalid();
  });
}

export function readAuthoringContent(
  content: unknown,
  rich = true,
): EditorNode {
  validateEditableContent(content, rich);
  const node = (rich ? richEditorSchema : editorSchema).nodeFromJSON(content);
  node.check();
  return node;
}
export function serializeAuthoringNode(node: EditorNode): unknown {
  const value = node.toJSON() as RecordValue;
  if (!["text", "hardBreak", "image"].includes(node.type.name)) {
    const children: unknown[] = [];
    node.forEach((child) => children.push(serializeAuthoringNode(child)));
    value.content = children;
  }
  return value;
}
/** Empty paragraphs and fully covered table rows are explicit in the closed wire protocol. */
export function serializeAuthoringContent(node: EditorNode): EditorDocument {
  const value = serializeAuthoringNode(node);
  validateEditableContent(value, !!node.type.schema.nodes.table);
  return value;
}
export function hasRichContent(content: EditorDocument) {
  return content.content.some(
    (node) => node.type === "table" || node.type === "image",
  );
}
export function authoringText(content: unknown) {
  try {
    const node = readAuthoringContent(content);
    return node.textBetween(0, node.content.size, "\n");
  } catch {
    return "章节结构无法完整读取，请保留原内容并重新核对。";
  }
}
