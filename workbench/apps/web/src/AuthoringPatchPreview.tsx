import { useState } from "react";
import { api } from "./api";
import type {
  AuthoringNode,
  AuthoringPreview,
  AuthoringPreviewRequest,
  DraftSaved,
  DraftView,
} from "./contracts";
import type { AuthoringHead } from "./SectionEditor";
import { ErrorNotice } from "./components";
import { jsonDigest } from "./editorSchema";
import {
  authoringText as editorText,
  richEditorSchema as editorSchema,
  serializeAuthoringNode,
} from "./richEditorSchema";
import type { EditorDocument } from "./richEditorSchema";
import { useCommand } from "./useCommand";
import { TextChangePreview } from "./TextChangePreview";

function findNode(document: EditorDocument, id: string): AuthoringNode | null {
  function visit(nodes: AuthoringNode[]): AuthoringNode | null {
    for (const node of nodes) {
      if ("attrs" in node && node.attrs.id === id) return node;
      if ("content" in node) {
        const found = visit(node.content);
        if (found) return found;
      }
    }
    return null;
  }
  const nodes: AuthoringNode[] = [];
  editorSchema.nodeFromJSON(document).descendants((node) => {
    if (
      (node.type.name === "paragraph" || node.type.name === "heading") &&
      node.attrs.id === id
    )
      nodes.push(serializeAuthoringNode(node) as AuthoringNode);
  });
  return visit(nodes);
}
export function AuthoringPatchPreview({
  bidId,
  sectionId,
  content,
  target,
  disabled,
  flush,
  getHead,
  setBusy,
  refresh,
}: {
  bidId: string;
  sectionId: string;
  content: EditorDocument;
  target: AuthoringNode | null;
  disabled: boolean;
  flush: () => Promise<boolean>;
  getHead: () => AuthoringHead;
  setBusy: (busy: boolean) => void;
  refresh: () => Promise<void>;
}) {
  const [replacement, setReplacement] = useState("");
  const [preview, setPreview] = useState<{
    value: AuthoringPreview;
    etag: string | null;
  } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setLocalBusy] = useState(false);
  const [applied, setApplied] = useState<DraftSaved | null>(null);
  const prepare = useCommand(`patch-preview:${sectionId}`);
  const apply = useCommand(`patch-apply:${preview?.value.action_id ?? "none"}`);
  const textTarget =
    target && (target.type === "paragraph" || target.type === "heading")
      ? target
      : null;
  const stale =
    preview &&
    (!editorSchema
      .nodeFromJSON(preview.value.before)
      .eq(editorSchema.nodeFromJSON(content)) ||
      getHead().draft.revision !== preview.value.base_draft_revision);
  async function createPreview() {
    if (!textTarget || !replacement.trim() || disabled || busy) return;
    setLocalBusy(true);
    setBusy(true);
    setError(null);
    setApplied(null);
    try {
      if (!(await flush())) return;
      const head = getHead();
      const original = findNode(head.section.content, textTarget.attrs.id);
      if (
        !original ||
        (original.type !== "paragraph" && original.type !== "heading")
      )
        throw new Error("原段落已经变化，请重新选择当前段落后预览。");
      const body: AuthoringPreviewRequest = {
        base_section_revision: head.section.revision,
        node_id: original.attrs.id,
        before_digest: await jsonDigest(original),
        replacement: {
          ...original,
          content: [{ type: "text", text: replacement }],
        },
        source_refs: [],
      };
      const result = await prepare.run<AuthoringPreview>(
        `/bids/${bidId}/sections/${sectionId}/patch-previews`,
        body,
        null,
      );
      if (result) {
        const current = await api<DraftView>(
          `/bids/${bidId}/drafts/${head.draft.id}`,
        );
        setPreview({
          value: result.data,
          etag:
            current.data.revision === result.data.base_draft_revision
              ? current.etag
              : null,
        });
      }
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
      setLocalBusy(false);
    }
  }
  async function confirmApply() {
    if (!preview || stale || !preview.etag || disabled || busy) return;
    setLocalBusy(true);
    setBusy(true);
    setError(null);
    try {
      if (!(await flush())) return;
      if (getHead().draft.revision !== preview.value.base_draft_revision)
        throw new Error("基础修订已变化，请重新比较并生成预览。");
      const result = await apply.run<DraftSaved>(
        `/bids/${bidId}/authoring-actions/${preview.value.action_id}/apply`,
        {},
        preview.etag,
      );
      if (result) {
        await refresh();
        setApplied(result.data);
        setPreview(null);
        setReplacement("");
      }
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
      setLocalBusy(false);
    }
  }
  return (
    <details className="coverage-details">
      <summary>手动段落修改预览</summary>
      <div className="manual-patch">
        <p className="small-note">
          选择正文中的一个段落或标题，提出有边界的替换。这里的手动预览不调用模型；明确应用后追加修订，风险仍须用新稿复检。
        </p>
        {!textTarget && (
          <p className="small-note">请先点击需要修改的正文段落。</p>
        )}
        <label>
          替换后的段落文字
          <textarea
            value={replacement}
            rows={4}
            maxLength={50000}
            disabled={disabled || busy}
            onChange={(event) => setReplacement(event.target.value)}
          />
        </label>
        <button
          className="button secondary"
          disabled={!textTarget || !replacement.trim() || disabled || busy}
          onClick={() => void createPreview()}
        >
          {busy ? "正在核对段落边界…" : "预览这次段落替换"}
        </button>
        <ErrorNotice error={error ?? apply.error ?? prepare.error} />
        {stale && (
          <div className="notice warning">
            正文或草稿基准已变化，旧预览保留供比较，不能继续应用。请重新预览。
          </div>
        )}
        {preview && (
          <>
            <TextChangePreview
              before={editorText(preview.value.before)}
              after={editorText(preview.value.after)}
              beforeLabel={`修改前 · 草稿修订 ${preview.value.base_draft_revision}`}
            />
            <p className="small-note">
              仅改变这次段落及明确关联的来源；规则、事实、来源效力仍由服务端在应用时再次核验。
            </p>
            <div className="review-shortcuts">
              <button
                className="button primary"
                disabled={!!stale || !preview.etag || disabled || busy}
                onClick={() => void confirmApply()}
              >
                {busy ? "正在应用并核对保存结果…" : "应用这次修改并保存"}
              </button>
              <button
                className="text-button"
                disabled={busy}
                onClick={() => setPreview(null)}
              >
                放弃此预览
              </button>
            </div>
          </>
        )}
        {applied && (
          <p className="inline-success" role="status">
            已追加草稿修订 {applied.draft_revision}
            。原稿和历史保留；应用修改不表示已解决风险。
          </p>
        )}
      </div>
    </details>
  );
}
