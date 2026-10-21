import "prosemirror-view/style/prosemirror.css";
import { useEffect, useRef, useState } from "react";
import type { Node as EditorNode, Schema } from "prosemirror-model";
import { Fragment, Slice } from "prosemirror-model";
import { EditorState } from "prosemirror-state";
import type { Command } from "prosemirror-state";
import { EditorView } from "prosemirror-view";
import { baseKeymap, chainCommands, toggleMark } from "prosemirror-commands";
import { keymap } from "prosemirror-keymap";
import { history, undo, redo } from "prosemirror-history";
import {
  liftListItem,
  sinkListItem,
  splitListItem,
  wrapInList,
} from "prosemirror-schema-list";
import { blockStyle, stableNodeIds } from "./editorSchema";
import { ErrorNotice } from "./components";
import { serializeAuthoringContent } from "./richEditorSchema";

const plugins = (editorSchema: Schema) => [
  stableNodeIds,
  history(),
  keymap({
    "Mod-z": undo,
    "Mod-y": redo,
    "Mod-Shift-z": redo,
    Enter: chainCommands(
      splitListItem(editorSchema.nodes.listItem),
      baseKeymap.Enter,
    ),
    "Shift-Enter": (state, dispatch) => {
      dispatch?.(
        state.tr
          .replaceSelectionWith(editorSchema.nodes.hardBreak.create())
          .scrollIntoView(),
      );
      return true;
    },
    "Mod-b": toggleMark(editorSchema.marks.bold),
    "Mod-i": toggleMark(editorSchema.marks.italic),
    "Mod-[": liftListItem(editorSchema.nodes.listItem),
    "Mod-]": sinkListItem(editorSchema.nodes.listItem),
  }),
  keymap(baseKeymap),
];
export function SourceEditor({
  bidId,
  value,
  disabled = false,
  onChange,
  onTarget,
}: {
  bidId?: string;
  value: EditorNode;
  disabled?: boolean;
  onChange: (value: EditorNode) => void;
  onTarget: (node: EditorNode | null) => void;
}) {
  const editorSchema = value.type.schema;
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const callbacks = useRef({ onChange, onTarget });
  callbacks.current = { onChange, onTarget };
  const initial = useRef({ value, disabled, bidId });
  initial.current = { value, disabled, bidId };
  const [selection, setSelection] = useState<EditorState | null>(null);
  const [pasteError, setPasteError] = useState<unknown>(null);
  useEffect(() => {
    if (!host.current) return;
    const editorSchema = initial.current.value.type.schema;
    const editor = new EditorView(host.current, {
      state: EditorState.create({
        schema: editorSchema,
        doc: initial.current.value,
        plugins: plugins(editorSchema),
      }),
      editable: () => !initial.current.disabled,
      attributes: {
        role: "textbox",
        "aria-label": "章节正文",
        "aria-multiline": "true",
        spellcheck: "true",
      },
      nodeViews:
        editorSchema.nodes.image && initial.current.bidId
          ? {
              image(node) {
                const figure = document.createElement("figure");
                figure.className = "authoring-image-node";
                figure.setAttribute("data-node-id", String(node.attrs.id));
                const image = document.createElement("img");
                image.alt = String(node.attrs.alt);
                image.src = `/api/v1/bids/${encodeURIComponent(initial.current.bidId!)}/authoring-images/${encodeURIComponent(String(node.attrs.asset_id))}/versions/${encodeURIComponent(String(node.attrs.asset_version_id))}/bytes/normalized`;
                image.style.width = `${Number(node.attrs.width_twips) / 15}px`;
                image.style.height = `${Number(node.attrs.height_twips) / 15}px`;
                const caption = document.createElement("figcaption");
                caption.textContent = `${node.attrs.caption || node.attrs.alt} · 图片版本 ${node.attrs.asset_revision}`;
                figure.append(image, caption);
                image.onerror = () => {
                  caption.textContent = `图片原件暂时无法预览；${node.attrs.alt} · 已保留绑定版本 ${node.attrs.asset_revision}`;
                };
                return { dom: figure, stopEvent: () => true };
              },
            }
          : {},
      dispatchTransaction(transaction) {
        const next = editor.state.applyTransaction(transaction).state;
        if (transaction.docChanged) {
          try {
            serializeAuthoringContent(next.doc);
          } catch (failure) {
            setPasteError(failure);
            return;
          }
        }
        editor.updateState(next);
        setSelection(next);
        if (transaction.docChanged) callbacks.current.onChange(next.doc);
        const { $from } = next.selection;
        let target: EditorNode | null = null;
        for (let depth = $from.depth; depth > 0; depth--) {
          const node = $from.node(depth);
          if (node.attrs.id) {
            target = node;
            break;
          }
        }
        callbacks.current.onTarget(target);
      },
      handlePaste(current, event) {
        if (
          /<(?:table|img)[\s>]/i.test(
            event.clipboardData?.getData("text/html") ?? "",
          )
        ) {
          setPasteError(
            new Error(
              "粘贴内容包含表格或图片，未隐式导入或展平这些对象。请使用表格或图片工具，或明确复制纯文字。",
            ),
          );
          return true;
        }
        const text = event.clipboardData?.getData("text/plain");
        if (text === undefined) return false;
        const lines = text.replace(/\r\n?/g, "\n").split("\n");
        setPasteError(null);
        const paragraphs = lines.map((line) =>
          editorSchema.nodes.paragraph.create(
            { id: crypto.randomUUID() },
            line ? editorSchema.text(line) : undefined,
          ),
        );
        current.dispatch(
          current.state.tr
            .replaceSelection(new Slice(Fragment.fromArray(paragraphs), 1, 1))
            .scrollIntoView(),
        );
        return true;
      },
    });
    view.current = editor;
    setSelection(editor.state);
    callbacks.current.onTarget(editor.state.selection.$from.parent);
    return () => {
      editor.destroy();
      view.current = null;
    };
  }, [editorSchema, bidId]);
  useEffect(() => {
    const editor = view.current;
    if (!editor) return;
    editor.setProps({ editable: () => !disabled });
    if (!editor.state.doc.eq(value)) {
      editor.updateState(
        EditorState.create({
          schema: editorSchema,
          doc: value,
          plugins: plugins(editorSchema),
        }),
      );
      setSelection(editor.state);
      callbacks.current.onTarget(editor.state.selection.$from.parent);
    }
  }, [value, disabled, editorSchema]);
  function run(command: Command) {
    const editor = view.current;
    if (!editor || disabled) return;
    command(editor.state, editor.dispatch, editor);
    editor.focus();
  }
  const marks =
    selection?.storedMarks ?? selection?.selection.$from.marks() ?? [];
  return (
    <div className="source-editor">
      <div className="editor-toolbar" role="toolbar" aria-label="章节正文格式">
        <select
          aria-label="段落样式"
          disabled={disabled}
          value={
            selection?.selection.$from.parent.type.name === "heading"
              ? String(selection.selection.$from.parent.attrs.level)
              : "paragraph"
          }
          onChange={(event) =>
            run(
              event.target.value === "paragraph"
                ? blockStyle()
                : blockStyle(Number(event.target.value)),
            )
          }
        >
          <option value="paragraph">正文段落</option>
          {[1, 2, 3, 4, 5, 6].map((level) => (
            <option value={level} key={level}>
              标题 {level}
            </option>
          ))}
        </select>
        {(
          [
            {
              label: "粗体",
              command: toggleMark(editorSchema.marks.bold),
              active: marks.some(
                (mark) => mark.type === editorSchema.marks.bold,
              ),
            },
            {
              label: "斜体",
              command: toggleMark(editorSchema.marks.italic),
              active: marks.some(
                (mark) => mark.type === editorSchema.marks.italic,
              ),
            },
            {
              label: "无序列表",
              command: wrapInList(editorSchema.nodes.bulletList),
            },
            {
              label: "有序列表",
              command: wrapInList(editorSchema.nodes.orderedList),
            },
            {
              label: "减少缩进",
              command: liftListItem(editorSchema.nodes.listItem),
            },
            {
              label: "增加缩进",
              command: sinkListItem(editorSchema.nodes.listItem),
            },
            { label: "撤销文字修改", command: undo },
            { label: "重做文字修改", command: redo },
          ] as const
        ).map((item) => (
          <button
            type="button"
            className="editor-tool"
            disabled={disabled}
            aria-pressed={"active" in item ? item.active : undefined}
            key={item.label}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => run(item.command)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <ErrorNotice error={pasteError} />
      <div ref={host} className="editor-surface" />
      <p className="small-note">
        支持段落、标题、列表、粗体和斜体。粘贴按纯文字接收，表格与图片使用明确的编制工具。编辑器内容需保存确认，再生成固定文件。
      </p>
    </div>
  );
}
