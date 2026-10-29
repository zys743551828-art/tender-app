import "prosemirror-view/style/prosemirror.css";
import { useEffect, useRef, useState } from "react";
import type { Node as EditorNode } from "prosemirror-model";
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
import { blockStyle, editorSchema, stableNodeIds } from "./editorSchema";
import { ErrorNotice } from "./components";

const plugins = () => [
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
  value,
  disabled = false,
  onChange,
  onTarget,
}: {
  value: EditorNode;
  disabled?: boolean;
  onChange: (value: EditorNode) => void;
  onTarget: (node: EditorNode | null) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const callbacks = useRef({ onChange, onTarget });
  callbacks.current = { onChange, onTarget };
  const initial = useRef({ value, disabled });
  const [selection, setSelection] = useState<EditorState | null>(null);
  const [pasteError, setPasteError] = useState<unknown>(null);
  useEffect(() => {
    if (!host.current) return;
    const editor = new EditorView(host.current, {
      state: EditorState.create({
        schema: editorSchema,
        doc: initial.current.value,
        plugins: plugins(),
      }),
      editable: () => !initial.current.disabled,
      attributes: {
        role: "textbox",
        "aria-label": "章节正文",
        "aria-multiline": "true",
        spellcheck: "true",
      },
      dispatchTransaction(transaction) {
        const next = editor.state.applyTransaction(transaction).state;
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
              "粘贴内容包含表格或图片，当前未接收这些对象。原正文保留；请上传对应PDF原件，或明确改用纯文字。",
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
  }, []);
  useEffect(() => {
    const editor = view.current;
    if (!editor) return;
    editor.setProps({ editable: () => !disabled });
    if (!editor.state.doc.eq(value)) {
      editor.updateState(
        EditorState.create({
          schema: editorSchema,
          doc: value,
          plugins: plugins(),
        }),
      );
      setSelection(editor.state);
      callbacks.current.onTarget(editor.state.selection.$from.parent);
    }
  }, [value, disabled]);
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
        支持段落、标题、列表、粗体和斜体。粘贴按纯文字接收；图片和表格请保留在PDF原件中。编辑器内容需保存确认，再生成正式文件。
      </p>
    </div>
  );
}
