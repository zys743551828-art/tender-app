import { lazy, Suspense, useRef, useState } from "react";
import { supportsApi } from "./api";
import type { ApiResult } from "./api";
import type { Bid, DraftView, TechnicalChapterLayoutView } from "./contracts";
import { ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import {
  authoringInteger,
  type FixedAuthoringChapter,
} from "./packageAuthoringInputProtocol";
import { executionId } from "./executionInputValidation";
import { useResource } from "./useResource";
import { TechnicalChapterTemplates } from "./TechnicalChapterTemplates";
import { readTechnicalChapterLayout } from "./technicalChapterLayout";

const PackageAuthoringTemplateEditor = lazy(() =>
  import("./PackageAuthoringTemplateEditor").then(
    ({ PackageAuthoringTemplateEditor }) => ({
      default: PackageAuthoringTemplateEditor,
    }),
  ),
);

const unsupportedReasonLabels: Record<
  TechnicalChapterLayoutView["unsupported_reasons"][number],
  string
> = {
  saved_chapter_plans: "这份草稿已有章节计划（也可能在别章）。",
  bound_project_format:
    "当前安装或草稿组合暂不支持这份草稿的项目版式绑定；已保存的版式不变。",
  word_import_sources: "这份草稿记录了 Word 导入来源。",
};

type Props = {
  bidId: string;
  memberId: string;
  draft: DraftView;
  sectionId: string;
  disabled: boolean;
  prepare: () => Promise<ApiResult<DraftView> | null>;
  onPreparing: (busy: boolean) => void;
  onOpenLayoutTemplates: (trigger: HTMLButtonElement) => void;
};

export function TechnicalBidChapter({
  bidId,
  memberId,
  draft,
  sectionId,
  disabled,
  prepare,
  onPreparing,
  onOpenLayoutTemplates,
}: Props) {
  const [showForm, setShowForm] = useState(false);
  const [savedForScope, setSavedForScope] = useState(false);
  const [scope, setScope] = useState<FixedAuthoringChapter | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [layoutResult, setLayoutResult] =
    useState<TechnicalChapterLayoutView | null>(null);
  const [templateIds, setTemplateIds] = useState<string[]>([]);
  const waiting = useRef(false);
  const bid = useResource<Bid>(
    scope && !savedForScope ? "/bids/" + bidId : null,
  );
  const section = draft.sections.find((item) => item.id === sectionId);
  const current =
    !!scope &&
    draft.id === scope.draft_id &&
    draft.snapshot_id === scope.snapshot_id &&
    draft.revision === scope.base_draft_revision &&
    section?.id === scope.section_id &&
    section.revision === scope.base_section_revision;
  const currentLayout =
    layoutResult?.snapshot_id === draft.snapshot_id &&
    layoutResult.draft_revision === draft.revision &&
    layoutResult.section_revision === section?.revision
      ? layoutResult
      : null;
  const currentLayoutBlock =
    currentLayout &&
    currentLayout.state !== "plain_draft" &&
    currentLayout.state !== "structured_layout_rechecked"
      ? currentLayout
      : null;
  if (!supportsApi("GET", "/authoring/package-input-capabilities")) return null;

  async function open(rebind = false) {
    if (disabled || waiting.current) return;
    if (scope && !rebind && !savedForScope && !current) {
      // Keep the disabled old form visible; never substitute a newer revision.
      setShowForm(true);
      return;
    }
    waiting.current = true;
    setPreparing(true);
    setError(null);
    setLayoutResult(null);
    onPreparing(true);
    try {
      let selected = scope && !rebind && !savedForScope ? scope : null;
      if (!selected) {
        const head = await prepare();
        const target = head?.data.sections.find(
          (item) => item.id === sectionId,
        );
        if (
          !head?.etag ||
          head.data.id !== draft.id ||
          head.data.bid_id !== bidId ||
          !executionId(bidId) ||
          !executionId(head.data.id) ||
          !executionId(head.data.snapshot_id) ||
          !authoringInteger(head.data.revision) ||
          !target ||
          !executionId(target.id) ||
          !authoringInteger(target.revision)
        )
          throw new Error("未核对本章已保存版本，不能建立编写模板。");
        selected = {
          draft_id: head.data.id,
          snapshot_id: head.data.snapshot_id,
          base_draft_revision: head.data.revision,
          section_id: target.id,
          base_section_revision: target.revision,
        };
      }
      const layout = await readTechnicalChapterLayout(bidId, selected);
      setLayoutResult(layout);
      if (
        layout.state !== "plain_draft" &&
        layout.state !== "structured_layout_rechecked"
      ) {
        setShowForm(false);
        return;
      }
      setScope(selected);
      setSavedForScope(false);
      setShowForm(true);
    } catch (failure) {
      setError(failure);
    } finally {
      waiting.current = false;
      setPreparing(false);
      onPreparing(false);
    }
  }

  return (
    <section className="panel" aria-label="从固定依据生成本章技术标候选">
      <p className="small-note">
        从当前已保存章节选择稳定文字节点、项目资料、原文要求和已确认事实。先保存编写模板，再明确手动运行；不使用通用批次替代，不自动采纳。
      </p>
      {!showForm && (
        <button
          type="button"
          className="button secondary"
          disabled={disabled || preparing}
          onClick={() => void open()}
        >
          {preparing
            ? "正在核对已保存正文…"
            : savedForScope
              ? "重新准备一份本章候选"
              : "准备生成本章技术标候选"}
        </button>
      )}
      <ErrorNotice error={error} />
      {currentLayoutBlock && (
        <div className="notice warning" role="status">
          {currentLayoutBlock.state === "structure_not_supported" ? (
            <>
              <p>当前草稿不能准备固定编写，未打开生成表单，也未启动模型。</p>
              <ul>
                {currentLayoutBlock.unsupported_reasons.map((reason) => (
                  <li key={reason}>
                    {reason !== "saved_chapter_plans"
                      ? unsupportedReasonLabels[reason]
                      : currentLayoutBlock.plan_state === "target_stale"
                        ? `本章计划修订 ${currentLayoutBlock.section_plan_revision} 仍对照旧正文，不随正文自动更新。`
                        : "这份草稿已有章节计划（也可能在别章），当前工作台未配置固定编写的计划核验。"}
                  </li>
                ))}
              </ul>
              {currentLayoutBlock.ordinary_structure_protected ? (
                <p>
                  已有固定整包修订受保护。请保留原稿和已存依据；若需继续固定编写，另行准备符合条件的草稿。
                </p>
              ) : (
                <p>
                  已存内容和依据未被改动。可
                  <a href="#authoring-current-section">返回本章正文</a>
                  ，有编辑权限时可按原计划手工编写。如仍需固定编写，请保留原稿，另行准备符合条件的草稿。
                </p>
              )}
            </>
          ) : (
            <>
              <p>
                版式核对未完成或当前依据已变化。为避免采用之后无法构建内部
                Word，这里未打开生成表单，也未启动模型。
              </p>
              {currentLayoutBlock.ordinary_structure_protected ? (
                <p>
                  当前草稿已有受保护的固定整包修订，不能通过普通版式操作补做确认。请保留原稿，按当前要求另行准备草稿或人工核对。
                </p>
              ) : (
                <p>
                  <button
                    type="button"
                    className="text-button"
                    aria-controls="authoring-layout-templates"
                    disabled={disabled || preparing}
                    onClick={({ currentTarget }) =>
                      onOpenLayoutTemplates(currentTarget)
                    }
                  >
                    打开目录模板与版式模板
                  </button>
                  ，沿用实际招标要求完成已有核对与确认，再回来准备本章。此步骤不判定暗标、版面或整包是否通过。
                </p>
              )}
            </>
          )}
        </div>
      )}
      {showForm && currentLayout?.plan_state === "requires_fixed_evidence" && (
        <p className="small-note" role="status">
          {currentLayout.section_plan_revision === null
            ? "原草稿中其他章节的计划会保留。"
            : `原本章计划修订 ${currentLayout.section_plan_revision} 会保留；固定输入仍须核对计划关联的已选依据包原页和已确认要求。`}
          只向模型提供核验后的关联，不发送计划正文、人工计划页数或待核事实。采用正文不会自动更新或批准计划。
        </p>
      )}
      {scope && !savedForScope && (
        <div hidden={!showForm}>
          <p>
            草稿修订 {scope.base_draft_revision} · 本章修订{" "}
            {scope.base_section_revision}
          </p>
          {!current && (
            <div className="notice warning">
              <p>
                草稿或章节已变化。原编写表单保留，但不能保存此旧修订的生成入口。
              </p>
              <button
                className="button secondary"
                type="button"
                disabled={disabled || preparing}
                onClick={() => void open(true)}
              >
                重新读取本章，选择新输入
              </button>
            </div>
          )}
          <ResourceState
            {...bid}
            hasData={!!bid.data}
            onRetry={() => void bid.reload()}
          />
          {bid.data?.id === bidId && bid.etag && (
            <Suspense fallback={<p role="status">正在打开本章固定编写表单…</p>}>
              <PackageAuthoringTemplateEditor
                key={scope.snapshot_id}
                bidId={bidId}
                memberId={memberId}
                template={null}
                etag={bid.etag}
                targetChapter={scope}
                formIdentity={
                  "technical-chapter:" +
                  scope.draft_id +
                  ":" +
                  scope.section_id +
                  ":" +
                  scope.snapshot_id
                }
                writesDisabled={disabled || !current}
                onClose={() => setShowForm(false)}
                onSaved={(item) => {
                  if (item.bid_id !== bidId || !executionId(item.id)) {
                    setError(
                      new Error("编写模板回执与本项目不一致，未打开其他模板。"),
                    );
                    return;
                  }
                  setTemplateIds((items) => [
                    item.id,
                    ...items.filter((id) => id !== item.id),
                  ]);
                  setSavedForScope(true);
                  setShowForm(false);
                }}
              />
            </Suspense>
          )}
        </div>
      )}
      <TechnicalChapterTemplates
        key={JSON.stringify([memberId, bidId, draft.id, sectionId])}
        bidId={bidId}
        draft={draft}
        sectionId={sectionId}
        navigationDisabled={disabled || preparing || showForm}
      />
      {templateIds.length > 0 && (
        <div role="status">
          固定编写模板已保存，未运行。
          <ul>
            {templateIds.map((templateId) => (
              <li key={templateId}>
                <a
                  href={"/bids/" + bidId + "/tasks?task_template=" + templateId}
                >
                  打开本次模板，核对后手动运行
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
