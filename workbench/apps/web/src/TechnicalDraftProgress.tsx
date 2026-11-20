import { useCallback, useState } from "react";
import { supportsApi } from "./api";
import { ErrorNotice } from "./components";
import type { AuthoringTreeView } from "./contracts";
import { executionId } from "./executionInputValidation";
import {
  isWritingGap,
  readTechnicalDraftProgress,
  type chapterBodyState,
} from "./technicalDraftProgress";
import { useAuthoringCaptureRead } from "./useAuthoringCaptureRead";

const labels: Record<ReturnType<typeof chapterBodyState>, string> = {
  body_text: "有已保存的正文文字",
  headings_only: "仅有段内标题，未看到正文文字",
  no_readable_body: "未看到可读正文",
  objects_to_review: "有表格或图片，待人工查看",
};
const PAGE_SIZE = 20;

type Props = {
  bidId: string;
  tree: AuthoringTreeView;
  navigationDisabled: boolean;
  onOpenSection: (sectionId: string) => Promise<void>;
};

export function TechnicalDraftProgress(props: Props) {
  const [open, setOpen] = useState(false);
  const { bidId, tree } = props;
  const path = `/bids/${bidId}/work-contexts/draft_snapshot/${tree.snapshot_id}`;
  if (
    !executionId(bidId) ||
    !executionId(tree.draft_id) ||
    !executionId(tree.snapshot_id) ||
    !supportsApi("GET", path)
  )
    return null;
  return (
    <section aria-label="当前草稿的已存正文进度">
      <button
        type="button"
        className="text-button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {open ? "收起已存正文进度" : "查看本稿哪些章节还空白"}
      </button>
      {open && <SavedProgressContents key={path} path={path} {...props} />}
    </section>
  );
}

function SavedProgressContents({
  bidId,
  tree,
  navigationDisabled,
  onOpenSection,
  path,
}: Props & { path: string }) {
  const [onlyGaps, setOnlyGaps] = useState(false);
  const [page, setPage] = useState(0);
  const verify = useCallback(
    (value: unknown) => readTechnicalDraftProgress(value, bidId, tree),
    [bidId, tree],
  );
  const read = useAuthoringCaptureRead(path, verify);
  const rows = read.ready ? read.value : null;
  const gaps = rows?.filter(({ state }) => isWritingGap(state)) ?? [];
  const shown = onlyGaps ? gaps : (rows ?? []);
  const pages = Math.max(1, Math.ceil(shown.length / PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  return (
    <>
      <p className="small-note">
        只看草稿修订 {tree.draft_revision} 的已保存正文，不包含未保存编辑。
        文字存在不等于回答了要求、来源有效、内容已审核或文件可提交。
      </p>
      {read.busy && <p role="status">正在核对当前草稿和各章修订…</p>}
      <ErrorNotice error={read.error} />
      {rows && (
        <>
          <p className="small-note">
            共 {rows.length} 章；{gaps.length} 章为空白或仅标题，{" "}
            {rows.filter(({ state }) => state === "objects_to_review").length}{" "}
            章有表图需人工查看。
          </p>
          {gaps.length > 0 && (
            <>
              <button
                type="button"
                className="button secondary"
                disabled={navigationDisabled}
                onClick={() => void onOpenSection(gaps[0].id)}
              >
                定位首个空白或仅标题章
              </button>
              <label className="small-note">
                <input
                  type="checkbox"
                  checked={onlyGaps}
                  onChange={(e) => {
                    setOnlyGaps(e.target.checked);
                    setPage(0);
                  }}
                />
                只看空白或仅标题章
              </label>
            </>
          )}
          {shown.length > 0 && (
            <ul>
              {shown
                .slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE)
                .map((row) => (
                  <li key={row.id}>
                    <button
                      className="text-button"
                      type="button"
                      disabled={navigationDisabled}
                      onClick={() => void onOpenSection(row.id)}
                    >
                      定位：{row.title}
                    </button>{" "}
                    · 修订 {row.revision} · {labels[row.state]}
                  </li>
                ))}
            </ul>
          )}
          {pages > 1 && (
            <div className="review-shortcuts">
              <button
                type="button"
                className="text-button"
                disabled={current === 0}
                onClick={() => setPage(current - 1)}
              >
                上一页章节
              </button>
              <span>
                第 {current + 1} / {pages} 页
              </span>
              <button
                type="button"
                className="text-button"
                disabled={current + 1 === pages}
                onClick={() => setPage(current + 1)}
              >
                下一页章节
              </button>
            </div>
          )}
        </>
      )}
      <button
        type="button"
        className="text-button"
        disabled={read.busy}
        onClick={() => void read.reload()}
      >
        重新核对本稿正文
      </button>
    </>
  );
}
