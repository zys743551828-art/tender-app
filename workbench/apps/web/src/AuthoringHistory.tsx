import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import type {
  AuthoringRevisionPage,
  AuthoringHistoricalSectionView,
  DraftSaved,
  RestoreAuthoringSection,
} from "./contracts";
import type { AuthoringHead } from "./SectionEditor";
import { Badge, ErrorNotice } from "./components";
import { authoringText } from "./richEditorSchema";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import { useCommand } from "./useCommand";
import { AuthoringRichSnapshot } from "./AuthoringRichSnapshot";
import { TextChangePreview } from "./TextChangePreview";
import {
  historicalSectionPath,
  readAuthoringRevisionPage,
  validateHistoricalSection,
} from "./authoringHistoryProtocol";

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
          key={`${bidId}:${getHead().draft.id}:${sectionId}`}
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
  const [selected, setSelected] = useState<
    AuthoringRevisionPage["items"][number] | null
  >(null);
  const [error, setError] = useState<unknown>(null);
  const [restored, setRestored] = useState<number | null>(null);
  const [compare, setCompare] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const restorePending = useRef(false);
  const active = useRef(true);
  const pageTicket = useRef(0);
  const pagePending = useRef(false);
  const invalidatePages = useCallback(() => {
    pageTicket.current++;
    pagePending.current = false;
  }, []);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      invalidatePages();
    };
  }, [invalidatePages]);
  const command = useCommand(`section-restore:${sectionId}`);
  const draftId = getHead().draft.id;
  const selectedRevision = selected?.revision,
    selectedDigest = selected?.digest;
  const selection =
    selected === null
      ? null
      : {
          bidId,
          draftId,
          sectionId,
          revision: selected.revision,
          digest: selected.digest,
        };
  const path = selection === null ? null : historicalSectionPath(selection);
  const historical = useResource<unknown>(path);
  const [checked, setChecked] = useState<{
    path: string;
    raw: unknown;
    value?: AuthoringHistoricalSectionView;
    error?: unknown;
  } | null>(null);
  useEffect(() => {
    let live = true;
    if (
      !path ||
      !historical.data ||
      selectedRevision === undefined ||
      selectedDigest === undefined
    )
      return;
    const expected = {
      bidId,
      draftId,
      sectionId,
      revision: selectedRevision,
      digest: selectedDigest,
    };
    void validateHistoricalSection(historical.data, expected).then(
      (value) => {
        if (live) setChecked({ path, raw: historical.data, value });
      },
      (failure) => {
        if (live) setChecked({ path, raw: historical.data, error: failure });
      },
    );
    return () => {
      live = false;
    };
  }, [
    path,
    historical.data,
    bidId,
    draftId,
    sectionId,
    selectedRevision,
    selectedDigest,
  ]);
  const result =
    checked?.path === path && checked.raw === historical.data ? checked : null;
  const valid = result?.value;
  const [preview, setPreview] = useState<{
    value: AuthoringHistoricalSectionView;
    ready: boolean;
  } | null>(null);
  const onPreviewReady = useCallback(
    (ready: boolean) => {
      if (valid) setPreview({ value: valid, ready });
    },
    [valid],
  );
  const previewReady = !!valid && preview?.value === valid && preview.ready;
  const directory = useMemo(() => {
    try {
      if (!revisions.data) return { items: [], last: undefined, error: null };
      const first = readAuthoringRevisionPage(revisions.data);
      const byRevision = new Map<
        number,
        AuthoringRevisionPage["items"][number]
      >();
      for (const page of [first, ...more])
        for (const item of page.items) {
          const prior = byRevision.get(item.revision);
          if (
            prior &&
            (prior.digest !== item.digest ||
              prior.created_at !== item.created_at ||
              prior.created_by !== item.created_by)
          )
            throw new Error("同一历史修订的保存身份不一致，请重新读取目录。");
          byRevision.set(item.revision, item);
        }
      return {
        items: [...byRevision.values()],
        last: more.at(-1) ?? first,
        error: null,
      };
    } catch (failure) {
      return { items: [], last: undefined, error: failure };
    }
  }, [revisions.data, more]);
  const { items, last } = directory;
  async function next() {
    if (last?.next_cursor == null || pagePending.current) return;
    pagePending.current = true;
    const ticket = ++pageTicket.current;
    setLoadingMore(true);
    setError(null);
    try {
      const { data } = await api<unknown>(
        `/sections/${sectionId}/revisions?before=${last.next_cursor}`,
      );
      const page = readAuthoringRevisionPage(data, last.next_cursor);
      if (active.current && ticket === pageTicket.current)
        setMore((old) => [...old, page]);
    } catch (failure) {
      if (active.current && ticket === pageTicket.current) setError(failure);
    } finally {
      if (active.current && ticket === pageTicket.current) {
        setLoadingMore(false);
        pagePending.current = false;
      }
    }
  }
  async function restore() {
    if (
      !valid ||
      !previewReady ||
      selected === null ||
      restorePending.current ||
      command.busy ||
      disabled ||
      historical.loading
    )
      return;
    restorePending.current = true;
    setRestoring(true);
    setBusy(true);
    setError(null);
    try {
      if (!(await flush())) return;
      if (!active.current) return;
      const head = getHead();
      if (
        head.draft.id !== draftId ||
        head.draft.bid_id !== bidId ||
        head.section.id !== sectionId
      )
        throw new Error("当前章节已变化，请回到原章节重新核对后恢复。");
      const body: RestoreAuthoringSection = {
        revision: selected.revision,
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
        invalidatePages();
        setLoadingMore(false);
        await revisions.reload();
      }
    } catch (failure) {
      setError(failure);
    } finally {
      restorePending.current = false;
      if (active.current) setRestoring(false);
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
      <ErrorNotice error={error ?? command.error ?? directory.error} />
      <div className="revision-choices">
        {items.map((item) => (
          <button
            className="button secondary"
            key={item.revision}
            onClick={() => {
              setSelected(item);
              setRestored(null);
              setCompare(false);
            }}
            disabled={restoring || command.busy || disabled}
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
          <ErrorNotice error={result?.error} />
          {historical.data && !result && (
            <p role="status">正在核验历史正文与图片绑定…</p>
          )}
          {valid && (
            <>
              <Badge>历史章节修订 {valid.revision}</Badge>
              <p>
                保存于 {new Date(valid.created_at).toLocaleString("zh-CN")}
                。这是只读历史，恢复仍须重新核验当前来源。
              </p>
              <AuthoringRichSnapshot
                key={`${valid.section_revision_id}:${valid.digest}`}
                bidId={bidId}
                content={valid.content}
                expectedImages={valid.images}
                label="拟恢复的完整历史正文"
                onReady={onPreviewReady}
              />
              {!previewReady && (
                <p className="small-note" role="status">
                  完整正文与全部历史图片核验完成后，才能确认恢复。
                </p>
              )}
              <details
                onToggle={(event) => setCompare(event.currentTarget.open)}
              >
                <summary>与当前已保存正文比较</summary>
                {compare && (
                  <>
                    <TextChangePreview
                      before={authoringText(getHead().section.content)}
                      after={authoringText(valid.content)}
                      beforeLabel="当前已保存正文"
                      afterLabel="拟恢复的历史正文 · 尚未恢复"
                    />
                    <AuthoringRichSnapshot
                      bidId={bidId}
                      content={getHead().section.content}
                      label="完整当前已保存正文"
                    />
                  </>
                )}
              </details>
              <details>
                <summary>保存记录身份</summary>
                <dl className="detail-grid">
                  <dt>保存成员</dt>
                  <dd>{valid.created_by}</dd>
                  <dt>原修订标识</dt>
                  <dd>{valid.section_revision_id}</dd>
                  <dt>正文摘要</dt>
                  <dd>{valid.digest}</dd>
                </dl>
              </details>
              <button
                className="button secondary"
                disabled={
                  disabled ||
                  restoring ||
                  command.busy ||
                  historical.loading ||
                  !previewReady
                }
                onClick={() => void restore()}
              >
                {restoring || command.busy
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
