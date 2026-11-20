import { useState } from "react";
import { EvidenceLinks } from "./EvidenceLinks";
import type {
  AuthoringTreeView,
  BidPackageStoredView,
  PackageRequirementInventoryView,
} from "./contracts";
import type { technicalOutline } from "./technicalBidOutlinePlan";
import {
  frozenOutlineAuthority,
  technicalDraftTrace,
  type TechnicalDraftTraceRow,
} from "./technicalDraftTraceModel";

type Outline = ReturnType<typeof technicalOutline>;
const pageSize = 15;
const chapterPreviewLimit = 8;
const states = {
  matched_reference: "保存引用与要求原页身份相符",
  check_reference: "已关联章节，当前要求原页引用待核",
  old_plan: "仅有旧计划关联，正文改动后待重核",
  unlinked: "尚无保存的章节关联",
} satisfies Record<TechnicalDraftTraceRow["state"], string>;
const origins = {
  body: "保存正文",
  plan: "同版计划",
  old_plan: "旧计划",
} as const;

export function TechnicalDraftTrace({
  inventory,
  authority,
  outline,
  bidId,
  tree,
  navigationDisabled,
  onOpenSection,
}: {
  inventory: PackageRequirementInventoryView;
  authority: BidPackageStoredView;
  outline: Outline;
  bidId: string;
  tree: AuthoringTreeView | null;
  navigationDisabled: boolean;
  onOpenSection: (sectionId: string) => Promise<void>;
}) {
  const [page, setPage] = useState(0);
  const scope = frozenOutlineAuthority(authority);
  const rows = tree
    ? technicalDraftTrace(bidId, tree, outline.rows, scope)
    : [];
  const pages = Math.max(1, Math.ceil(outline.rows.length / pageSize));
  const current = Math.min(page, pages - 1);
  const traced = rows.filter((row) => row.state === "matched_reference").length;
  return (
    <details>
      <summary>技术要求与已存章节对照（{outline.rows.length}）</summary>
      <p className="small-note">
        清单修订 {inventory.manifest.revision}
        {tree ? ` · 草稿修订 ${tree.draft_revision}` : " · 草稿尚待核对"}。
        仅对照已保存的章节关联和所选依据包的原页标识，不判断正文是否落实条款或当前依据是否仍有效，不能当作覆盖率或审批。
      </p>
      {tree ? (
        <p className="small-note">
          {traced} 条的保存引用身份与本清单相符，{rows.length - traced}{" "}
          条待关联或复核；另有 {outline.pending}{" "}
          项未确认或未分类，未纳入此对照。
        </p>
      ) : (
        <p className="small-note">
          当前保存草稿版本未核对，暂不展示章节关联或引用结论。
        </p>
      )}
      {!scope.length && (
        <p className="small-note">
          所选依据包没有可对应的固定解析，暂不打开原页。
        </p>
      )}
      <ul>
        {outline.rows
          .slice(current * pageSize, (current + 1) * pageSize)
          .map((rule, index) => {
            const row = rows[current * pageSize + index];
            return (
              <li key={rule.ruleId}>
                <p>{rule.statement}</p>
                <p className="small-note">
                  目录建议：
                  {outline.chapters
                    .filter((chapter) => rule.suggested.includes(chapter.key))
                    .map((chapter) => chapter.title)
                    .join("、") || "待人工定位"}
                </p>
                {row && (
                  <>
                    <p>{states[row.state]}</p>
                    {row.chapters.length > 0 && (
                      <ul>
                        {row.chapters
                          .slice(0, chapterPreviewLimit)
                          .map((chapter) => (
                            <li key={chapter.sectionId}>
                              <button
                                className="text-button"
                                type="button"
                                disabled={navigationDisabled}
                                onClick={() =>
                                  void onOpenSection(chapter.sectionId)
                                }
                              >
                                定位章节：{chapter.title}
                              </button>
                              <small>
                                修订 {chapter.sectionRevision} ·{" "}
                                {chapter.origins
                                  .map((v) => origins[v])
                                  .join("、")}
                                {chapter.evidenceIds.length
                                  ? ` · 引用身份相符 ${chapter.evidenceIds.length} 处`
                                  : ""}
                              </small>
                            </li>
                          ))}
                      </ul>
                    )}
                    {row.chapters.length > chapterPreviewLimit && (
                      <p className="small-note">
                        共关联 {row.chapters.length} 章，此处仅显示前{" "}
                        {chapterPreviewLimit} 章。
                      </p>
                    )}
                  </>
                )}
                {!!scope.length && (
                  <EvidenceLinks
                    ids={rule.evidenceIds}
                    allowedSources={scope}
                  />
                )}
              </li>
            );
          })}
      </ul>
      {pages > 1 && (
        <div className="review-shortcuts">
          <button
            className="button secondary"
            type="button"
            disabled={current === 0}
            onClick={() => setPage(current - 1)}
          >
            上一页要求
          </button>
          <span>
            第 {current + 1} / {pages} 页
          </span>
          <button
            className="button secondary"
            type="button"
            disabled={current + 1 >= pages}
            onClick={() => setPage(current + 1)}
          >
            下一页要求
          </button>
        </div>
      )}
    </details>
  );
}
