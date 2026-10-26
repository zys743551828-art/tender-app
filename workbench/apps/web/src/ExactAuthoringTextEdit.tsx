import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { AuthoringDocument, AuthoringExactDraftStatus } from "./contracts";
import { ErrorNotice } from "./components";
import { jsonDigest } from "./editorSchema";
import {
  editableTextNodes,
  textEditChanges,
  type ExactTextEditRequest,
  readTextEditCapabilities,
  verifyTextEditBase,
  type ExactTextEditBase,
  type ExactTextEditScope,
} from "./authoringExactTextEditProtocol";
import { useExactAuthoringTextEdit } from "./useExactAuthoringTextEdit";
import { useNavigationGuard } from "./navigationGuard";

export function ExactAuthoringTextEdit(
  props: Parameters<typeof ExactAuthoringTextEditor>[0],
) {
  return (
    <ExactAuthoringTextEditor
      key={`${props.memberId}:${props.bidId}:${props.draftId}:${props.sectionId ?? ""}`}
      {...props}
    />
  );
}
function ExactAuthoringTextEditor({
  memberId,
  bidId,
  draftId,
  sectionId,
  status,
  etag,
  disabled,
  onSaved,
  onEditingChange,
}: ExactTextEditScope & {
  sectionId: string | undefined;
  status: AuthoringExactDraftStatus | null;
  etag: string;
  disabled: boolean;
  onSaved: () => Promise<unknown>;
  onEditingChange: (value: boolean) => void;
}) {
  const command = useExactAuthoringTextEdit({ memberId, bidId, draftId });
  const [loaded, setLoaded] = useState<{
    identity: string;
    base: ExactTextEditBase | null;
    available: boolean;
    multi: boolean;
  } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [refresh, setRefresh] = useState(0);
  const [editing, setEditing] = useState<ExactTextEditBase | null>(null);
  const [nodeId, setNodeId] = useState("");
  const [replacement, setReplacement] = useState("");
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [multi, setMulti] = useState(false);
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [savedMessage, setSavedMessage] = useState("");
  const binding = status?.exact_sections.find(
    (s) => s.section_id === sectionId,
  );
  const identity = `${status?.snapshot_id ?? ""}:${binding?.qualification_digest ?? ""}:${sectionId ?? ""}`;
  const base = loaded?.identity === identity ? loaded.base : null;
  const available = loaded?.identity === identity && loaded.available;
  const dirty = !!editing;
  const unsettled =
    dirty ||
    command.pending ||
    command.conflict ||
    command.busy ||
    command.blocked;
  const guard = useRef(async () => !unsettled);
  guard.current = async () => !unsettled;
  useNavigationGuard(guard);
  useEffect(() => {
    onEditingChange(unsettled);
    return () => onEditingChange(false);
  }, [unsettled, onEditingChange]);
  useEffect(() => {
    if (!unsettled) return;
    const leave = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", leave);
    return () => window.removeEventListener("beforeunload", leave);
  }, [unsettled]);
  useEffect(() => {
    let active = true;
    if (!status || !binding || !sectionId) return;
    const scope = { memberId, bidId, draftId };
    void api<unknown>("/authoring/exact-text-edit-capabilities")
      .then(async (caps) => {
        const capability = readTextEditCapabilities(caps.data);
        if (!active) return;
        if (!capability.available) {
          setLoaded({ identity, base: null, available: false, multi: false });
          setError(null);
          return;
        }
        const [section, qualification] = await Promise.all([
          api<unknown>(`/sections/${sectionId}`),
          api<unknown>(
            `/bids/${bidId}/authoring/section-revisions/${binding.section_revision_id}/exact-qualification`,
          ),
        ]);
        const verified = await verifyTextEditBase(
          { status, section: section.data, qualification: qualification.data },
          scope,
        );
        if (active) {
          setLoaded({
            identity,
            base: verified,
            available: capability.available,
            multi:
              capability.protocol ===
              "authoring-exact-text-edit-capabilities/2",
          });
          setError(null);
        }
      })
      .catch((failure) => {
        if (active) {
          setLoaded(null);
          setError(failure);
        }
      });
    return () => {
      active = false;
    };
  }, [memberId, bidId, draftId, sectionId, identity, status, binding, refresh]);
  const nodes = editing
    ? editableTextNodes(editing.section.content as AuthoringDocument)
    : [];
  const node = nodes.find((n) => n.id === nodeId);
  const changes = Object.entries({
    ...texts,
    ...(nodeId ? { [nodeId]: replacement } : {}),
  }).filter(([id, text]) => nodes.find((n) => n.id === id)?.text !== text);
  const validChanges =
    changes.length > 0 &&
    changes.length <= (multi ? 20 : 1) &&
    changes.every(([id]) => nodes.some((n) => n.id === id)) &&
    changes.reduce((total, [, text]) => total + Array.from(text).length, 0) <=
      20000;
  const canStart =
    !disabled &&
    available &&
    !!base &&
    etag === `"draft:${draftId}:${base.status.draft_revision}"` &&
    !unsettled;
  async function completed(result: Awaited<ReturnType<typeof command.retry>>) {
    if (!result) return;
    setEditing(null);
    setConfirmed(false);
    setSavedMessage(
      `人工文字修订已保存为草稿修订 ${result.data.draft_revision}，原稿及来源链均已保留。`,
    );
    try {
      await onSaved();
      setRefresh((n) => n + 1);
    } catch (failure) {
      setError(failure);
    }
  }
  async function save() {
    if (
      !editing ||
      !node ||
      !confirmed ||
      disabled ||
      command.busy ||
      command.pending ||
      command.conflict ||
      command.blocked
    )
      return;
    setError(null);
    try {
      if (!validChanges) return;
      const edits = await Promise.all(
        changes.map(async ([id, text]) => ({
          node_id: id,
          before_node_digest: await jsonDigest(
            nodes.find((n) => n.id === id)!.node,
          ),
          replacement_text: text,
        })),
      );
      const common = {
        base_draft_revision: editing.status.draft_revision,
        section_revision_id: editing.qualification.manifest.section_revision_id,
        reason,
      };
      const body: ExactTextEditRequest =
        edits.length === 1
          ? { ...common, ...edits[0] }
          : { ...common, protocol: "authoring-exact-multi-text-edit/1", edits };
      await completed(
        await command.run(
          editing,
          body,
          `"draft:${draftId}:${editing.status.draft_revision}"`,
        ),
      );
    } catch (failure) {
      setError(failure);
    }
  }
  function begin() {
    if (
      !canStart ||
      !base ||
      etag !== `"draft:${draftId}:${base.status.draft_revision}"`
    )
      return;
    const first = editableTextNodes(
      base.section.content as AuthoringDocument,
    )[0];
    if (!first) {
      setError(new Error("本章暂无可单独修订的纯文字段落或标题。"));
      return;
    }
    setEditing(base);
    setMulti(!!loaded?.multi);
    setTexts({});
    setNodeId(first.id);
    setReplacement(first.text);
    setReason("");
    setConfirmed(false);
    setSavedMessage("");
  }
  async function reopenConflict() {
    if (!base) return;
    const old = await command.acknowledgeConflict(base);
    if (!old) return;
    setEditing(base);
    const edits = textEditChanges(old);
    setMulti("edits" in old);
    setTexts(
      Object.fromEntries(
        edits.map((edit) => [edit.node_id, edit.replacement_text]),
      ),
    );
    setNodeId(edits[0].node_id);
    setReplacement(edits[0].replacement_text);
    setReason(old.reason);
    setConfirmed(false);
  }
  return (
    <section className="panel" aria-label="固定来源文字修订">
      <h3>固定来源文字修订</h3>
      <p className="small-note">
        可修改现有纯文字段落或标题；服务支持时可在同章选择多个段落，一次原子保存新修订，保留引用、规则和原稿，并记为人工修改；正文正确性仍需人工核对。
      </p>
      <ErrorNotice error={error} onRetry={() => setRefresh((n) => n + 1)} />
      <ErrorNotice error={command.error} />
      {savedMessage && (
        <p role="status" className="notice success">
          {savedMessage}
        </p>
      )}
      {command.pending && (
        <div className="notice warning" role="status">
          <p>
            上次文字修订尚未取得已核验回执。原文字、原保存条件和操作键已保留。
          </p>
          {command.original && (
            <label>
              待核对的原请求文字
              <textarea
                readOnly
                rows={4}
                value={textEditChanges(command.original.body)
                  .map((edit) => `${edit.node_id}: ${edit.replacement_text}`)
                  .join("\n\n")}
              />
            </label>
          )}
          <button
            className="button"
            disabled={command.busy || command.blocked}
            onClick={() => void command.retry().then(completed)}
          >
            查询并重试原文字修订
          </button>
        </div>
      )}
      {command.conflict && (
        <div className="notice warning" role="status">
          <p>
            原保存基准已变化，文字仍保留。请先重新读取当前草稿，再核对差异并重新确认。
          </p>
          <button
            className="button secondary"
            disabled={command.busy || command.blocked}
            onClick={() =>
              void onSaved()
                .then(() => setRefresh((n) => n + 1))
                .catch(setError)
            }
          >
            重新读取当前草稿
          </button>
          <button
            className="button secondary"
            disabled={
              !base ||
              !command.original ||
              base.status.draft_revision <=
                command.original.body.base_draft_revision ||
              command.busy ||
              command.blocked
            }
            onClick={() => void reopenConflict()}
          >
            按当前原稿重新核对保留文字
          </button>
        </div>
      )}
      {!editing && !command.pending && !command.conflict && (
        <>
          <button
            className="button secondary"
            disabled={!canStart}
            onClick={begin}
          >
            修改本章固定来源文字
          </button>
          {!available && (
            <p className="small-note">
              {loaded?.identity === identity
                ? "当前服务未开放固定来源文字修订。"
                : "正在核对本章原稿与来源资格，核验后可开始文字修订。"}
            </p>
          )}
        </>
      )}
      {editing && (
        <div className="form-stack">
          <label>
            修改段落或标题
            <select
              value={nodeId}
              disabled={
                command.busy ||
                command.pending ||
                command.conflict ||
                command.blocked ||
                (!multi && !!node && replacement !== node.text)
              }
              onChange={(event) => {
                const selected = nodes.find((n) => n.id === event.target.value);
                setNodeId(event.target.value);
                setReplacement(
                  texts[event.target.value] ?? selected?.text ?? "",
                );
                setConfirmed(false);
              }}
            >
              {nodes.map((n, index) => (
                <option key={n.id} value={n.id}>
                  {index + 1}. {n.text.slice(0, 80) || "空段落"}
                </option>
              ))}
            </select>
          </label>
          {!node && (
            <p className="notice warning" role="status">
              原段落已不在本章，请选择现有段落并核对保留文字。
            </p>
          )}
          <label>
            原文字
            <textarea readOnly rows={4} value={node?.text ?? ""} />
          </label>
          <label>
            修改后的文字
            <textarea
              rows={6}
              value={replacement}
              disabled={
                command.busy ||
                command.pending ||
                command.conflict ||
                command.blocked
              }
              onChange={(event) => {
                setReplacement(event.target.value);
                setTexts((previous) => ({
                  ...previous,
                  [nodeId]: event.target.value,
                }));
                setConfirmed(false);
              }}
            />
          </label>
          {multi && (
            <div>
              <p role="status" className="small-note">
                本次已修改 {changes.length} 个节点（最多 20 个，合计 20000
                字符），切换段落保留修改；确认后全部成功或全部不改。
              </p>
              {changes.map(([id, text], index) => (
                <details key={id}>
                  <summary>
                    待保存节点 {index + 1}：
                    {nodes.find((n) => n.id === id)?.text.slice(0, 60) ||
                      "原节点已不存在或为空"}
                  </summary>
                  <pre className="small-note">{text}</pre>
                  <button
                    type="button"
                    className="button secondary"
                    disabled={
                      command.busy ||
                      command.pending ||
                      command.conflict ||
                      command.blocked
                    }
                    onClick={() => {
                      setTexts((previous) => {
                        const next = { ...previous };
                        delete next[id];
                        return next;
                      });
                      if (nodeId === id) {
                        const next = nodes.find((n) => n.id === id) ?? nodes[0];
                        setNodeId(next?.id ?? "");
                        setReplacement(
                          next
                            ? next.id === id
                              ? next.text
                              : (texts[next.id] ?? next.text)
                            : "",
                        );
                      }
                      setConfirmed(false);
                    }}
                  >
                    撤销节点 {index + 1} 的修改
                  </button>
                </details>
              ))}
            </div>
          )}
          <label>
            修订说明
            <input
              value={reason}
              maxLength={1000}
              disabled={
                command.busy ||
                command.pending ||
                command.conflict ||
                command.blocked
              }
              onChange={(event) => {
                setReason(event.target.value);
                setConfirmed(false);
              }}
            />
          </label>
          <p className="small-note">
            保留 {editing.section.content.attrs.source_refs.length} 条来源引用、
            {editing.section.content.attrs.rule_ids.length}{" "}
            条规则关联。此操作不改变章节顺序、格式或引用。
          </p>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={confirmed}
              disabled={
                command.busy ||
                command.pending ||
                command.conflict ||
                command.blocked
              }
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            我已核对文字与原来源，确认保存为人工修订
          </label>
          <div className="button-row">
            <button
              className="button"
              disabled={
                disabled ||
                !confirmed ||
                !node ||
                !validChanges ||
                !reason.trim() ||
                Array.from(replacement).length > 20000 ||
                command.busy ||
                command.pending ||
                command.conflict ||
                command.blocked
              }
              onClick={() => void save()}
            >
              {command.busy ? "正在保存并核对…" : "确认保存人工修订"}
            </button>
            <button
              className="button secondary"
              disabled={
                command.busy ||
                command.pending ||
                command.conflict ||
                command.blocked
              }
              onClick={() => {
                setEditing(null);
                setConfirmed(false);
              }}
            >
              取消未保存修改
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
