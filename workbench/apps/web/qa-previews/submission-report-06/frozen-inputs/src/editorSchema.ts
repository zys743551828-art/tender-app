import { Schema } from "prosemirror-model";
import type { Node as EditorNode } from "prosemirror-model";
import { Plugin } from "prosemirror-state";
import type { Command } from "prosemirror-state";

const idAttribute = { id: { default: null } };
/** Formatting changes a block's presentation without changing its patch identity. */
export function blockStyle(level?: number): Command {
  return (state, dispatch) => {
    const type = level
      ? editorSchema.nodes.heading
      : editorSchema.nodes.paragraph;
    const transaction = state.tr;
    let changed = false;
    state.doc.nodesBetween(
      state.selection.from,
      state.selection.to,
      (node, position) => {
        if (
          node.type !== editorSchema.nodes.paragraph &&
          node.type !== editorSchema.nodes.heading
        )
          return;
        const place = state.doc.resolve(position);
        if (
          !place.parent.canReplaceWith(place.index(), place.index() + 1, type)
        )
          return;
        transaction.setNodeMarkup(
          position,
          type,
          level ? { id: node.attrs.id, level } : { id: node.attrs.id },
          node.marks,
        );
        changed = true;
      },
    );
    if (changed) dispatch?.(transaction.scrollIntoView());
    return changed;
  };
}
function readId(dom: HTMLElement) {
  return { id: dom.getAttribute("data-node-id") };
}
function attributes(node: EditorNode) {
  return { "data-node-id": node.attrs.id };
}

/** The backend's closed subset; arbitrary HTML/assets never become saved nodes. */
export const editorSchema = new Schema({
  nodes: {
    doc: {
      content: "block*",
      attrs: {
        title: { default: "章节" },
        ordinal: { default: 0 },
        rule_ids: { default: [] },
        source_refs: { default: [] },
      },
    },
    paragraph: {
      group: "block",
      content: "inline*",
      attrs: idAttribute,
      parseDOM: [{ tag: "p", getAttrs: readId }],
      toDOM: (node) => ["p", attributes(node), 0],
    },
    heading: {
      group: "block",
      content: "inline*",
      defining: true,
      attrs: { ...idAttribute, level: { default: 1 } },
      parseDOM: [1, 2, 3, 4, 5, 6].map((level) => ({
        tag: `h${level}`,
        getAttrs: (dom: HTMLElement) => ({ ...readId(dom), level }),
      })),
      toDOM: (node) => [`h${node.attrs.level}`, attributes(node), 0],
    },
    bulletList: {
      group: "block",
      content: "listItem*",
      attrs: idAttribute,
      parseDOM: [{ tag: "ul", getAttrs: readId }],
      toDOM: (node) => ["ul", attributes(node), 0],
    },
    orderedList: {
      group: "block",
      content: "listItem*",
      attrs: idAttribute,
      parseDOM: [{ tag: "ol", getAttrs: readId }],
      toDOM: (node) => ["ol", attributes(node), 0],
    },
    listItem: {
      content: "(paragraph|bulletList|orderedList)*",
      defining: true,
      attrs: idAttribute,
      parseDOM: [{ tag: "li", getAttrs: readId }],
      toDOM: (node) => ["li", attributes(node), 0],
    },
    text: { group: "inline" },
    hardBreak: {
      inline: true,
      group: "inline",
      selectable: false,
      parseDOM: [{ tag: "br" }],
      toDOM: () => ["br"],
    },
  },
  marks: {
    bold: {
      parseDOM: [
        { tag: "strong" },
        { tag: "b" },
        { style: "font-weight=bold" },
      ],
      toDOM: () => ["strong", 0],
    },
    italic: {
      parseDOM: [{ tag: "em" }, { tag: "i" }, { style: "font-style=italic" }],
      toDOM: () => ["em", 0],
    },
  },
});

export const stableNodeIds = new Plugin({
  appendTransaction(transactions, _old, state) {
    if (!transactions.some((transaction) => transaction.docChanged))
      return null;
    const seen = new Set<string>();
    const transaction = state.tr;
    state.doc.descendants((node, position) => {
      if (node.isText || node.type.name === "hardBreak") return;
      let id = node.attrs.id as string | null;
      if (!id || seen.has(id)) {
        id = crypto.randomUUID();
        transaction.setNodeMarkup(position, undefined, { ...node.attrs, id });
      }
      seen.add(id);
    });
    return transaction.docChanged ? transaction : null;
  },
});

export function editorText(content: unknown): string {
  try {
    const node = editorSchema.nodeFromJSON(content);
    return node.textBetween(0, node.content.size, "\n");
  } catch {
    return "章节结构无法读取，请保留原内容并重试。";
  }
}
export async function jsonDigest(value: unknown) {
  function ordered(input: unknown): unknown {
    if (Array.isArray(input)) return input.map(ordered);
    if (input && typeof input === "object")
      return Object.fromEntries(
        Object.entries(input)
          .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
          .map(([key, nested]) => [key, ordered(nested)]),
      );
    return input;
  }
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(JSON.stringify(ordered(value))),
  );
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}
