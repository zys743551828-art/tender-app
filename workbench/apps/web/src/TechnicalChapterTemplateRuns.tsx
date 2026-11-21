import { useCallback } from "react";
import { ErrorNotice } from "./components";
import type {
  TechnicalChapterRunPage,
  TechnicalChapterTemplateItem,
} from "./contracts";
import {
  exactKeys,
  executionId,
  recordObject,
} from "./executionInputValidation";
import { authoringTimestamp } from "./packageAuthoringInputProtocol";
import { useAuthoringCaptureRead } from "./useAuthoringCaptureRead";

const stageText: Record<
  TechnicalChapterRunPage["items"][number]["stage"],
  string
> = {
  queued: "已受理，尚在排队",
  running: "运行中",
  cancel_requested: "已请求取消，结果待确认",
  awaiting_publication: "候选已生成，待发布",
  candidate_published: "候选已发布，不代表已采纳",
  failed: "运行或候选发布失败",
  cancelled: "已取消",
  superseded: "依据变化，未发布候选",
  reconciliation_required: "模型费用或回执待核对，不应重复运行",
  unverified: "状态待核，尚无可确认结果",
};

function checked(
  value: unknown,
  bidId: string,
  draftId: string,
  sectionId: string,
  template: TechnicalChapterTemplateItem,
) {
  const invalid = () =>
    new Error(
      "固定运行记录与所选章节、模板版本或输入摘要不一致，未展示其他记录。",
    );
  if (
    !recordObject(value) ||
    !exactKeys(value, [
      "available",
      "bid_id",
      "draft_id",
      "section_id",
      "template_id",
      "template_version_id",
      "template_digest",
      "input_id",
      "input_digest",
      "has_more",
      "items",
    ]) ||
    value.bid_id !== bidId ||
    value.draft_id !== draftId ||
    value.section_id !== sectionId ||
    value.template_id !== template.template_id ||
    value.template_version_id !== template.template_version_id ||
    value.template_digest !== template.template_digest ||
    value.input_id !== template.input_id ||
    value.input_digest !== template.input_digest ||
    typeof value.available !== "boolean" ||
    typeof value.has_more !== "boolean" ||
    !Array.isArray(value.items) ||
    value.items.length > 3 ||
    (!value.available && (value.items.length || value.has_more)) ||
    (value.has_more && value.items.length !== 3)
  )
    throw invalid();
  const runIds = new Set<string>();
  for (const item of value.items) {
    if (
      !recordObject(item) ||
      !exactKeys(item, ["run_id", "recorded_at", "stage"]) ||
      !executionId(item.run_id) ||
      runIds.has(item.run_id) ||
      !authoringTimestamp(item.recorded_at) ||
      typeof item.stage !== "string" ||
      !Object.hasOwn(stageText, item.stage)
    )
      throw invalid();
    runIds.add(item.run_id);
  }
  return value as unknown as TechnicalChapterRunPage;
}

export function TechnicalChapterTemplateRuns({
  bidId,
  draftId,
  sectionId,
  template,
  navigationDisabled,
}: {
  bidId: string;
  draftId: string;
  sectionId: string;
  template: TechnicalChapterTemplateItem;
  navigationDisabled: boolean;
}) {
  const verify = useCallback(
    (value: unknown) => checked(value, bidId, draftId, sectionId, template),
    [bidId, draftId, sectionId, template],
  );
  const path = `/bids/${bidId}/drafts/${draftId}/sections/${sectionId}/technical-authoring-templates/${template.template_version_id}/runs`;
  const read = useAuthoringCaptureRead(path, verify);
  const page = read.ready ? read.value : null;
  return (
    <section aria-label="此模板版本的固定运行记录">
      {read.busy && <p role="status">正在核对固定运行记录…</p>}
      <ErrorNotice error={read.error} />
      {page && !page.available && (
        <p role="status">当前环境无法核对固定运行记录，不能当作未运行。</p>
      )}
      {page?.available && (
        <>
          <p className="small-note">
            仅查看模板第 {template.template_revision} 版与此固定输入的运行记录。
            候选发布不等于已采用、批准或形成可提交文件。
          </p>
          {page.items.length ? (
            <ul>
              {page.items.map((item) => (
                <li key={item.run_id}>
                  <time dateTime={item.recorded_at}>
                    {new Date(item.recorded_at).toLocaleString("zh-CN")}
                  </time>
                  {" · "}
                  {stageText[item.stage]}
                  {!navigationDisabled && item.stage !== "unverified" && (
                    <>
                      {" "}
                      <a href={`/bids/${bidId}/tasks?run=${item.run_id}`}>
                        在任务页核对这次运行
                      </a>
                    </>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="small-note">
              未读到与这个模板版本和固定输入相符的运行记录。
            </p>
          )}
          {page.has_more && (
            <p className="small-note">
              这里只列最近的 3 条，更多请到任务页查看。
            </p>
          )}
        </>
      )}
      <button
        type="button"
        className="text-button"
        disabled={read.busy}
        onClick={() => void read.reload()}
      >
        刷新此版本运行记录
      </button>
    </section>
  );
}
