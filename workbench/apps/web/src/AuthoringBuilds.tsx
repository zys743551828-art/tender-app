import { useEffect, useRef, useState } from "react";
import { api, completeCommand } from "./api";
import type { ApiResult } from "./api";
import type {
  Accepted,
  AuthoringCapabilities,
  AuthoringRichCapabilities,
  AuthoringTreeView,
  BuildPage,
  BuildRequest,
  BuildView,
  DraftView,
} from "./contracts";
import { AuthoringBuildResult } from "./AuthoringBuildResult";
import { Badge, ErrorNotice } from "./components";
import {
  definitiveBuildFailure,
  matchBuildAck,
  readBuildCache,
  validBuildView,
} from "./authoringBuildRecovery";
import type { BuildCache } from "./authoringBuildRecovery";
import { rememberOperation } from "./operationStorage";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";

export function AuthoringBuilds({
  bidId,
  memberId,
  projectTitle = "当前项目",
  draftId,
  capabilities,
  richCapabilities,
  disabled,
  prepare,
  setBusy,
  onPackages,
}: {
  bidId: string;
  memberId: string;
  projectTitle?: string;
  draftId: string;
  capabilities: AuthoringCapabilities;
  richCapabilities?: AuthoringRichCapabilities;
  disabled: boolean;
  prepare: () => Promise<ApiResult<DraftView> | null>;
  setBusy: (busy: boolean) => void;
  onPackages?: () => void;
}) {
  const cacheKey = `tender:authoring:${memberId}:${bidId}:${draftId}:builds`;
  const scope = `authoring-build:${memberId}:${bidId}:${draftId}`;
  const [recovery] = useState(() =>
    readBuildCache(cacheKey, bidId, memberId, draftId),
  );
  const [cache, setCache] = useState(recovery.cache);
  const cacheRef = useRef(cache);
  const [expandedBuild, setExpandedBuild] = useState<string | null>(
    cache.received[0]?.id ?? null,
  );
  const [formats, setFormats] = useState<("docx" | "pdf")[]>(
    capabilities.formats,
  );
  const [pagination, setPagination] = useState<
    "chapter_start_new_page" | "continuous"
  >("chapter_start_new_page");
  const [busy, setLocalBusy] = useState(false);
  const working = useRef(false);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const [error, setError] = useState<unknown>(null);
  const historyPath = `/bids/${bidId}/builds?draft_id=${encodeURIComponent(draftId)}`;
  const history = useResource<BuildPage>(historyPath);
  const [more, setMore] = useState<BuildPage[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const rawHistory = [
    ...(history.data?.items ?? []),
    ...more.flatMap((page) => page.items),
  ];
  const historyInvalid = rawHistory.some(
    (row) => !validBuildView(row, bidId, draftId),
  );
  const serverBuilds = rawHistory.filter((row) =>
    validBuildView(row, bidId, draftId),
  );
  const builds = [
    ...new Map(
      [
        ...cache.received,
        ...serverBuilds.map((row) => ({
          id: row.id,
          snapshotId: row.draft_snapshot_id,
          revision: row.identity.draft_revision,
        })),
      ].map((row) => [row.id, row]),
    ).values(),
  ];
  const lastPage = more.at(-1) ?? history.data;
  function persist(value: BuildCache) {
    sessionStorage.setItem(cacheKey, JSON.stringify(value));
    cacheRef.current = value;
    setCache(value);
  }
  async function build() {
    if (
      working.current ||
      recovery.blocked ||
      (!cacheRef.current.pending && (disabled || !formats.length))
    )
      return;
    working.current = true;
    setLocalBusy(true);
    setBusy(true);
    setError(null);
    let sent = false;
    let responseReceived = false;
    try {
      let pending = cacheRef.current.pending;
      if (!pending) {
        const head = await prepare();
        if (!head || !active.current) return;
        if (
          head.data.id !== draftId ||
          head.data.bid_id !== bidId ||
          !head.etag ||
          !head.data.snapshot_id ||
          !Number.isSafeInteger(head.data.revision) ||
          head.data.revision < 1
        )
          throw new Error("当前草稿尚无可核对的保存确认，请先完成章节保存。");
        const structure = await api<AuthoringTreeView>(
          `/bids/${bidId}/drafts/${draftId}/structure`,
        );
        if (!active.current) return;
        if (
          structure.data.draft_id !== draftId ||
          structure.data.draft_revision !== head.data.revision ||
          !structure.data.directory_template_version_id ||
          !structure.data.style_template_version_id
        )
          throw new Error(
            "目录与已保存正文修订不一致，请读取最新目录后重试生成。",
          );
        const body: BuildRequest = {
          draft_id: draftId,
          draft_revision: head.data.revision,
          directory_template_version_id:
            structure.data.directory_template_version_id,
          style_template_version_id: structure.data.style_template_version_id,
          formats: [...formats],
          follow_up: "none",
          ...(richCapabilities ? { pagination_mode: pagination } : {}),
        };
        pending = {
          body,
          key: crypto.randomUUID(),
          snapshotId: head.data.snapshot_id,
        };
        persist({ ...cacheRef.current, pending });
      }
      if (!active.current) return;
      sent = true;
      const { data: accepted } = await api<Accepted>(`/bids/${bidId}/builds`, {
        method: "POST",
        body: pending.body,
        key: pending.key,
      });
      responseReceived = true;
      if (!active.current) return;
      if (
        accepted?.resource_kind !== "build" ||
        typeof accepted.resource_id !== "string" ||
        !accepted.operation ||
        accepted.operation.bid_id !== bidId
      )
        throw new Error("受理响应身份无法核对，原构建请求保留。");
      const { data: result } = await api<BuildView>(
        `/builds/${accepted.resource_id}`,
      );
      if (!active.current) return;
      if (!matchBuildAck(accepted, result, bidId, draftId, pending))
        throw new Error(
          "受理结果与原草稿修订、模板或固定快照不一致。原请求保留，未采用其他版本。",
        );
      persist({
        ...cacheRef.current,
        pending: null,
        received: [
          {
            id: result.id,
            snapshotId: result.draft_snapshot_id,
            revision: result.identity.draft_revision,
          },
          ...cacheRef.current.received.filter((row) => row.id !== result.id),
        ].slice(0, 30),
      });
      setExpandedBuild(result.id);
      completeCommand(scope);
      try {
        rememberOperation(bidId, accepted.operation.id);
      } catch {
        /* The verified build receipt and server history remain the recovery authority. */
      }
      setMore([]);
      void history.reload();
    } catch (failure) {
      if (active.current) {
        if (sent && !responseReceived && definitiveBuildFailure(failure)) {
          try {
            persist({ ...cacheRef.current, pending: null });
            completeCommand(scope);
          } catch {
            setError(
              new Error("无法更新恢复记录，原请求仍保留；请从历史核对后重试。"),
            );
            return;
          }
        }
        setError(
          failure instanceof DOMException
            ? new Error(
                sent
                  ? "构建恢复记录未能更新，原请求可能已受理；请按原记录或历史核对。"
                  : "本机恢复存储空间不足，本次尚未发送构建；正文和原记录保留。",
              )
            : failure,
        );
      }
    } finally {
      working.current = false;
      if (active.current) {
        setBusy(false);
        setLocalBusy(false);
      }
    }
  }
  async function next() {
    if (!lastPage?.next_cursor || loadingMore) return;
    setLoadingMore(true);
    setError(null);
    try {
      const { data } = await api<BuildPage>(
        `${historyPath}&cursor=${encodeURIComponent(lastPage.next_cursor)}`,
      );
      if (active.current) setMore((old) => [...old, data]);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      if (active.current) setLoadingMore(false);
    }
  }
  return (
    <section className="panel authoring-builds" aria-label="生成文件版本">
      <div className="section-heading">
        <div>
          <h3>生成固定版本</h3>
          <p className="small-note">
            先等待所有章节保存确认，再冻结该草稿修订。后续编辑不会改变本次输出。
          </p>
        </div>
        <Badge>目录与版式分别固定</Badge>
      </div>
      <div className="review-shortcuts">
        {(["docx", "pdf"] as const)
          .filter((format) => capabilities.formats.includes(format))
          .map((format) => (
            <label className="checkbox-label" key={format}>
              <input
                type="checkbox"
                disabled={busy || !!cache.pending}
                checked={formats.includes(format)}
                onChange={(event) =>
                  setFormats((old) =>
                    event.target.checked
                      ? [...old, format]
                      : old.filter((item) => item !== format),
                  )
                }
              />
              {format === "docx" ? "Word" : "PDF"}
            </label>
          ))}
        {richCapabilities && (
          <label>
            章页排版
            <select
              aria-label="章页排版"
              value={pagination}
              disabled={busy || !!cache.pending}
              onChange={(event) =>
                setPagination(event.target.value as typeof pagination)
              }
            >
              <option value="chapter_start_new_page">
                每章另起一页（页数可能增加）
              </option>
              <option value="continuous">连续排版（章末页可能未知）</option>
            </select>
          </label>
        )}
        <button
          type="button"
          className="button primary"
          disabled={
            busy ||
            recovery.blocked ||
            (!cache.pending && (disabled || !formats.length))
          }
          onClick={() => void build()}
        >
          {busy
            ? "正在确认保存并受理生成…"
            : cache.pending
              ? `重试受理草稿修订 ${cache.pending.body.draft_revision}`
              : "保存确认后生成文件"}
        </button>
      </div>
      <p className="small-note">
        本次仅生成文件，不自动切换受检正文或开始评审。Word与PDF独立显示结果，生成成功不表示内容通过。
      </p>
      {richCapabilities && !richCapabilities.renderer_configured && (
        <p className="notice warning">
          表图转换器尚未配置；可生成
          Word，PDF、真实目录页码与章页范围可能不可用。构建会如实保留各格式结果。
        </p>
      )}
      {cache.pending && (
        <div className="notice warning">
          上次生成受理尚未确认。重试会核对原草稿修订{" "}
          {cache.pending.body.draft_revision}
          ，不会改用现在的新稿；当前编辑仍保留。
        </div>
      )}
      {recovery.blocked && (
        <div role="alert" className="notice error">
          构建恢复记录无法核对，原记录保留，已停止新建构建。可先查阅本草稿的服务器生成历史。
        </div>
      )}
      <ErrorNotice error={error} />
      <ResourceState
        {...history}
        hasData={!!history.data}
        onRetry={() => void history.reload()}
      />
      {historyInvalid && (
        <div role="alert" className="notice error">
          部分生成历史与当前项目、草稿或固定输入不一致，未展示这些输出。
        </div>
      )}
      {!!builds.length && (
        <>
          <h4>本草稿生成版本</h4>
          <p className="small-note">
            选择生成记录，核对精确草稿修订和固定快照；Word与PDF分别保留实际结果。
          </p>
        </>
      )}
      {builds.map((item) => (
        <div key={item.id}>
          <button
            type="button"
            className="button secondary"
            aria-expanded={expandedBuild === item.id}
            onClick={() =>
              setExpandedBuild((old) => (old === item.id ? null : item.id))
            }
          >
            {expandedBuild === item.id ? "收起生成记录" : "查看生成记录"} · 修订{" "}
            {item.revision ?? "待核对"} · {item.id.slice(0, 8)}
          </button>
          {expandedBuild === item.id && (
            <AuthoringBuildResult
              bidId={bidId}
              draftId={draftId}
              item={item}
              projectTitle={projectTitle}
              memberId={memberId}
              disabled={disabled || busy}
              onPackages={onPackages}
            />
          )}
        </div>
      ))}
      {history.data && !builds.length && !historyInvalid && (
        <p className="small-empty">
          本草稿尚无已受理的文件生成。先保存正文，再生成固定版本。
        </p>
      )}
      {lastPage?.has_more && lastPage.next_cursor && (
        <button
          type="button"
          className="text-button"
          disabled={loadingMore}
          onClick={() => void next()}
        >
          {loadingMore ? "正在读取更早版本…" : "加载更早生成版本"}
        </button>
      )}
    </section>
  );
}
