import { AuthoringTemplateEditor } from "./AuthoringTemplateEditor";
import { AuthoringFormatBindings } from "./AuthoringFormatBindings";
import { useEffect, useState, useRef } from "react";
import { api, type ApiResult } from "./api";
import type {
  AuthoringTreeView,
  AuthoringTreeChangeRequest,
  AuthoringStructurePreview,
  AuthoringStylePreview,
  AuthoringStructureResult,
  AuthoringStructureHistory,
  AuthoringTemplateCatalog,
  AuthoringTemplateVersionView,
  AuthoringStyleApplyPreview,
  DraftView,
} from "./contracts";
import { treeOrder, record } from "./authoringStructureState";
import { useResource } from "./useResource";
import { useRecordedCommand } from "./useRecordedCommand";
import { useKnowledgeInput } from "./knowledgeStorage";
import { ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { AuthoringPlan } from "./AuthoringPlan";

type Change = AuthoringTreeChangeRequest["changes"][number];
type Held = { value: AuthoringStylePreview; etag: string };
export function AuthoringStructure({
  bidId,
  memberId,
  draftId,
  draftRevision,
  sectionId,
  disabled,
  readOnly = false,
  onChoose,
  onContinue,
  prepare,
  onChanged,
  onBusy,
}: {
  bidId: string;
  memberId: string;
  draftId: string;
  draftRevision: number;
  sectionId: string | undefined;
  disabled: boolean;
  readOnly?: boolean;
  onChoose: (id: string) => Promise<void>;
  onContinue?: () => void;
  prepare: () => Promise<ApiResult<DraftView> | null>;
  onChanged: () => Promise<unknown>;
  onBusy: (busy: boolean) => void;
}) {
  const path = `/bids/${bidId}/drafts/${draftId}`;
  const tree = useResource<AuthoringTreeView>(path + "/structure");
  const reloadTree = tree.reload;
  useEffect(() => {
    void reloadTree();
  }, [draftRevision, reloadTree]);
  const preview = useRecordedCommand(
    `authoring-structure:${memberId}:${draftId}`,
  );
  const resolve = useRecordedCommand(
    `authoring-resolve:${memberId}:${draftId}`,
  );
  const [held, setHeld] = useKnowledgeInput<Held | null>(
    `tender:knowledge:${memberId}:structure-preview:${draftId}`,
    null,
  );
  const [working, setWorking] = useState(false);
  const [planWorking, setPlanWorking] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [title, setTitle] = useKnowledgeInput(
    `tender:knowledge:${memberId}:structure-form:${draftId}:title`,
    "",
  );
  const [parent, setParent] = useKnowledgeInput(
    `tender:knowledge:${memberId}:structure-form:${draftId}:parent`,
    "",
  );
  const [ordinal, setOrdinal] = useKnowledgeInput(
    `tender:knowledge:${memberId}:structure-form:${draftId}:ordinal`,
    1,
  );
  const [kind, setKind] = useKnowledgeInput<"chapter" | "appendix">(
    `tender:knowledge:${memberId}:structure-form:${draftId}:kind`,
    "chapter",
  );
  const [showHistory, setShowHistory] = useState(false);
  const history = useResource<AuthoringStructureHistory>(
    showHistory ? path + "/structure/history" : null,
  );
  const [more, setMore] = useState<AuthoringStructureHistory[]>([]);
  const [styleRequest, setStyleRequest] =
    useKnowledgeInput<AuthoringStyleApplyPreview | null>(
      `tender:knowledge:${memberId}:style-preview-request:${draftId}`,
      null,
    );
  const previewPanel = useRef<HTMLElement>(null);
  useEffect(() => {
    if (held) {
      previewPanel.current?.focus({ preventScroll: true });
      previewPanel.current?.scrollIntoView?.({ block: "start" });
    }
  }, [held]);
  const navigationLocked =
    disabled ||
    planWorking ||
    working ||
    preview.busy ||
    resolve.busy ||
    !!preview.pending ||
    !!resolve.pending ||
    !!held;
  const locked = readOnly || navigationLocked;
  useEffect(() => {
    onBusy(
      working ||
        planWorking ||
        preview.busy ||
        resolve.busy ||
        !!held ||
        !!preview.pending ||
        !!resolve.pending,
    );
    return () => onBusy(false);
  }, [
    working,
    planWorking,
    preview.busy,
    resolve.busy,
    held,
    preview.pending,
    resolve.pending,
    onBusy,
  ]);
  const valid = tree.data?.draft_id === draftId ? tree.data : undefined;
  async function refresh() {
    await onChanged();
    await tree.reload();
    if (showHistory) await history.reload();
  }
  async function begin(
    suffix: string,
    body: (revision: number) => unknown,
    retry = false,
  ) {
    if (disabled || (!retry && readOnly) || working) return;
    setWorking(true);
    setError(null);
    try {
      let response;
      let tag = held?.etag ?? "";
      if (retry) {
        tag = preview.pending?.etag ?? "";
        response = await preview.retry<AuthoringStylePreview>();
      } else {
        const head = await prepare();
        if (!head?.etag) return;
        tag = head.etag;
        response = await preview.run<AuthoringStylePreview>(
          path + suffix,
          body(head.data.revision),
          tag,
        );
      }
      if (response) {
        setHeld({ value: response.data, etag: tag });
      }
    } catch (e) {
      setError(e);
    } finally {
      setWorking(false);
    }
  }
  async function change(op: Change) {
    await begin(
      "/structure/preview",
      (revision) =>
        ({
          base_draft_revision: revision,
          changes: [op],
        }) satisfies AuthoringTreeChangeRequest,
    );
  }
  async function decide(decision: "confirm" | "reject", retry = false) {
    if (!held?.value.action_id && !resolve.pending) return;
    if (!retry && decision === "confirm" && (disabled || readOnly)) return;
    setWorking(true);
    try {
      const r = retry
        ? await resolve.retry<AuthoringStructureResult>()
        : await resolve.run<AuthoringStructureResult>(
            `/bids/${bidId}/authoring-structure-actions/${held!.value.action_id}/resolve`,
            { decision },
            held!.etag,
          );
      if (r) {
        setHeld(null);
        setStyleRequest(null);
        await refresh();
      }
    } catch (e) {
      setError(e);
    } finally {
      setWorking(false);
    }
  }
  async function nextHistory() {
    const last = more.at(-1) ?? history.data;
    if (!last?.next_cursor) return;
    try {
      const r = await api<AuthoringStructureHistory>(
        path + `/structure/history?before_revision=${last.next_cursor}`,
      );
      setMore((old) => [...old, r.data]);
    } catch (e) {
      setError(e);
    }
  }
  const node = valid?.nodes.find(
    (n) => n.section_id === sectionId && !n.deleted,
  );
  const parentValue = parent ? { section_id: parent } : null;
  return (
    <div className="authoring-structure">
      <h3>章节目录</h3>
      <ResourceState
        {...tree}
        hasData={!!valid}
        onRetry={() => void tree.reload()}
      />
      <ErrorNotice error={error ?? preview.error ?? resolve.error} />
      {valid && (
        <>
          <p className="small-note">
            草稿修订 {valid.draft_revision} · 人工计划{" "}
            {valid.page_budget.planned_total} 页，
            {valid.page_budget.unknown_section_ids.length}{" "}
            章未填预算。实际总页与章页范围尚未测得，目录页码未核完。
          </p>
          <ol className="chapter-tree" aria-label="当前章节层级">
            {treeOrder(valid.nodes).map(({ node: n, depth }) => (
              <li
                key={n.section_id}
                style={{ paddingInlineStart: `${Math.min(depth, 8) * 12}px` }}
              >
                <button
                  className={`chapter-link${n.section_id === sectionId ? " selected" : ""}`}
                  aria-current={n.section_id === sectionId ? "true" : undefined}
                  disabled={navigationLocked}
                  onClick={() => void onChoose(n.section_id)}
                >
                  <span>{n.node_type === "appendix" ? "附" : "章"}</span>
                  <div>
                    {n.title}
                    <small>
                      修订 {n.section_revision} ·{" "}
                      {n.plan?.planned_pages ?? "未填"} 预算页 ·{" "}
                      {n.plan_content_basis_state === "section_changed"
                        ? "计划基准已变化"
                        : n.plan
                          ? "已有编写计划"
                          : "未建计划"}
                    </small>
                  </div>
                </button>
              </li>
            ))}
          </ol>
          {sectionId && onContinue && (
            <button
              className="button secondary"
              disabled={navigationLocked}
              onClick={onContinue}
            >
              {readOnly ? "查看本章正文" : "继续编写本章"}
            </button>
          )}
          <details>
            <summary>新增或调整章节目录</summary>
            <fieldset disabled={locked}>
              <legend>调整目录（先预览，不直接改稿）</legend>
              <label>
                章节名称
                <input
                  value={title}
                  maxLength={200}
                  onChange={(e) => setTitle(e.target.value)}
                />
              </label>
              <label>
                放入上级章节
                <select
                  value={parent}
                  onChange={(e) => setParent(e.target.value)}
                >
                  <option value="">顶层</option>
                  {parent &&
                    !valid.nodes.some(
                      (n) => !n.deleted && n.section_id === parent,
                    ) && (
                      <option value={parent}>先前上级已变化，请重新选择</option>
                    )}
                  {valid.nodes
                    .filter((n) => !n.deleted && n.section_id !== sectionId)
                    .map((n) => (
                      <option value={n.section_id} key={n.section_id}>
                        {n.title}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                同级位置（从1开始）
                <input
                  type="number"
                  min={1}
                  max={500}
                  value={ordinal}
                  onChange={(e) => setOrdinal(Number(e.target.value))}
                />
              </label>
              <label>
                章节类型
                <select
                  value={kind}
                  onChange={(e) => setKind(e.target.value as typeof kind)}
                >
                  <option value="chapter">正文章节</option>
                  <option value="appendix">附录</option>
                </select>
              </label>
              <div className="review-shortcuts">
                <button
                  className="button secondary"
                  disabled={!title.trim()}
                  onClick={() =>
                    void change({
                      op: "add",
                      client_key: crypto.randomUUID(),
                      title: title.trim(),
                      node_type: kind,
                      parent: parentValue,
                      ordinal: ordinal - 1,
                    })
                  }
                >
                  预览新增章节
                </button>
                {node && (
                  <>
                    <button
                      className="text-button"
                      disabled={!title.trim()}
                      onClick={() =>
                        void change({
                          op: "rename",
                          section_id: node.section_id,
                          title: title.trim(),
                        })
                      }
                    >
                      预览重命名本章
                    </button>
                    <button
                      className="text-button"
                      onClick={() =>
                        void change({
                          op: "move",
                          section_id: node.section_id,
                          parent: parentValue,
                          ordinal: ordinal - 1,
                        })
                      }
                    >
                      预览移动本章
                    </button>
                    <button
                      className="text-button"
                      onClick={() =>
                        void change({
                          op: "copy",
                          section_id: node.section_id,
                          parent: parentValue,
                          ordinal: ordinal - 1,
                          client_key: crypto.randomUUID(),
                        })
                      }
                    >
                      预览复制本章
                    </button>
                    <button
                      className="text-button"
                      onClick={() =>
                        void change({
                          op: "set_type",
                          section_id: node.section_id,
                          node_type: kind,
                        })
                      }
                    >
                      预览更改章节类型
                    </button>
                    <button
                      className="text-button"
                      onClick={() =>
                        void change({
                          op: "delete",
                          section_id: node.section_id,
                        })
                      }
                    >
                      预览删除本章及子章
                    </button>
                  </>
                )}
              </div>
            </fieldset>
          </details>
          {valid.nodes.some((n) => n.deleted) && (
            <details>
              <summary>已删除章节 · 可预览恢复</summary>
              {valid.nodes
                .filter((n) => n.deleted)
                .map((n) => (
                  <div className="review-shortcuts" key={n.section_id}>
                    <span>{n.title}</span>
                    <button
                      className="text-button"
                      disabled={locked}
                      onClick={() =>
                        void change({
                          op: "restore",
                          section_id: n.section_id,
                          parent: parentValue,
                          ordinal: ordinal - 1,
                          include_descendants: true,
                        })
                      }
                    >
                      预览恢复此章及子章
                    </button>
                  </div>
                ))}
            </details>
          )}
          <TemplateSelection
            key={`${valid.directory_template_version_id}:${valid.style_template_version_id}`}
            tree={valid}
            bidId={bidId}
            memberId={memberId}
            disabled={locked}
            onDirectory={(id, matches) =>
              void begin("/directory-template/preview", (r) => ({
                base_draft_revision: r,
                directory_template_version_id: id,
                matches,
                delete_section_ids: [],
              }))
            }
            onStyle={(id, bindings) => {
              const body: AuthoringStyleApplyPreview = {
                base_draft_revision: valid.draft_revision,
                style_template_version_id: id,
                format_bindings: bindings,
                format_review_ack: null,
              };
              setStyleRequest(body);
              void begin("/style-template/preview", (r) => ({
                ...body,
                base_draft_revision: r,
              }));
            }}
          />
          {node && (
            <AuthoringPlan
              key={node.section_id}
              node={node}
              bidId={bidId}
              memberId={memberId}
              draftId={draftId}
              draftRevision={valid.draft_revision}
              disabled={locked}
              prepare={prepare}
              onSaved={refresh}
              onBusy={setPlanWorking}
            />
          )}
        </>
      )}
      {preview.pending && (
        <button
          className="button secondary"
          disabled={working || disabled}
          onClick={() => void begin("", () => ({}), true)}
        >
          恢复原目录预览结果
        </button>
      )}
      {!held && resolve.pending && (
        <button
          className="button secondary"
          disabled={resolve.busy || disabled}
          onClick={() => void decide("confirm", true)}
        >
          恢复原变更处理结果
        </button>
      )}
      {held && (
        <section
          ref={previewPanel}
          tabIndex={-1}
          className="structure-preview"
          aria-label="目录与版式变更预览"
        >
          <h4>变更尚未应用</h4>
          {held.value.action_id ? (
            <>
              <p className="small-note">
                基于草稿修订 {held.value.base_draft_revision}
                ，确认时仍核对原修订。后续编辑不会被静默覆盖。
              </p>
              <Preview value={held.value} />
              <div className="review-shortcuts">
                <button
                  className="button primary"
                  disabled={
                    disabled ||
                    readOnly ||
                    working ||
                    resolve.busy ||
                    !!resolve.pending
                  }
                  onClick={() => void decide("confirm")}
                >
                  应用这次变更
                </button>
                <button
                  className="button secondary"
                  disabled={working || resolve.busy || !!resolve.pending}
                  onClick={() => void decide("reject")}
                >
                  放弃这次变更
                </button>
              </div>
            </>
          ) : (
            <>
              <FormatReport value={held.value.format_report} />
              <p className="notice warning">
                仅按已有人工有据绑定的格式字段应用；其他格式和暗标语义尚未核完。核对后再生成变更预览，仍未改稿。
              </p>
              <button
                className="button secondary"
                disabled={!styleRequest || working}
                onClick={() => {
                  const digest = record(held.value.format_report).review_digest;
                  if (typeof digest !== "string" || !styleRequest) return;
                  void begin("/style-template/preview", (r) => ({
                    ...styleRequest,
                    base_draft_revision: r,
                    format_review_ack: digest,
                  }));
                }}
              >
                已核对未判明范围，继续预览
              </button>
              <button
                className="text-button"
                disabled={working}
                onClick={() => {
                  setHeld(null);
                  setStyleRequest(null);
                }}
              >
                保留当前版式
              </button>
            </>
          )}
          {resolve.pending && (
            <button
              className="button secondary"
              disabled={resolve.busy}
              onClick={() => void decide("confirm", true)}
            >
              恢复原变更处理结果
            </button>
          )}
          {resolve.conflict && (
            <p className="notice warning">
              草稿已有新修订，原预览不能覆盖当前稿。保留本次差异，读取最新目录后重新预览。
            </p>
          )}
          {resolve.conflict && (
            <button
              className="text-button"
              onClick={() => {
                setHeld(null);
                void refresh();
              }}
            >
              保留人工内容，读取当前目录后重新预览
            </button>
          )}
        </section>
      )}
      <details onToggle={(e) => setShowHistory(e.currentTarget.open)}>
        <summary>查看目录历史</summary>
        <ResourceState
          {...history}
          hasData={!!history.data}
          onRetry={() => void history.reload()}
        />
        {[...(history.data?.items ?? []), ...more.flatMap((p) => p.items)].map(
          (h) => (
            <div className="review-shortcuts" key={h.id}>
              <span>
                草稿修订 {h.draft_revision} ·{" "}
                {new Date(h.created_at).toLocaleString()}
              </span>
              <button
                className="text-button"
                disabled={locked}
                onClick={() =>
                  void begin("/structure/restore-preview", (r) => ({
                    base_draft_revision: r,
                    structure_version_id: h.id,
                  }))
                }
              >
                预览还原此目录
              </button>
            </div>
          ),
        )}
        {(more.at(-1) ?? history.data)?.next_cursor && (
          <button className="text-button" onClick={() => void nextHistory()}>
            加载更早目录
          </button>
        )}
      </details>
    </div>
  );
}
function Preview({ value }: { value: AuthoringStructurePreview }) {
  return (
    <>
      <div className="structure-diff">
        <div>
          <h4>变更前</h4>
          {value.before
            .filter((n) => !n.deleted)
            .map((n) => (
              <p key={n.section_id}>
                {sectionTitle(
                  value.before_sections[n.section_id],
                  n.section_id,
                )}
              </p>
            ))}
        </div>
        <div>
          <h4>变更后</h4>
          {treeOrder(value.after).map(({ node: n, depth }) => (
            <p style={{ paddingInlineStart: depth * 12 }} key={n.section_id}>
              {n.ordinal + 1}.{" "}
              {sectionTitle(value.after_sections[n.section_id], n.section_id)}
            </p>
          ))}
        </div>
      </div>
      {value.deletion_impact.map((i) => (
        <p className="notice warning" key={i.section_id}>
          将删除：{i.title} · {i.text_characters}字 · {i.rule_ids.length}
          条要求关联 · {i.source_count}处来源 ·{" "}
          {i.plan_version_id ? "含编写计划" : "未建计划"}
          。要求本身及历史不会因此消失。
        </p>
      ))}
      <FormatReport value={value.format_report} />
      <details>
        <summary>核对固定变更内容与身份</summary>
        <pre className="structure-json">
          {JSON.stringify(
            {
              before_sections: value.before_sections,
              after_sections: value.after_sections,
              created_ids: value.created_ids,
            },
            null,
            2,
          )}
        </pre>
      </details>
    </>
  );
}
function sectionTitle(value: unknown, fallback: string) {
  if (value && typeof value === "object" && "attrs" in value) {
    const a = value.attrs;
    if (
      a &&
      typeof a === "object" &&
      "title" in a &&
      typeof a.title === "string"
    )
      return a.title;
  }
  return `章节 ${fallback.slice(0, 8)}`;
}
function FormatReport({
  value,
}: {
  value: AuthoringStructurePreview["format_report"];
}) {
  const report = record(value);
  return (
    <>
      <p className="small-note">
        {typeof report.notice === "string"
          ? report.notice
          : "格式范围由服务器核对；此预览不代表要求已满足。"}
      </p>
      <details>
        <summary>查看版式范围与冲突详情</summary>
        <pre className="structure-json">{JSON.stringify(value, null, 2)}</pre>
      </details>
    </>
  );
}
function TemplateSelection({
  tree,
  bidId,
  memberId,
  disabled,
  onDirectory,
  onStyle,
}: {
  tree: AuthoringTreeView;
  bidId: string;
  memberId: string;
  disabled: boolean;
  onDirectory: (
    id: string,
    matches: { template_key: string; section_id: string }[],
  ) => void;
  onStyle: (
    id: string,
    bindings: AuthoringStyleApplyPreview["format_bindings"],
  ) => void;
}) {
  const [bindings, setBindings] = useKnowledgeInput<
    AuthoringStyleApplyPreview["format_bindings"]
  >(
    `tender:knowledge:${memberId}:format-bindings:${tree.draft_id}`,
    Array.isArray(tree.metadata.format_bindings)
      ? (tree.metadata
          .format_bindings as AuthoringStyleApplyPreview["format_bindings"])
      : [],
  );
  return (
    <details>
      <summary>目录模板与版式模板 · 分别固定版本</summary>
      <TemplateChoice
        kind="outline"
        tree={tree}
        memberId={memberId}
        id={tree.directory_template_version_id}
        disabled={disabled}
        onApply={onDirectory}
      />
      <AuthoringFormatBindings
        bidId={bidId}
        bindings={bindings}
        disabled={disabled}
        onChange={setBindings}
      />
      <TemplateChoice
        kind="layout"
        tree={tree}
        memberId={memberId}
        id={tree.style_template_version_id}
        disabled={disabled}
        onApply={(id) => onStyle(id, bindings)}
      />
    </details>
  );
}
function TemplateChoice({
  kind,
  tree,
  memberId,
  id,
  disabled,
  onApply,
}: {
  kind: "outline" | "layout";
  tree: AuthoringTreeView;
  memberId: string;
  id: string;
  disabled: boolean;
  onApply: (
    id: string,
    matches: { template_key: string; section_id: string }[],
  ) => void;
}) {
  const catalog = useResource<AuthoringTemplateCatalog>(
    `/authoring/templates?kind=${kind}`,
  );
  const [more, setMore] = useState<AuthoringTemplateCatalog[]>([]);
  const [selected, setSelected] = useState(id);
  const [matches, setMatches] = useState<Record<string, string>>({});
  const [savedNotice, setSavedNotice] = useState("");
  const detail = useResource<AuthoringTemplateVersionView>(
    `/authoring/template-versions/${selected}`,
  );
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const items = [
    ...new Map(
      [
        ...(catalog.data?.items ?? []),
        ...more.flatMap((p) => p.items),
        ...(detail.data ? [detail.data] : []),
      ].map((v) => [v.id, v]),
    ).values(),
  ];
  async function next() {
    const last = more.at(-1) ?? catalog.data;
    if (!last?.next_cursor || busy) return;
    setBusy(true);
    try {
      const r = await api<AuthoringTemplateCatalog>(
        `/authoring/templates?kind=${kind}&after=${last.next_cursor}`,
      );
      setMore((old) => [...old, r.data]);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  const label = kind === "outline" ? "目录模板" : "版式模板";
  return (
    <fieldset disabled={disabled}>
      <legend>{label}</legend>
      <p className="small-note">
        {kind === "outline"
          ? "目录模板影响章节结构；预览默认保留现有人工章节，不自动删除或匹配。"
          : "版式模板影响纸张、字体、封面与页眉页脚；与目录模板独立。"}
      </p>
      <ResourceState
        {...catalog}
        hasData={!!catalog.data}
        onRetry={() => void catalog.reload()}
      />
      <label>
        选择{label}固定版本
        <select
          value={selected}
          onChange={(e) => {
            setSelected(e.target.value);
            setMatches({});
          }}
        >
          {!items.some((i) => i.id === selected) && (
            <option value={selected}>正在读取当前固定版本</option>
          )}
          {items
            .filter((i) => i.kind === kind)
            .map((i) => (
              <option value={i.id} key={i.id}>
                {i.name} · 版本{i.revision}
                {i.id === id ? "（当前）" : ""}
              </option>
            ))}
        </select>
      </label>
      {(more.at(-1) ?? catalog.data)?.next_cursor && (
        <button
          type="button"
          className="text-button"
          disabled={busy}
          onClick={() => void next()}
        >
          加载更多{label}
        </button>
      )}
      <ResourceState
        {...detail}
        hasData={!!detail.data}
        onRetry={() => void detail.reload()}
      />
      {detail.data && (
        <>
          <p className="small-note">
            {detail.data.name} · 版本{detail.data.revision} ·{" "}
            {selected === id ? "当前固定版本" : "尚未应用"}
          </p>
          <details>
            <summary>查看{label}配置</summary>
            <pre className="structure-json">
              {JSON.stringify(detail.data.config, null, 2)}
            </pre>
          </details>
          {detail.data.previous_version_id && (
            <button
              type="button"
              className="text-button"
              onClick={() => setSelected(detail.data!.previous_version_id!)}
            >
              查看该模板的上一版本
            </button>
          )}
          {kind === "outline" &&
            "nodes" in detail.data.config &&
            detail.data.config.nodes.map((n) => (
              <label key={n.key}>
                匹配“{n.title}”到当前章
                <select
                  value={matches[n.key] ?? ""}
                  onChange={(e) =>
                    setMatches((old) => ({ ...old, [n.key]: e.target.value }))
                  }
                >
                  <option value="">沿用同模板映射或新增，保留其他人工章</option>
                  {tree.nodes
                    .filter((v) => !v.deleted)
                    .map((v) => (
                      <option key={v.section_id} value={v.section_id}>
                        {v.title}
                      </option>
                    ))}
                </select>
              </label>
            ))}
          <AuthoringTemplateEditor
            key={detail.data.id}
            template={detail.data}
            etag={detail.etag}
            memberId={memberId}
            disabled={disabled}
            onSaved={(v) => {
              setSelected(v.id);
              setMatches({});
              setSavedNotice(
                "模板固定版本已保存，尚未应用当前稿。请核对后预览应用。",
              );
              void catalog.reload();
            }}
          />
          {savedNotice && <p role="status">{savedNotice}</p>}
          <button
            type="button"
            className="button secondary"
            onClick={() =>
              onApply(
                selected,
                Object.entries(matches)
                  .filter(([, v]) => v)
                  .map(([template_key, section_id]) => ({
                    template_key,
                    section_id,
                  })),
              )
            }
          >
            预览应用{label}
          </button>
        </>
      )}
      <ErrorNotice error={error} />
    </fieldset>
  );
}
