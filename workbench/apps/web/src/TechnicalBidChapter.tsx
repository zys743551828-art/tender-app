import { lazy, Suspense, useRef, useState } from "react";
import { supportsApi } from "./api";
import type { ApiResult } from "./api";
import type { Bid, DraftView } from "./contracts";
import { ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import {
  authoringInteger,
  type FixedAuthoringChapter,
} from "./packageAuthoringInputProtocol";
import { executionId } from "./executionInputValidation";
import { useResource } from "./useResource";
import { TechnicalChapterTemplates } from "./TechnicalChapterTemplates";

const PackageAuthoringTemplateEditor = lazy(() =>
  import("./PackageAuthoringTemplateEditor").then(
    ({ PackageAuthoringTemplateEditor }) => ({
      default: PackageAuthoringTemplateEditor,
    }),
  ),
);

type Props = {
  bidId: string;
  memberId: string;
  draft: DraftView;
  sectionId: string;
  disabled: boolean;
  prepare: () => Promise<ApiResult<DraftView> | null>;
  onPreparing: (busy: boolean) => void;
};

export function TechnicalBidChapter({
  bidId,
  memberId,
  draft,
  sectionId,
  disabled,
  prepare,
  onPreparing,
}: Props) {
  const [showForm, setShowForm] = useState(false);
  const [savedForScope, setSavedForScope] = useState(false);
  const [scope, setScope] = useState<FixedAuthoringChapter | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState<unknown>(null);
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
  if (!supportsApi("GET", "/authoring/package-input-capabilities")) return null;

  async function open(rebind = false) {
    if (disabled || waiting.current) return;
    if (scope && !rebind && !savedForScope) {
      setShowForm(true);
      return;
    }
    waiting.current = true;
    setPreparing(true);
    setError(null);
    onPreparing(true);
    try {
      const head = await prepare();
      const target = head?.data.sections.find((item) => item.id === sectionId);
      if (
        !head?.etag ||
        head.data.id !== draft.id ||
        head.data.bid_id !== bidId ||
        !executionId(head.data.id) ||
        !executionId(head.data.snapshot_id) ||
        !authoringInteger(head.data.revision) ||
        !target ||
        !executionId(target.id) ||
        !authoringInteger(target.revision)
      )
        throw new Error("未核对本章已保存版本，不能建立编写模板。");
      setScope({
        draft_id: head.data.id,
        snapshot_id: head.data.snapshot_id,
        base_draft_revision: head.data.revision,
        section_id: target.id,
        base_section_revision: target.revision,
      });
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
