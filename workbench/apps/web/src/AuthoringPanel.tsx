import { AuthoringStructure } from "./AuthoringStructure";
import { useEffect, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import type { ApiResult } from "./api";
import type {
  AuthoringCapabilities,
  AuthoringRichCapabilities,
  AuthoringDraftPage,
  CreateDraftRequest,
  DraftView,
} from "./contracts";
import { Badge, ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import { useCommand } from "./useCommand";
import { SectionEditor } from "./SectionEditor";
import { AuthoringBuilds } from "./AuthoringBuilds";
import { AuthoringWordImport } from "./AuthoringWordImport";
import type { SectionEditorHandle } from "./SectionEditor";

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
      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>按需编制正文</h2>
            <p className="muted">
              已有稿件可以继续走PDF资料评审；在这里人工编写章节，生成固定版本后再核对。无需先配置模板或企业事实库。
            </p>
          </div>
          <Badge>可选工作面</Badge>
        </div>
        <ResourceState
          {...capabilities}
          hasData={!!capabilities.data}
          onRetry={() => void capabilities.reload()}
        />
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
  const [error, setError] = useState<unknown>(null);
  const editor = useRef<SectionEditorHandle>(null);
  const writingRef = useRef<HTMLElement>(null);
  const sectionId = view?.sections.some((section) => section.id === selected)
    ? selected!
    : view?.sections[0]?.id;
  async function choose(id: string) {
    if (switching || building || importing || id === sectionId) return;
    setSwitching(true);
    try {
      if (!editor.current || (await editor.current.flush())) {
        await reloadHead();
        setSelected(id);
        sessionStorage.setItem(sectionPositionKey, id);
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
      <ErrorNotice error={error} />
      {view && current.etag && (
        <div className="authoring-columns">
          <aside className="chapter-outline panel" aria-label="章节目录">
            <AuthoringStructure
              bidId={bidId}
              memberId={memberId}
              draftId={draftId}
              draftRevision={view.revision}
              sectionId={sectionId}
              disabled={disabled || switching || building || importing}
              onChoose={choose}
              onContinue={() => {
                writingRef.current?.scrollIntoView({ block: "start" });
                writingRef.current
                  ?.querySelector<HTMLElement>('[aria-label="章节正文"]')
                  ?.focus({ preventScroll: true });
              }}
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
                  importing
                }
                onSaved={() => void reloadHead().catch(setError)}
              />
            ) : (
              <p className="small-empty">
                当前草稿没有章节，可先新增一个章节。
              </p>
            )}
          </section>
        </div>
      )}
      {view &&
        current.etag &&
        supportsApi("GET", "/authoring/word-import-capabilities") && (
          <AuthoringWordImport
            bidId={bidId}
            memberId={memberId}
            draftId={draftId}
            draftRevision={view.revision}
            disabled={disabled || switching || building || structureBusy}
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
          disabled={disabled || switching || structureBusy || importing}
          onPackages={onPackages}
          setBusy={setBuilding}
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
