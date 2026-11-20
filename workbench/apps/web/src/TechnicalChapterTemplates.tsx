import { useCallback, useState } from "react";
import { supportsApi } from "./api";
import { ErrorNotice } from "./components";
import type { DraftView, TechnicalChapterTemplatePage } from "./contracts";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
import { authoringInteger } from "./packageAuthoringInputProtocol";
import { useAuthoringCaptureRead } from "./useAuthoringCaptureRead";

function checkedPage(
  value: unknown,
  bid: string,
  draft: string,
  section: string,
) {
  const failure = () =>
    new Error(
      "模板目录的项目、草稿、章节或固定输入身份不一致，未显示其他记录。",
    );
  if (
    !recordObject(value) ||
    !exactKeys(value, [
      "available",
      "bid_id",
      "draft_id",
      "has_more",
      "items",
      "observed_draft_revision",
      "observed_section_revision",
      "observed_snapshot_id",
      "section_id",
    ]) ||
    value.bid_id !== bid ||
    value.draft_id !== draft ||
    value.section_id !== section ||
    !executionId(value.observed_snapshot_id) ||
    !authoringInteger(value.observed_draft_revision) ||
    !authoringInteger(value.observed_section_revision) ||
    typeof value.available !== "boolean" ||
    typeof value.has_more !== "boolean" ||
    !Array.isArray(value.items) ||
    value.items.length > 12 ||
    (!value.available && (value.items.length || value.has_more)) ||
    (value.has_more && value.items.length !== 12)
  )
    throw failure();
  const templates = new Set<string>();
  for (const row of value.items) {
    if (
      !recordObject(row) ||
      !exactKeys(row, [
        "bound_to_observed_chapter",
        "input_digest",
        "input_draft_revision",
        "input_id",
        "input_section_revision",
        "input_snapshot_id",
        "name",
        "paused",
        "template_digest",
        "template_id",
        "template_revision",
        "template_version_id",
      ]) ||
      !executionId(row.template_id) ||
      templates.has(row.template_id) ||
      !executionId(row.template_version_id) ||
      !authoringInteger(row.template_revision) ||
      !executionSha(row.template_digest) ||
      typeof row.name !== "string" ||
      !row.name.trim() ||
      Array.from(row.name).length > 200 ||
      typeof row.paused !== "boolean" ||
      !executionId(row.input_id) ||
      !executionSha(row.input_digest) ||
      !executionId(row.input_snapshot_id) ||
      !authoringInteger(row.input_draft_revision) ||
      !authoringInteger(row.input_section_revision) ||
      typeof row.bound_to_observed_chapter !== "boolean" ||
      (row.bound_to_observed_chapter &&
        (row.input_snapshot_id !== value.observed_snapshot_id ||
          row.input_draft_revision !== value.observed_draft_revision ||
          row.input_section_revision !== value.observed_section_revision))
    )
      throw failure();
    templates.add(row.template_id);
  }
  return value as unknown as TechnicalChapterTemplatePage;
}

export function TechnicalChapterTemplates({
  bidId,
  draft,
  sectionId,
  navigationDisabled,
}: {
  bidId: string;
  draft: DraftView;
  sectionId: string;
  navigationDisabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const canRead =
    draft.bid_id === bidId && [bidId, draft.id, sectionId].every(executionId);
  const path = `/bids/${bidId}/drafts/${draft.id}/sections/${sectionId}/technical-authoring-templates`;
  const supported = canRead && supportsApi("GET", path);
  const validate = useCallback(
    (value: unknown) => checkedPage(value, bidId, draft.id, sectionId),
    [bidId, draft.id, sectionId],
  );
  const read = useAuthoringCaptureRead(
    supported && open ? path : null,
    validate,
  );
  if (!supported) return null;
  const page = read.ready ? read.value : null;
  const section = draft.sections.find((item) => item.id === sectionId);
  const matched =
    page &&
    section &&
    page.observed_snapshot_id === draft.snapshot_id &&
    page.observed_draft_revision === draft.revision &&
    page.observed_section_revision === section.revision;
  return (
    <section aria-label="本章已保存的固定编写模板">
      <button
        type="button"
        className="text-button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {open ? "收起本章固定编写模板" : "查看本章已保存的固定编写模板"}
      </button>
      {open && (
        <>
          {read.busy && <p role="status">正在核对本章固定编写模板…</p>}
          <ErrorNotice error={read.error} />
          {page && !matched && (
            <p role="status">
              读到的草稿或章节版本已变化，请先刷新草稿；未显示旧入口。
            </p>
          )}
          {matched && page && !page.available && (
            <p role="status">
              当前环境未开放固定编写模板目录，不能判断是否有记录。
            </p>
          )}
          {matched && page?.available && (
            <>
              <p className="small-note">
                这里只读取与本章绑定的模板，不判断运行、采用状态或当前依据资格。
                任务页会重新读取模板的当前版本，不会自动运行。
              </p>
              {page.items.length ? (
                <ul>
                  {page.items.map((item) => (
                    <li key={item.template_id}>
                      <strong>{item.name}</strong> · 模板第{" "}
                      {item.template_revision} 版
                      {item.paused ? " · 已暂停后续触发" : ""} ·{" "}
                      {item.bound_to_observed_chapter
                        ? "绑定本次已保存章节版本"
                        : "绑定早期或不同正文版本"}{" "}
                      （草稿修订 {item.input_draft_revision}，章节修订{" "}
                      {item.input_section_revision}）
                      {!navigationDisabled && (
                        <>
                          {" "}
                          <a
                            href={`/bids/${bidId}/tasks?task_template=${item.template_id}`}
                          >
                            到任务页核对模板当前版本
                          </a>
                        </>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="small-note">
                  没有读到与本章绑定的已保存固定模板。
                </p>
              )}
              {page.has_more && (
                <p className="small-note">
                  此处只列部分匹配的模板，更多记录请到任务页查看。
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
            刷新本章模板目录
          </button>
        </>
      )}
    </section>
  );
}
