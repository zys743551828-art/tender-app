import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type {
  AuthoringGenerationBatch,
  AuthoringGenerationBatchCandidate,
} from "./contracts";
import { ErrorNotice } from "./components";
import { AuthoringRichSnapshot } from "./AuthoringRichSnapshot";
import { TextChangePreview } from "./TextChangePreview";
import { editorText } from "./editorSchema";
import { generationPath } from "./authoringGenerationRecovery";
import type { GenerationScope } from "./authoringGenerationRecovery";
import {
  currentGenerationAttempt,
  validateGenerationCandidate,
} from "./authoringGenerationProtocol";
import type { GenerationSection } from "./authoringGenerationProtocol";

export type GenerationCandidateReview = {
  candidate: AuthoringGenerationBatchCandidate;
  ready: boolean;
};

export function AuthoringGenerationCandidate({
  scope,
  batch,
  section,
  disabled,
  selected,
  onSelect,
  onReview,
}: {
  scope: GenerationScope;
  batch: AuthoringGenerationBatch;
  section: GenerationSection;
  disabled: boolean;
  selected: boolean;
  onSelect: (sectionId: string, actionId: string, selected: boolean) => void;
  onReview: (
    sectionId: string,
    review: GenerationCandidateReview | null,
  ) => void;
}) {
  const [candidate, setCandidate] =
    useState<AuthoringGenerationBatchCandidate | null>(null);
  const [beforeReady, setBeforeReady] = useState(false);
  const [afterReady, setAfterReady] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [textComparison, setTextComparison] = useState(false);
  const active = useRef(true);
  const working = useRef(false);
  const attempt = currentGenerationAttempt(section);
  const eligible =
    !!candidate &&
    candidate.state === "pending" &&
    Date.parse(candidate.expires_at) > Date.now();
  const ready = beforeReady && afterReady && eligible;
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      onReview(section.section_id, null);
    };
  }, [section.section_id, onReview]);
  useEffect(() => {
    onReview(section.section_id, candidate ? { candidate, ready } : null);
  }, [section.section_id, candidate, ready, onReview]);
  const beforeStatus = useCallback(
    (value: boolean) => setBeforeReady(value),
    [],
  );
  const afterStatus = useCallback((value: boolean) => setAfterReady(value), []);

  async function read() {
    if (working.current || !attempt.action_id) return;
    working.current = true;
    setLoading(true);
    setError(null);
    setCandidate(null);
    setBeforeReady(false);
    setAfterReady(false);
    try {
      const response = await api<AuthoringGenerationBatchCandidate>(
        `${generationPath(scope)}/${batch.batch_id}/candidates/${attempt.action_id}`,
      );
      const value = await validateGenerationCandidate(
        response.data,
        scope,
        batch,
        section,
        attempt,
      );
      if (response.etag !== value.etag)
        throw new Error("候选版本令牌与回执不一致，不能确认此预览。");
      if (active.current) setCandidate(value);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      working.current = false;
      if (active.current) setLoading(false);
    }
  }

  return (
    <div
      className="generation-candidate"
      aria-label={`${section.title}的候选核对`}
      aria-busy={loading}
    >
      <button
        type="button"
        className="button secondary"
        disabled={loading}
        onClick={() => void read()}
      >
        {loading
          ? "正在读取完整候选…"
          : candidate
            ? "重新读取本章候选"
            : `核对${section.title}的完整前后稿`}
      </button>
      <ErrorNotice error={error} />
      {candidate && (
        <>
          <div className="generation-change-summary">
            <strong>
              修改 {candidate.changes.replaced_node_ids.length} 处 · 新增{" "}
              {candidate.changes.added_paragraphs} 段
            </strong>
            <span>
              原章节修订 {candidate.base_section_revision} · 第{" "}
              {candidate.attempt} 次尝试
            </span>
          </div>
          <p className="small-note">
            绿色标记对应候选修改或新增的正文节点。以下完整保留表格、图片和未修改内容，请对照核实；生成内容仍需人工判断事实与投标要求。
          </p>
          <details
            onToggle={(event) => setTextComparison(event.currentTarget.open)}
          >
            <summary>核对具体文字变化</summary>
            {textComparison && (
              <>
                <p className="small-note">
                  此处对照文字增删；表格结构和图片请核对下方完整前后稿。
                </p>
                <TextChangePreview
                  before={editorText(candidate.before)}
                  after={editorText(candidate.after)}
                />
              </>
            )}
          </details>
          <div className="generation-rich-comparison">
            <AuthoringRichSnapshot
              bidId={scope.bidId}
              content={candidate.before}
              label={`${section.title}：原稿`}
              changedNodeIds={candidate.changes.replaced_node_ids}
              onReady={beforeStatus}
            />
            <AuthoringRichSnapshot
              bidId={scope.bidId}
              content={candidate.after}
              label={`${section.title}：候选稿`}
              changedNodeIds={[
                ...candidate.changes.replaced_node_ids,
                ...candidate.changes.insertions.flatMap(
                  (insertion) => insertion.node_ids,
                ),
              ]}
              onReady={afterStatus}
            />
          </div>
          {!beforeReady || !afterReady ? (
            <p className="notice warning">
              完整结构或确切图片仍未核对完毕，暂不能选择应用本章。
            </p>
          ) : null}
          {!eligible && (
            <p className="notice warning">
              此候选已执行、关闭或过期，只能查看；不会据此覆盖当前章节。
            </p>
          )}
          <label className="generation-check generation-candidate-confirm">
            <input
              type="checkbox"
              aria-label={`已核对完整前后稿，选择应用${section.title}`}
              checked={selected}
              disabled={disabled || !ready}
              onChange={(event) =>
                onSelect(
                  section.section_id,
                  candidate.action_id,
                  event.target.checked,
                )
              }
            />
            <span>已核对本章完整前后稿及表格、图片，选择应用本章候选</span>
          </label>
          <details className="generation-provenance">
            <summary>本章候选来源与有效期</summary>
            <dl>
              <dt>候选有效至</dt>
              <dd>{new Date(candidate.expires_at).toLocaleString("zh-CN")}</dd>
              <dt>固定基准</dt>
              <dd>
                草稿修订 {candidate.base_draft_revision}，章节修订{" "}
                {candidate.base_section_revision}
              </dd>
              <dt>资料版本</dt>
              <dd>
                {section.source_version_ids.length
                  ? section.source_version_ids.join("、")
                  : "仅本章冻结正文，无额外资料版本"}
              </dd>
              <dt>操作记录</dt>
              <dd>{candidate.action_id}</dd>
              <dt>候选摘要</dt>
              <dd>{candidate.candidate_digest}</dd>
            </dl>
          </details>
        </>
      )}
    </div>
  );
}
