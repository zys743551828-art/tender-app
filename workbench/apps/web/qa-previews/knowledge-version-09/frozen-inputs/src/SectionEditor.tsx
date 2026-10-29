import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import type { Node as EditorNode } from "prosemirror-model";
import { api, ApiError, commandKey, completeCommand } from "./api";
import type {
  AuthoringCapabilities,
  AuthoringDocument,
  AuthoringNode,
  DraftSaved,
  DraftView,
  SaveDraft,
  SectionView,
} from "./contracts";
import { AuthoringPatchPreview } from "./AuthoringPatchPreview";
import { AuthoringReferences } from "./AuthoringReferences";
import { AuthoringHistory } from "./AuthoringHistory";
import { ErrorNotice } from "./components";
import { editorSchema, editorText } from "./editorSchema";
import { authoringStorageKey } from "./editorStorage";
import { SourceEditor } from "./SourceEditor";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import { useSaveQueue } from "./useSaveQueue";
import { useNavigationGuard } from "./navigationGuard";

export type SectionEditorHandle = {
  flush: (requireLocalChoice?: boolean) => Promise<boolean>;
};
type PendingSave = { body: SaveDraft; etag: string; key: string };
type LocalDraft = {
  sectionId: string;
  value: AuthoringDocument;
  draftRevision: number;
  sectionRevision: number;
  schemaDigest: string;
  etag: string;
  pending: PendingSave | null;
};
export type AuthoringHead = {
  draft: DraftView;
  section: SectionView;
  etag: string;
};
export const SectionEditor = forwardRef<
  SectionEditorHandle,
  {
    bidId: string;
    memberId: string;
    draft: DraftView;
    etag: string;
    sectionId: string;
    capabilities: AuthoringCapabilities;
    disabled: boolean;
    onSaved: () => void;
  }
>(function SectionEditor(props, ref) {
  const section = useResource<SectionView>(`/sections/${props.sectionId}`);
  const child = useRef<SectionEditorHandle>(null);
  useImperativeHandle(
    ref,
    () => ({
      flush: (required) =>
        child.current?.flush(required) ?? Promise.resolve(!required),
    }),
    [],
  );
  if (
    section.data &&
    (section.data.id !== props.sectionId ||
      section.data.draft_id !== props.draft.id)
  )
    return (
      <div className="notice error" role="alert">
        章节身份不一致，未打开其他正文。
      </div>
    );
  return (
    <>
      <ResourceState
        {...section}
        hasData={!!section.data}
        onRetry={() => void section.reload()}
      />
      {section.data && (
        <SectionBody
          {...props}
          key={props.sectionId}
          initial={section.data}
          ref={child}
        />
      )}
    </>
  );
});

const SectionBody = forwardRef<
  SectionEditorHandle,
  {
    bidId: string;
    memberId: string;
    draft: DraftView;
    etag: string;
    initial: SectionView;
    capabilities: AuthoringCapabilities;
    disabled: boolean;
    onSaved: () => void;
  }
>(function SectionBody(
  { bidId, memberId, draft, etag, initial, capabilities, disabled, onSaved },
  ref,
) {
  const key = authoringStorageKey(memberId, bidId, `${draft.id}:${initial.id}`);
  const scope = `authoring-save:${memberId}:${bidId}:${draft.id}:${initial.id}`;
  const head = useRef<AuthoringHead>({ draft, section: initial, etag });
  const pending = useRef<PendingSave | null>(null);
  const [value, setValue] = useState(() =>
    editorSchema.nodeFromJSON(initial.content),
  );
  const latest = useRef(value);
  latest.current = value;
  const [recovery, setRecovery] = useState<LocalDraft | null>(() => {
    try {
      const saved = JSON.parse(
        sessionStorage.getItem(key) ?? "null",
      ) as LocalDraft | null;
      return saved?.sectionId === initial.id ? saved : null;
    } catch {
      return null;
    }
  });
  const [conflict, setConflict] = useState<AuthoringHead | null>(null);
  const [notice, setNotice] = useState<unknown>(null);
  const [ack, setAck] = useState({
    section: initial.revision,
    draft: draft.revision,
  });
  const [extensionBusy, setExtensionBusy] = useState(false);
  const [target, setTarget] = useState<EditorNode | null>(null);
  function persist(document: AuthoringDocument) {
    const state = head.current;
    const local: LocalDraft = {
      sectionId: initial.id,
      value: document,
      draftRevision: state.draft.revision,
      sectionRevision: state.section.revision,
      schemaDigest: state.section.schema_digest,
      etag: state.etag,
      pending: pending.current,
    };
    sessionStorage.setItem(key, JSON.stringify(local));
  }
  async function readHead(): Promise<AuthoringHead> {
    const [currentDraft, currentSection] = await Promise.all([
      api<DraftView>(`/bids/${bidId}/drafts/${draft.id}`),
      api<SectionView>(`/sections/${initial.id}`),
    ]);
    if (
      !currentDraft.etag ||
      currentDraft.data.id !== draft.id ||
      currentDraft.data.bid_id !== bidId ||
      currentSection.data.id !== initial.id ||
      currentSection.data.draft_id !== draft.id
    )
      throw new Error(
        "当前正文身份或保存令牌无法核对，已保留本地稿，请刷新重试。",
      );
    return {
      draft: currentDraft.data,
      section: currentSection.data,
      etag: currentDraft.etag,
    };
  }
  const queue = useSaveQueue<AuthoringDocument>(
    async (content) => {
      if (head.current.section.schema_digest !== capabilities.schema_digest)
        throw new Error(
          "编辑格式已更新，未覆盖本地内容。请保留副本并重新核对当前章节。",
        );
      if (!pending.current) {
        const body: SaveDraft = {
          base_draft_revision: head.current.draft.revision,
          changes: [
            {
              section_id: initial.id,
              base_section_revision: head.current.section.revision,
              schema_digest: head.current.section.schema_digest,
              content,
            },
          ],
        };
        pending.current = {
          body,
          etag: head.current.etag,
          key: commandKey(scope, { body, etag: head.current.etag }),
        };
      }
      persist(latest.current.toJSON() as AuthoringDocument);
      try {
        const command = pending.current;
        const saved = await api<DraftSaved>(
          `/bids/${bidId}/drafts/${draft.id}`,
          {
            method: "PATCH",
            body: command.body,
            etag: command.etag,
            key: command.key,
          },
        );
        if (!saved.etag || saved.data.draft_id !== draft.id)
          throw new Error(
            "保存响应缺少可核对身份或条件令牌。内容保留，重试会接续同一保存请求。",
          );
        const current = await api<SectionView>(`/sections/${initial.id}`);
        if (
          current.data.id !== initial.id ||
          current.data.draft_id !== draft.id ||
          !editorSchema
            .nodeFromJSON(current.data.content)
            .eq(editorSchema.nodeFromJSON(content))
        ) {
          setConflict(await readHead());
          throw new ApiError(
            "保存后章节又有并发变化。请比较服务器稿与本地稿，再明确合并。",
            412,
            "SECTION_CHANGED_AFTER_SAVE",
          );
        }
        head.current = {
          etag: saved.etag,
          section: current.data,
          draft: {
            ...head.current.draft,
            revision: saved.data.draft_revision,
            snapshot_id: saved.data.snapshot_id,
          },
        };
        setAck({
          section: current.data.revision,
          draft: saved.data.draft_revision,
        });
        pending.current = null;
        completeCommand(scope);
        setConflict(null);
        if (latest.current.eq(editorSchema.nodeFromJSON(content)))
          sessionStorage.removeItem(key);
        else persist(latest.current.toJSON() as AuthoringDocument);
        onSaved();
      } catch (failure) {
        if (
          failure instanceof ApiError &&
          [409, 412].includes(failure.status)
        ) {
          try {
            setConflict(await readHead());
          } catch {
            /* Retain the original command and error if recovery reads are unavailable. */
          }
        }
        if (
          failure instanceof ApiError &&
          [400, 422].includes(failure.status)
        ) {
          pending.current = null;
          completeCommand(scope);
        }
        persist(latest.current.toJSON() as AuthoringDocument);
        throw failure;
      }
    },
    800,
    (failure) =>
      !(failure instanceof ApiError && [400, 422].includes(failure.status)),
  );
  function change(node: EditorNode) {
    latest.current = node;
    setValue(node);
    const content = node.toJSON() as AuthoringDocument;
    persist(content);
    queue.change(content);
    setNotice(null);
  }
  const guard = useRef(async () => true);
  guard.current = () => queue.flush();
  useNavigationGuard(guard);
  useImperativeHandle(ref, () => ({
    flush: async (required) => {
      if (required && recovery) {
        setNotice(
          new Error(
            "发现尚未处理的本地内容。请先选择恢复，或明确使用服务器稿，再生成版本。",
          ),
        );
        return false;
      }
      return queue.flush();
    },
  }));
  useEffect(() => {
    const unload = (event: BeforeUnloadEvent) => {
      if (queue.isDirty()) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", unload);
    return () => window.removeEventListener("beforeunload", unload);
  }, [queue]);
  async function adoptRemote() {
    try {
      const current = conflict ?? (await readHead());
      if (!queue.discard()) return;
      head.current = current;
      pending.current = null;
      completeCommand(scope);
      latest.current = editorSchema.nodeFromJSON(current.section.content);
      setValue(latest.current);
      setAck({
        section: current.section.revision,
        draft: current.draft.revision,
      });
      setConflict(null);
      setRecovery(null);
      sessionStorage.removeItem(key);
      setNotice(null);
      onSaved();
    } catch (failure) {
      setNotice(failure);
    }
  }
  function restoreLocal() {
    if (!recovery) return;
    try {
      const restored = editorSchema.nodeFromJSON(recovery.value);
      head.current = {
        etag: recovery.etag,
        draft: { ...draft, revision: recovery.draftRevision },
        section: {
          ...initial,
          revision: recovery.sectionRevision,
          schema_digest: recovery.schemaDigest,
        },
      };
      pending.current = recovery.pending;
      latest.current = restored;
      setValue(restored);
      setRecovery(null);
      if (pending.current) {
        queue.change(pending.current.body.changes[0].content);
        void queue.flush();
      }
      queue.change(recovery.value);
    } catch (failure) {
      setNotice(failure);
    }
  }
  async function saveMerged() {
    if (!conflict || !queue.discard()) return;
    head.current = conflict;
    pending.current = null;
    completeCommand(scope);
    setConflict(null);
    const content = latest.current.toJSON() as AuthoringDocument;
    persist(content);
    queue.change(content);
    await queue.flush();
  }
  async function refreshAfterAction() {
    if (!queue.discard())
      throw new Error("还有保存正在进行，请等待保存确认后恢复当前正文。");
    const current = await readHead();
    head.current = current;
    pending.current = null;
    completeCommand(scope);
    latest.current = editorSchema.nodeFromJSON(current.section.content);
    setValue(latest.current);
    setAck({
      section: current.section.revision,
      draft: current.draft.revision,
    });
    setConflict(null);
    sessionStorage.removeItem(key);
    onSaved();
  }
  const status = {
    saved: `已保存 · 章节修订 ${ack.section} · 草稿修订 ${ack.draft}`,
    pending: "本地有修改，等待保存确认…",
    saving: "正在保存，后续输入将继续排队…",
    failed: "保存未完成，本地内容保留",
  }[queue.phase];
  return (
    <div className="section-editor">
      <div className="editor-save-status" role="status">
        <span>{status}</span>
        <button
          className="button secondary"
          disabled={disabled || queue.phase === "saving" || !!recovery}
          onClick={() => void queue.flush()}
        >
          {queue.phase === "failed" ? "重试保存" : "立即保存"}
        </button>
      </div>
      <ErrorNotice error={notice ?? queue.error} />
      {recovery && (
        <div className="notice warning">
          <div>
            <strong>发现此成员的本地待保存内容</strong>
            <p>
              它不是正式保存版本。请比较后选择恢复，或明确保留服务器稿；其他成员的内容不会混入。
            </p>
            <details>
              <summary>比较本地与服务器文本</summary>
              <div className="editor-comparison">
                <pre>{editorText(recovery.value)}</pre>
                <pre>{editorText(initial.content)}</pre>
              </div>
            </details>
            <div className="review-shortcuts">
              <button className="button secondary" onClick={restoreLocal}>
                恢复本地内容并继续保存
              </button>
              <button
                className="text-button"
                onClick={() => void adoptRemote()}
              >
                忽略本地内容，使用服务器稿
              </button>
            </div>
          </div>
        </div>
      )}
      {conflict && (
        <div className="notice warning">
          <div>
            <strong>服务器章节或依据已变化，请人工合并</strong>
            <p>
              本地稿仍可编辑；下面只读显示当前服务器稿。不会自动最后写入覆盖。
            </p>
            <div className="editor-comparison">
              <div>
                <strong>本地待保存</strong>
                <pre>{editorText(value.toJSON())}</pre>
              </div>
              <div>
                <strong>
                  服务器 · 章节修订 {conflict.section.revision}／草稿修订{" "}
                  {conflict.draft.revision}
                </strong>
                <pre>{editorText(conflict.section.content)}</pre>
              </div>
            </div>
            <div className="review-shortcuts">
              <button
                className="button secondary"
                disabled={queue.phase === "saving"}
                onClick={() => void saveMerged()}
              >
                保存已合并的本地稿
              </button>
              <button
                className="text-button"
                disabled={queue.phase === "saving"}
                onClick={() => void adoptRemote()}
              >
                放弃本地待保存，使用服务器稿
              </button>
            </div>
          </div>
        </div>
      )}
      <label className="editor-title-label">
        章节名称
        <input
          value={String(value.attrs.title)}
          maxLength={200}
          disabled={disabled || extensionBusy || !!recovery}
          onChange={(event) =>
            change(
              value.type.create(
                { ...value.attrs, title: event.target.value },
                value.content,
              ),
            )
          }
        />
      </label>
      <SourceEditor
        value={value}
        disabled={disabled || extensionBusy || !!recovery}
        onChange={change}
        onTarget={setTarget}
      />
      <AuthoringReferences
        bidId={bidId}
        content={value.toJSON() as AuthoringDocument}
        disabled={disabled || extensionBusy || !!recovery}
        changeAttrs={(update) => {
          const current = latest.current;
          change(
            current.type.create(
              update(current.attrs as AuthoringDocument["attrs"]),
              current.content,
            ),
          );
        }}
      />
      <AuthoringPatchPreview
        bidId={bidId}
        sectionId={initial.id}
        content={value.toJSON() as AuthoringDocument}
        target={target ? (target.toJSON() as AuthoringNode) : null}
        disabled={disabled || !!recovery}
        flush={queue.flush}
        getHead={() => head.current}
        setBusy={setExtensionBusy}
        refresh={refreshAfterAction}
      />
      <AuthoringHistory
        bidId={bidId}
        sectionId={initial.id}
        disabled={disabled || extensionBusy || !!recovery}
        flush={queue.flush}
        getHead={() => head.current}
        setBusy={setExtensionBusy}
        refresh={refreshAfterAction}
      />
      <p className="small-note">
        {target?.attrs.id
          ? "已定位当前段落，可在修改预览中提出替换。"
          : "选择正文段落后可预览有边界的替换。"}{" "}
        关联 {value.attrs.rule_ids.length} 条要求、
        {value.attrs.source_refs.length} 条来源；文字保存不代表满足要求。
      </p>
    </div>
  );
});
