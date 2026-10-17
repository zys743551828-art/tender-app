import { useRef, useState } from "react";
import { api, ApiError, commandKey, completeCommand } from "./api";
import type { ApiResult } from "./api";
import type {
  Accepted,
  AuthoringCapabilities,
  AuthoringTreeView,
  AuthoringSnapshot,
  BuildRequest,
  BuildView,
  BuildPage,
  DraftView,
  Operation,
} from "./contracts";
import { ArtifactActions } from "./ArtifactActions";
import { generatedFilename } from "./artifactNames";
import { Badge, ErrorNotice } from "./components";
import { editorText } from "./editorSchema";
import { rememberOperation } from "./operationStorage";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";

type PendingBuild = { key: string; body: BuildRequest };
type ReceivedBuild = {
  id: string;
  snapshotId: string;
  revision: number | null;
};
type BuildCache = { pending: PendingBuild | null; received: ReceivedBuild[] };
function readCache(key: string): BuildCache {
  try {
    const value = JSON.parse(
      sessionStorage.getItem(key) ?? "null",
    ) as BuildCache | null;
    return value && Array.isArray(value.received)
      ? value
      : { pending: null, received: [] };
  } catch {
    return { pending: null, received: [] };
  }
}

export function AuthoringBuilds({
  bidId,
  memberId,
  projectTitle = "当前项目",
  draftId,
  capabilities,
  disabled,
  prepare,
  setBusy,
}: {
  bidId: string;
  memberId: string;
  projectTitle?: string;
  draftId: string;
  capabilities: AuthoringCapabilities;
  disabled: boolean;
  prepare: () => Promise<ApiResult<DraftView> | null>;
  setBusy: (busy: boolean) => void;
}) {
  const cacheKey = `tender:authoring:${memberId}:${bidId}:${draftId}:builds`;
  const scope = `authoring-build:${memberId}:${bidId}:${draftId}`;
  const [cache, setCache] = useState(() => readCache(cacheKey));
  const cacheRef = useRef(cache);
  const [formats, setFormats] = useState<("docx" | "pdf")[]>(["docx", "pdf"]);
  const [busy, setLocalBusy] = useState(false);
  const working = useRef(false);
  const [error, setError] = useState<unknown>(null);
  const history = useResource<BuildPage>(`/bids/${bidId}/builds`);
  const [more, setMore] = useState<BuildPage[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const serverBuilds = [
    ...new Map(
      [
        ...(history.data?.items ?? []),
        ...more.flatMap((page) => page.items),
      ].map((build) => [build.id, build]),
    ).values(),
  ];
  const known = new Map(cache.received.map((item) => [item.id, item]));
  const builds = [
    ...new Map(
      [
        ...cache.received,
        ...serverBuilds.map(
          (build) =>
            known.get(build.id) ?? {
              id: build.id,
              snapshotId: build.draft_snapshot_id,
              revision: null,
            },
        ),
      ].map((item) => [item.id, item]),
    ).values(),
  ];
  const lastPage = more.at(-1) ?? history.data;
  function persist(value: BuildCache) {
    cacheRef.current = value;
    sessionStorage.setItem(cacheKey, JSON.stringify(value));
    setCache(value);
  }
  async function build() {
    if (working.current || disabled || !formats.length) return;
    working.current = true;
    setLocalBusy(true);
    setBusy(true);
    setError(null);
    try {
      let pending = cacheRef.current.pending;
      if (!pending) {
        const head = await prepare();
        if (!head) return;
        if (!head.data.snapshot_id)
          throw new Error("当前草稿尚无已确认快照，请先完成章节保存。");
        const structure = await api<AuthoringTreeView>(
          `/bids/${bidId}/drafts/${draftId}/structure`,
        );
        if (
          structure.data.draft_id !== draftId ||
          structure.data.draft_revision !== head.data.revision
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
          formats,
          follow_up: "none",
        };
        pending = { body, key: commandKey(scope, body) };
        persist({ ...cacheRef.current, pending });
      }
      // Retain the exact revision/body/key across lost responses and refreshes.
      const accepted = await api<Accepted>(`/bids/${bidId}/builds`, {
        method: "POST",
        body: pending.body,
        key: pending.key,
      });
      if (
        accepted.data.resource_kind !== "build" ||
        accepted.data.operation.bid_id !== bidId
      )
        throw new Error("受理结果身份不一致，未展示其他项目的生成结果。");
      rememberOperation(bidId, accepted.data.operation.id);
      const received = {
        id: accepted.data.resource_id,
        snapshotId: "",
        revision: pending.body.draft_revision,
      };
      persist({
        pending: null,
        received: [
          received,
          ...cacheRef.current.received.filter(
            (item) => item.id !== received.id,
          ),
        ].slice(0, 30),
      });
      completeCommand(scope);
      setMore([]);
      void history.reload();
    } catch (failure) {
      if (
        failure instanceof ApiError &&
        [400, 409, 412, 422].includes(failure.status)
      ) {
        persist({ ...cacheRef.current, pending: null });
        completeCommand(scope);
      }
      setError(failure);
    } finally {
      working.current = false;
      setBusy(false);
      setLocalBusy(false);
    }
  }
  async function next() {
    if (!lastPage?.next_cursor || loadingMore) return;
    setLoadingMore(true);
    setError(null);
    try {
      const { data } = await api<BuildPage>(
        `/bids/${bidId}/builds?cursor=${encodeURIComponent(lastPage.next_cursor)}`,
      );
      setMore((old) => [...old, data]);
    } catch (failure) {
      setError(failure);
    } finally {
      setLoadingMore(false);
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
                      : old.filter((value) => value !== format),
                  )
                }
              />
              {format === "docx" ? "Word" : "PDF"}
            </label>
          ))}
        <button
          className="button primary"
          disabled={busy || disabled || !formats.length}
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
      {cache.pending && (
        <div className="notice warning">
          上次生成受理尚未确认。重试会核对原草稿修订{" "}
          {cache.pending.body.draft_revision}
          ，不会改用现在的新稿；当前编辑仍保留。
        </div>
      )}
      <ErrorNotice error={error} />
      <ResourceState
        {...history}
        hasData={!!history.data}
        onRetry={() => void history.reload()}
      />
      {builds.length > 0 && (
        <>
          <h4>本项目生成版本</h4>
          <p className="small-note">
            从服务器恢复已受理任务与固定快照，Word和PDF分别保留实际结果。草稿修订只在已取得其确认身份时显示。
          </p>
        </>
      )}
      {builds.map((item) => (
        <BuildResult
          key={item.id}
          bidId={bidId}
          item={item}
          projectTitle={projectTitle}
        />
      ))}
      {history.data && !builds.length && (
        <p className="small-empty">
          本项目尚无已受理的文件生成。先保存正文，再生成固定版本。
        </p>
      )}
      {lastPage?.has_more && lastPage.next_cursor && (
        <button
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

function BuildResult({
  bidId,
  item,
  projectTitle,
}: {
  bidId: string;
  item: ReceivedBuild;
  projectTitle: string;
}) {
  const result = useResource<BuildView>(`/builds/${item.id}`, 2500);
  const operation = useResource<Operation>(
    result.data ? `/operations/${result.data.operation_id}` : null,
    2500,
  );
  const [showSnapshot, setShowSnapshot] = useState(false);
  const snapshot = useResource<AuthoringSnapshot>(
    showSnapshot && result.data
      ? `/bids/${bidId}/draft-snapshots/${result.data.draft_snapshot_id}`
      : null,
  );
  if (
    (result.data && result.data.id !== item.id) ||
    (operation.data && operation.data.bid_id !== bidId)
  )
    return (
      <div role="alert" className="notice error">
        生成任务身份不一致，未展示输出。
      </div>
    );
  const terminal =
    operation.data &&
    ["failed", "cancelled", "succeeded"].includes(operation.data.state);
  return (
    <article className="build-result">
      <div className="section-heading">
        <strong>
          {item.revision === null
            ? "固定快照生成版本"
            : `来自草稿修订 ${item.revision}`}
        </strong>
        <Badge
          tone={operation.data?.state === "failed" ? "warning" : "neutral"}
        >
          {operation.data?.state === "failed"
            ? "生成任务失败"
            : operation.data?.state === "cancelled"
              ? "生成任务已取消"
              : operation.data?.state === "succeeded"
                ? "生成任务已完成"
                : "生成处理中"}
        </Badge>
      </div>
      <ResourceState
        {...result}
        hasData={!!result.data}
        onRetry={() => void result.reload()}
      />
      <ResourceState
        {...operation}
        hasData={!!operation.data}
        onRetry={() => void operation.reload()}
      />
      {result.data && (
        <>
          <details className="coverage-details">
            <summary>核对本次固定快照身份</summary>
            <p className="small-note identity-ref">
              {result.data.draft_snapshot_id}
            </p>
          </details>
          <button
            className="text-button"
            onClick={() => setShowSnapshot((old) => !old)}
          >
            {showSnapshot ? "收起本次快照正文" : "查看本次快照正文"}
          </button>
          {showSnapshot && (
            <>
              <ResourceState
                {...snapshot}
                hasData={!!snapshot.data}
                onRetry={() => void snapshot.reload()}
              />
              {snapshot.data &&
                snapshot.data.snapshot_id === result.data.draft_snapshot_id && (
                  <div className="snapshot-reading">
                    <h4>{snapshot.data.title}</h4>
                    {snapshot.data.sections.map((section, index) => (
                      <section key={index}>
                        <strong>{section.attrs.title}</strong>
                        <pre>{editorText(section)}</pre>
                      </section>
                    ))}
                  </div>
                )}
            </>
          )}
          {!result.data.outputs.length && (
            <p className="small-note">
              {terminal
                ? "任务已结束，尚无可用格式输出。请查看操作状态与失败原因。"
                : "尚无格式输出；受理不表示文件已生成。"}
            </p>
          )}
          {result.data.outputs.map((output) => (
            <div className="build-output" key={output.format}>
              <strong>{output.format === "docx" ? "Word" : "PDF"}</strong>
              <Badge
                tone={output.state === "succeeded" ? "success" : "warning"}
              >
                {output.state === "succeeded"
                  ? "此格式生成成功"
                  : output.state === "failed"
                    ? "此格式生成失败"
                    : "此格式正在生成"}
              </Badge>
              {output.gaps.map((gap, index) => (
                <p className="small-note" key={index}>
                  {gap === "RENDER_SANDBOX_NOT_ATTESTED"
                    ? "文件已生成，正式提交前请核对字体、分页与版面；当前转换环境尚未完成正式交付验收。"
                    : gap === "TOC_PAGE_NUMBERS_UNKNOWN"
                      ? "目录页码尚未实测，当前目录不能作为准确页码依据。"
                      : gap === "ACTUAL_SECTION_PAGE_RANGES_UNKNOWN"
                        ? "各章实际物理页范围尚未测得；计划页数不代表实际页数。"
                        : gap}
                </p>
              ))}
              {output.state === "succeeded" && output.document_version_id && (
                <ArtifactActions
                  bidId={bidId}
                  documentId={output.document_version_id}
                  isPdf={output.format === "pdf"}
                  downloadLabel={`下载投标正文（${output.format === "docx" ? "Word" : "PDF"}）`}
                  suggestedFilename={generatedFilename(
                    projectTitle,
                    result.data!.draft_snapshot_id,
                    output.format,
                  )}
                />
              )}
            </div>
          ))}
        </>
      )}
    </article>
  );
}
