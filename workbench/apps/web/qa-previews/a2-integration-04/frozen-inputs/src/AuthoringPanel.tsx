import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { ApiResult } from "./api";
import type {
  AuthoringCapabilities,
  AuthoringDraftPage,
  AuthoringSectionAdded,
  CreateDraftRequest,
  DraftView,
} from "./contracts";
import { Badge, ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import { useCommand } from "./useCommand";
import { SectionEditor } from "./SectionEditor";
import { AuthoringBuilds } from "./AuthoringBuilds";
import type { SectionEditorHandle } from "./SectionEditor";

export function AuthoringPanel({
  bidId,
  memberId,
  projectTitle,
  draftId,
  onOpenDraft,
}: {
  bidId: string;
  memberId: string;
  projectTitle: string;
  draftId: string | null;
  onOpenDraft: (id: string) => void;
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
    if (draftId) {
      sessionStorage.setItem(positionKey, draftId);
      return;
    }
    const saved = sessionStorage.getItem(positionKey);
    if (saved && drafts.data?.items.some((item) => item.id === saved))
      onOpenDraft(saved);
  }, [draftId, drafts.data, onOpenDraft, positionKey]);
  async function create() {
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
                  required
                  maxLength={200}
                  placeholder="例如：技术投标文件"
                  onChange={(event) => setTitle(event.target.value)}
                />
              </label>
              <button
                className="button secondary"
                disabled={command.busy || !title.trim() || !memberId}
              >
                {command.busy ? "正在创建…" : "创建正文草稿"}
              </button>
            </form>
            <p className="small-note">
              本批支持文字、标题和列表，内置A4版式；图片、表格及外部Word无损导入尚未开放，未接收的对象不会被称为已保真。
            </p>
          </>
        )}
      </section>
      {draftId && capabilities.data && (
        <DraftEditor
          key={draftId}
          bidId={bidId}
          memberId={memberId}
          draftId={draftId}
          capabilities={capabilities.data}
          projectTitle={projectTitle}
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
  projectTitle,
}: {
  bidId: string;
  memberId: string;
  draftId: string;
  capabilities: AuthoringCapabilities;
  projectTitle: string;
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
  const [selected, setSelected] = useState<string | null>(() =>
    sessionStorage.getItem(sectionPositionKey),
  );
  const [title, setTitle] = useState("");
  const [switching, setSwitching] = useState(false);
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const editor = useRef<SectionEditorHandle>(null);
  const command = useCommand(`section:add:${memberId}:${draftId}`);
  const sectionId = view?.sections.some((section) => section.id === selected)
    ? selected!
    : view?.sections[0]?.id;
  async function choose(id: string) {
    if (switching || building || id === sectionId) return;
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
  async function add() {
    if (building || switching) return;
    if (editor.current && !(await editor.current.flush())) return;
    try {
      const current = await api<DraftView>(`/bids/${bidId}/drafts/${draftId}`);
      const result = await command.run<AuthoringSectionAdded>(
        `/bids/${bidId}/drafts/${draftId}/sections`,
        { title: title.trim() },
        current.etag,
      );
      if (result) {
        setTitle("");
        await reloadHead();
        setSelected(result.data.section_id);
        sessionStorage.setItem(sectionPositionKey, result.data.section_id);
      }
    } catch (failure) {
      setError(failure);
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
      <ErrorNotice error={command.error ?? error} />
      {view && current.etag && (
        <div className="authoring-columns">
          <aside className="chapter-outline panel" aria-label="章节目录">
            <div className="section-heading">
              <div>
                <h3>章节目录</h3>
                <p className="small-note">草稿修订 {view.revision}</p>
              </div>
            </div>
            {view.sections.map((section, index) => (
              <button
                className={`chapter-link${section.id === sectionId ? " selected" : ""}`}
                aria-current={section.id === sectionId ? "true" : undefined}
                disabled={switching || building}
                key={section.id}
                onClick={() => void choose(section.id)}
              >
                <span>{index + 1}</span>
                <div>
                  {section.title}
                  <small>
                    章节修订 {section.revision} · 关联 {section.rule_ids.length}{" "}
                    条要求
                  </small>
                </div>
              </button>
            ))}
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void add();
              }}
            >
              <label>
                新增章节名称
                <input
                  value={title}
                  maxLength={200}
                  required
                  onChange={(event) => setTitle(event.target.value)}
                />
              </label>
              <button
                className="button secondary"
                disabled={
                  command.busy || switching || building || !title.trim()
                }
              >
                {command.busy ? "正在追加章节…" : "新增章节"}
              </button>
            </form>
          </aside>
          <section className="chapter-writing panel" aria-label="正文编写">
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
                disabled={switching || command.busy || building}
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
      {view && current.etag && (
        <AuthoringBuilds
          bidId={bidId}
          memberId={memberId}
          draftId={draftId}
          capabilities={capabilities}
          projectTitle={projectTitle}
          disabled={switching || command.busy}
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
