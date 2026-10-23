import { AuthoringStructure } from "./AuthoringStructure";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import type { ApiResult } from "./api";
import type {
  AuthoringCapabilities,
  AuthoringRichCapabilities,
  AuthoringDraftPage,
  CreateDraftRequest,
  DraftView,
} from "./contracts";
import { ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import { useAuthoringExactDraft } from "./useAuthoringExactDraft";
import { useCommand } from "./useCommand";
import { SectionEditor } from "./SectionEditor";
import { AuthoringBuilds } from "./AuthoringBuilds";
import { AuthoringWordImport } from "./AuthoringWordImport";
import { AuthoringGenerationBatch } from "./AuthoringGenerationBatch";
import type { SectionEditorHandle } from "./SectionEditor";
import { useAuxiliaryFocus } from "./useAuxiliaryFocus";
import { useElementWidth } from "./useElementWidth";
import {
  announceWorkspaceAuxiliary,
  listenWorkspaceAuxiliary,
} from "./workspaceAuxiliary";
import "./AuthoringLayout.css";

export function AuthoringPanel({
  bidId,
  memberId,
  projectTitle,
  draftId,
  onOpenDraft,
  disabled = false,
  onPackages,
}: {
  bidId: string;
  memberId: string;
  projectTitle: string;
  draftId: string | null;
  onOpenDraft: (id: string) => void;
  disabled?: boolean;
  onPackages?: () => void;
}) {
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const capabilities = useResource<AuthoringCapabilities>(
    "/authoring/capabilities",
  );
  const richCapabilities = useResource<AuthoringRichCapabilities>(
    supportsApi("GET", "/authoring/rich-capabilities")
      ? "/authoring/rich-capabilities"
      : null,
  );
  const drafts = useResource<AuthoringDraftPage>(`/bids/${bidId}/drafts`);
  const [more, setMore] = useState<AuthoringDraftPage[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [title, setTitle] = useState("");
  const [managementOpen, setManagementOpen] = useState(!draftId);
  useEffect(() => setManagementOpen(!draftId), [draftId]);
  const command = useCommand(`draft:create:${memberId}:${bidId}`);
  const items = [
    ...new Map(
      [
        ...(drafts.data?.items ?? []),
        ...more.flatMap((page) => page.items),
      ].map((draft) => [draft.id, draft]),
    ).values(),
  ];
  const last = more.at(-1) ?? drafts.data;
  const positionKey = `tender:authoring:${memberId}:${bidId}:selected-draft`;
  useEffect(() => {
    try {
      if (draftId) {
        sessionStorage.setItem(positionKey, draftId);
        return;
      }
      const saved = sessionStorage.getItem(positionKey);
      if (saved && drafts.data?.items.some((item) => item.id === saved))
        onOpenDraft(saved);
    } catch {
      // Navigation position is optional; it cannot block server-backed drafts.
    }
  }, [draftId, drafts.data, onOpenDraft, positionKey]);
  async function create() {
    if (disabled) return;
    const body: CreateDraftRequest = {
      title: title.trim(),
      outline_template_version_id: null,
    };
    const result = await command.run<DraftView>(
      `/bids/${bidId}/drafts`,
      body,
      null,
    );
    if (result && active.current) {
      setTitle("");
      void drafts.reload();
      onOpenDraft(result.data.id);
    }
  }
  async function next() {
    if (!last?.next_cursor || loadingMore) return;
    setLoadingMore(true);
    setError(null);
    try {
      const { data } = await api<AuthoringDraftPage>(
        `/bids/${bidId}/drafts?cursor=${encodeURIComponent(last.next_cursor)}`,
      );
      setMore((old) => [...old, data]);
    } catch (failure) {
      setError(failure);
    } finally {
      setLoadingMore(false);
    }
  }
  return (
    <div className="authoring-workspace">
      <section className="panel authoring-draft-management">
        <details
          open={managementOpen}
          onToggle={(event) => setManagementOpen(event.currentTarget.open)}
        >
          <summary className="authoring-management-summary">
            <span>
              <strong>
                {draftId
                  ? (items.find((item) => item.id === draftId)?.title ??
                    "当前正文草稿")
                  : "选择或创建正文草稿"}
              </strong>
            </span>
            <span>草稿管理与新建</span>
          </summary>
          <div className="authoring-management-content">
            <p className="small-note">
              已有稿件可以继续走PDF资料评审；在这里人工编写章节，生成固定版本后再核对。无需先配置模板或企业事实库。
            </p>
            <ResourceState
              {...drafts}
              hasData={!!drafts.data}
              onRetry={() => void drafts.reload()}
            />
            <ErrorNotice error={command.error ?? error} />
            {capabilities.data && (
              <>
                <div className="draft-picker">
                  <label>
                    打开已有正文草稿
                    <select
                      aria-label="打开已有正文草稿"
                      value={draftId ?? ""}
                      onChange={(event) => {
                        if (event.target.value) onOpenDraft(event.target.value);
                      }}
                    >
                      <option value="">选择正文草稿</option>
                      {items.map((item) => (
                        <option value={item.id} key={item.id}>
                          {item.title} · 草稿修订 {item.revision}
                        </option>
                      ))}
                    </select>
                  </label>
                  {last?.next_cursor && (
                    <button
                      className="text-button"
                      disabled={loadingMore}
                      onClick={() => void next()}
                    >
                      {loadingMore ? "正在读取更多草稿…" : "加载更多草稿"}
                    </button>
                  )}
                </div>
                <form
                  className="create-draft-form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void create();
                  }}
                >
                  <label>
                    新正文草稿名称
                    <input
                      value={title}
                      disabled={disabled || command.busy}
                      required
                      maxLength={200}
                      placeholder="例如：技术投标文件"
                      onChange={(event) => setTitle(event.target.value)}
                    />
                  </label>
                  <button
                    className="button secondary"
                    disabled={
                      disabled || command.busy || !title.trim() || !memberId
                    }
                  >
                    {command.busy ? "正在创建…" : "创建正文草稿"}
                  </button>
                </form>
                {disabled && (
                  <p className="notice neutral">
                    当前项目已结束或归档，可查看草稿与生成历史；新编写、构建和文件采用已停止。
                  </p>
                )}
                <p className="small-note">
                  支持文字、标题、列表、章节目录、编写计划与分别固定的目录和版式模板。
                  {richCapabilities.data
                    ? "表格和已登记图片可在章节中明确插入、编辑和保存；构建会分别记录实际目录、章页范围及未核验项。"
                    : "表格和图片编辑能力尚未就绪，请保留原稿。"}
                  {supportsApi("GET", "/authoring/word-import-capabilities")
                    ? "外部Word须先预览结构和转换损失，再明确追加新章节；实际支持范围见Word导入区。"
                    : "外部Word结构导入尚未开放，原Word可先保存或转PDF核对。"}
                </p>
                <ResourceState
                  {...richCapabilities}
                  hasData={!!richCapabilities.data}
                  onRetry={() => void richCapabilities.reload()}
                />
              </>
            )}
          </div>
        </details>
        <ResourceState
          {...capabilities}
          hasData={!!capabilities.data}
          onRetry={() => void capabilities.reload()}
        />
      </section>
      {draftId && capabilities.data && (
        <DraftEditor
          key={`${memberId}:${bidId}:${draftId}`}
          bidId={bidId}
          memberId={memberId}
          draftId={draftId}
          capabilities={capabilities.data}
          richCapabilities={richCapabilities.data}
          projectTitle={projectTitle}
          disabled={disabled}
          onPackages={onPackages}
        />
      )}
    </div>
  );
}

function DraftEditor({
  bidId,
  memberId,
  draftId,
  capabilities,
  richCapabilities,
  projectTitle,
  disabled,
  onPackages,
}: {
  bidId: string;
  memberId: string;
  draftId: string;
  capabilities: AuthoringCapabilities;
  richCapabilities?: AuthoringRichCapabilities;
  projectTitle: string;
  disabled: boolean;
  onPackages?: () => void;
}) {
  const draft = useResource<DraftView>(`/bids/${bidId}/drafts/${draftId}`);
  const [fresh, setFresh] = useState<ApiResult<DraftView> | null>(null);
  const current =
    fresh && fresh.data.revision >= (draft.data?.revision ?? 0)
      ? fresh
      : { data: draft.data, etag: draft.etag };
  const view = current.data;
  const exact = useAuthoringExactDraft(bidId, draftId, view);
  async function reloadHead() {
    const result = await api<DraftView>(`/bids/${bidId}/drafts/${draftId}`);
    if (
      result.data.id !== draftId ||
      result.data.bid_id !== bidId ||
      !result.etag
    )
      throw new Error("无法核对草稿当前身份与保存令牌，请重试。");
    setFresh((old) =>
      !old || result.data.revision >= old.data.revision ? result : old,
    );
    return result;
  }
  const sectionPositionKey = `tender:authoring:${memberId}:${bidId}:${draftId}:selected-section`;
  const [selected, setSelected] = useState<string | null>(() => {
    try {
      return sessionStorage.getItem(sectionPositionKey);
    } catch {
      return null;
    }
  });
  const [switching, setSwitching] = useState(false);
  const [building, setBuilding] = useState(false);
  const [structureBusy, setStructureBusy] = useState(false);
  const [importing, setImporting] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const editor = useRef<SectionEditorHandle>(null);
  const writingRef = useRef<HTMLElement>(null);
  const columns = useRef<HTMLDivElement>(null);
  const directoryPanel = useRef<HTMLElement>(null);
  const directoryClose = useRef<HTMLButtonElement>(null);
  const [directoryOpen, setDirectoryOpen] = useState(false);
  const closeDirectory = useCallback(() => setDirectoryOpen(false), []);
  const compactDirectory = useElementWidth(columns, !!view) < 860;
  useAuxiliaryFocus({
    open: directoryOpen,
    modal: compactDirectory,
    panel: directoryPanel,
    initialFocus: directoryClose,
    onClose: closeDirectory,
  });
  useEffect(
    () => listenWorkspaceAuxiliary(bidId, "directory", closeDirectory),
    [bidId, closeDirectory],
  );
  function continueWriting() {
    setDirectoryOpen(false);
    requestAnimationFrame(() => {
      (
        writingRef.current?.querySelector<HTMLElement>(
          '[aria-label="章节正文"]',
        ) ?? writingRef.current
      )?.focus({ preventScroll: true });
    });
  }
  const sectionId = view?.sections.some((section) => section.id === selected)
    ? selected!
    : view?.sections[0]?.id;
  async function choose(id: string) {
    if (switching || building || importing || generating || structureBusy)
      return;
    if (id === sectionId) {
      continueWriting();
      return;
    }
    setSwitching(true);
    setError(null);
    try {
      if (!editor.current || (await editor.current.flush())) {
        await reloadHead();
        setSelected(id);
        sessionStorage.setItem(sectionPositionKey, id);
        continueWriting();
      } else {
        setError(
          new Error(
            "本章保存尚未确认，未切换章节。本地正文仍保留，请收起目录处理保存或恢复提示。",
          ),
        );
      }
    } catch (failure) {
      setError(failure);
    } finally {
      setSwitching(false);
    }
  }
  if (view && (view.id !== draftId || view.bid_id !== bidId))
    return (
      <div className="notice error" role="alert">
        正文草稿项目身份不一致，未打开其他项目内容。
      </div>
    );
  return (
    <>
      <ResourceState
        {...draft}
        hasData={!!draft.data}
        onRetry={() => void draft.reload()}
      />
      {!directoryOpen && <ErrorNotice error={error} />}
      <ErrorNotice error={exact.error} onRetry={() => void exact.refresh()} />
      {exact.unavailable && (
        <p className="notice warning" role="status">
          当前服务尚不能核对本稿的保存来源资格，原稿保留，暂不进行新编辑或构建。
        </p>
      )}
      {exact.checking && (
        <p role="status" className="small-note">
          正在核对保存快照及本稿的来源资格…
        </p>
      )}
      {exact.hasExact && (
        <div className="notice neutral" role="status">
          <p>
            这份草稿含固定整包候选采纳后的正文修订。普通编辑、目录修改和导入暂不可用，原稿与来源关系保持完整。
          </p>
          <p>
            {exact.status?.build_available && !exact.buildBlocked
              ? `已核验草稿修订 ${view?.revision} 的构建能力；可在下方明确生成文件，再选择输出入包。`
              : "本稿的构建资格尚未就绪，原采纳结果和历史仍可核对。"}
          </p>
        </div>
      )}
      {view && current.etag && (
        <>
          <div className="authoring-task-toolbar">
            <button
              className="button secondary"
              aria-expanded={directoryOpen}
              aria-controls="authoring-directory"
              onClick={() => {
                if (directoryOpen) closeDirectory();
                else {
                  announceWorkspaceAuxiliary(bidId, "directory");
                  setDirectoryOpen(true);
                }
              }}
            >
              章节目录与计划
            </button>
            <span>
              {view.sections.find((section) => section.id === sectionId)
                ?.title ?? "请选择章节"}
            </span>
            {structureBusy && (
              <span role="status">目录操作待确认或处理中，打开目录继续。</span>
            )}
          </div>
          <div
            ref={columns}
            className={`authoring-columns authoring-columns--body-first${directoryOpen && !compactDirectory ? " authoring-columns--directory" : ""}`}
          >
            <aside
              id="authoring-directory"
              ref={directoryPanel}
              hidden={!directoryOpen}
              className={`chapter-outline panel authoring-directory${compactDirectory ? " authoring-directory--compact" : ""}`}
              role={compactDirectory ? "dialog" : "complementary"}
              aria-modal={directoryOpen && compactDirectory ? true : undefined}
              aria-label="章节目录与编写计划"
              tabIndex={-1}
            >
              <header className="authoring-directory-heading">
                <strong>目录与编写计划</strong>
                <button
                  ref={directoryClose}
                  className="button secondary"
                  onClick={closeDirectory}
                >
                  收起目录
                </button>
              </header>
              <ErrorNotice error={error} />
              <AuthoringStructure
                bidId={bidId}
                memberId={memberId}
                draftId={draftId}
                draftRevision={view.revision}
                sectionId={sectionId}
                disabled={
                  disabled || switching || building || importing || generating
                }
                readOnly={exact.ordinaryEditBlocked}
                onChoose={choose}
                onContinue={continueWriting}
                onBusy={setStructureBusy}
                onChanged={reloadHead}
                prepare={async () => {
                  if (editor.current && !(await editor.current.flush()))
                    return null;
                  return reloadHead();
                }}
              />
            </aside>
            <section
              ref={writingRef}
              className="chapter-writing panel"
              aria-label="正文编写"
              tabIndex={-1}
              inert={directoryOpen && compactDirectory}
            >
              {sectionId ? (
                <SectionEditor
                  key={sectionId}
                  ref={editor}
                  bidId={bidId}
                  memberId={memberId}
                  draft={view}
                  etag={current.etag}
                  sectionId={sectionId}
                  capabilities={capabilities}
                  richCapabilities={richCapabilities}
                  disabled={
                    disabled ||
                    switching ||
                    building ||
                    structureBusy ||
                    importing ||
                    generating
                  }
                  readOnly={exact.ordinaryEditBlocked}
                  onSaved={() => void reloadHead().catch(setError)}
                />
              ) : (
                <p className="small-empty">
                  当前草稿没有章节，可先新增一个章节。
                </p>
              )}
            </section>
          </div>
        </>
      )}
      {view &&
        current.etag &&
        supportsApi("GET", "/authoring/generation-batch-capabilities") && (
          <AuthoringGenerationBatch
            bidId={bidId}
            memberId={memberId}
            draft={view}
            disabled={
              disabled ||
              exact.ordinaryEditBlocked ||
              switching ||
              building ||
              structureBusy ||
              importing
            }
            onChanged={reloadHead}
            onBusy={setGenerating}
            prepare={async () => {
              if (
                sectionId &&
                (!editor.current || !(await editor.current.flush(true)))
              )
                return null;
              return reloadHead();
            }}
          />
        )}
      {view &&
        current.etag &&
        supportsApi("GET", "/authoring/word-import-capabilities") && (
          <AuthoringWordImport
            bidId={bidId}
            memberId={memberId}
            draftId={draftId}
            draftRevision={view.revision}
            disabled={
              disabled ||
              exact.ordinaryEditBlocked ||
              switching ||
              building ||
              structureBusy ||
              generating
            }
            onChanged={reloadHead}
            onBusy={setImporting}
            onPackages={onPackages}
            prepare={async () => {
              if (
                sectionId &&
                (!editor.current || !(await editor.current.flush(true)))
              )
                return null;
              return reloadHead();
            }}
          />
        )}
      {view && current.etag && (
        <AuthoringBuilds
          bidId={bidId}
          memberId={memberId}
          draftId={draftId}
          capabilities={capabilities}
          richCapabilities={richCapabilities}
          projectTitle={projectTitle}
          disabled={
            disabled ||
            exact.buildBlocked ||
            switching ||
            structureBusy ||
            importing ||
            generating
          }
          onPackages={onPackages}
          setBusy={setBuilding}
          fixedRevision={
            exact.status?.exact_sections.length
              ? {
                  draft_id: draftId,
                  draft_revision: exact.status.draft_revision,
                  snapshot_id: exact.status.snapshot_id,
                  snapshot_digest: exact.status.snapshot_digest,
                }
              : undefined
          }
          prepare={async () => {
            if (
              sectionId &&
              (!editor.current || !(await editor.current.flush(true)))
            )
              return null;
            return reloadHead();
          }}
        />
      )}
    </>
  );
}
