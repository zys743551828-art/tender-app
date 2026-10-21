import { useState } from "react";
import { api, supportsApi } from "./api";
import type {
  AuthoringRevisionPage,
  DraftSaved,
  RestoreAuthoringSection,
  SectionView,
} from "./contracts";
import type { AuthoringHead } from "./SectionEditor";
import { Badge, ErrorNotice } from "./components";
import { authoringText } from "./richEditorSchema";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import { useCommand } from "./useCommand";

export function AuthoringHistory({
  bidId,
  sectionId,
  disabled,
  flush,
  getHead,
  setBusy,
  refresh,
}: {
  bidId: string;
  sectionId: string;
  disabled: boolean;
  flush: () => Promise<boolean>;
  getHead: () => AuthoringHead;
  setBusy: (busy: boolean) => void;
  refresh: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  return (
    <details
      className="coverage-details"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>查看章节历史修订</summary>
      {open && (
        <RevisionList
          bidId={bidId}
          sectionId={sectionId}
          disabled={disabled}
          flush={flush}
          getHead={getHead}
          setBusy={setBusy}
          refresh={refresh}
        />
      )}
    </details>
  );
}
function RevisionList({
  bidId,
  sectionId,
  disabled,
  flush,
  getHead,
  setBusy,
  refresh,
}: {
  bidId: string;
  sectionId: string;
  disabled: boolean;
  flush: () => Promise<boolean>;
  getHead: () => AuthoringHead;
  setBusy: (busy: boolean) => void;
  refresh: () => Promise<void>;
}) {
  const revisions = useResource<AuthoringRevisionPage>(
    `/sections/${sectionId}/revisions`,
  );
  const [more, setMore] = useState<AuthoringRevisionPage[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [restored, setRestored] = useState<number | null>(null);
  const command = useCommand(`section-restore:${sectionId}`);
  const path =
    selected === null ? null : `/sections/${sectionId}/revisions/${selected}`;
  const historical = useResource<SectionView>(path);
  const valid =
    historical.data &&
    historical.data.id === sectionId &&
    historical.data.revision === selected &&
    historical.data.draft_id === getHead().draft.id;
  const last = more.at(-1) ?? revisions.data;
  const items = [
    ...new Map(
      [
        ...(revisions.data?.items ?? []),
        ...more.flatMap((page) => page.items),
      ].map((item) => [item.revision, item]),
    ).values(),
  ];
  async function next() {
    if (last?.next_cursor == null || loadingMore) return;
    setLoadingMore(true);
    setError(null);
    try {
      const { data } = await api<AuthoringRevisionPage>(
        `/sections/${sectionId}/revisions?before=${last.next_cursor}`,
      );
      setMore((old) => [...old, data]);
    } catch (failure) {
      setError(failure);
    } finally {
      setLoadingMore(false);
    }
  }
  async function restore() {
    if (!valid || selected === null || command.busy || disabled) return;
    setBusy(true);
    setError(null);
    try {
      if (!(await flush())) return;
      const head = getHead();
      const body: RestoreAuthoringSection = {
        revision: selected,
        base_draft_revision: head.draft.revision,
        base_section_revision: head.section.revision,
      };
      const result = await command.run<DraftSaved>(
        `/bids/${bidId}/sections/${sectionId}/restore`,
        body,
        head.etag,
      );
      if (result) {
        await refresh();
        setRestored(result.data.draft_revision);
        setSelected(null);
        setMore([]);
        await revisions.reload();
      }
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="authoring-history">
      <p className="small-note">
        恢复会追加新的章节修订，保留当前版本。来源已变化时由服务器阻止恢复，不把旧证据视为当前有效。
      </p>
      <ResourceState
        {...revisions}
        hasData={!!revisions.data}
        onRetry={() => void revisions.reload()}
      />
      <ErrorNotice error={error ?? command.error} />
      <div className="revision-choices">
        {items.map((item) => (
          <button
            className="button secondary"
            key={item.revision}
            onClick={() => {
              setSelected(item.revision);
              setRestored(null);
            }}
            disabled={command.busy || disabled}
          >
            章节修订 {item.revision}
            <small>{new Date(item.created_at).toLocaleString("zh-CN")}</small>
          </button>
        ))}
      </div>
      {last?.next_cursor != null && (
        <button
          className="text-button"
          disabled={loadingMore}
          onClick={() => void next()}
        >
          {loadingMore ? "正在读取历史…" : "加载更早修订"}
        </button>
      )}
      {path && (
        <>
          {!supportsApi("GET", path) && (
            <p className="notice neutral">
              已读取真实修订记录。历史正文读取尚未开放，因此此处不猜测旧稿内容，也不提供盲恢复。
            </p>
          )}
          <ResourceState
            {...historical}
            hasData={!!historical.data}
            onRetry={() => void historical.reload()}
          />
          {historical.data && !valid && (
            <div className="notice error" role="alert">
              历史修订身份无法核对，未将当前正文冒充旧稿。
            </div>
          )}
          {valid && (
            <>
              <Badge>历史章节修订 {selected}</Badge>
              <div className="editor-comparison">
                <div>
                  <strong>当前已保存正文</strong>
                  <pre>{authoringText(getHead().section.content)}</pre>
                </div>
                <div>
                  <strong>拟恢复的历史正文</strong>
                  <pre>{authoringText(historical.data!.content)}</pre>
                </div>
              </div>
              <button
                className="button secondary"
                disabled={disabled || command.busy}
                onClick={() => void restore()}
              >
                {command.busy
                  ? "正在核验来源并追加修订…"
                  : "恢复此历史正文为新修订"}
              </button>
            </>
          )}
        </>
      )}
      {restored && (
        <p className="inline-success" role="status">
          已追加草稿修订 {restored}，其他历史仍保留。
        </p>
      )}
    </div>
  );
}
