import { useMemo, useState } from "react";
import type { AuthoringDocument } from "./contracts";
import { AuthoringRichSnapshot } from "./AuthoringRichSnapshot";
import { readAuthoringContent } from "./richEditorSchema";
import { TextChangePreview } from "./TextChangePreview";
import "./AssistantReviewDetails.css";

/** Read-only rendering: opening a comparison never confirms an action. */
export function AssistantPatchComparison({
  bidId,
  before,
  after,
}: {
  bidId: string;
  before: AuthoringDocument;
  after: AuthoringDocument;
}) {
  const [compare, setCompare] = useState(false);
  const [original, setOriginal] = useState(false);
  const [proposal, setProposal] = useState(false);
  const text = useMemo(() => {
    if (!compare) return null;
    try {
      const read = (content: AuthoringDocument) => {
        const node = readAuthoringContent(content, true);
        // Adjacent marked runs remain adjacent; explicit line breaks survive.
        return node.textBetween(0, node.content.size, "\n", "\n");
      };
      return { before: read(before), after: read(after), error: null };
    } catch {
      return {
        before: "",
        after: "",
        error: "本提议的正文结构尚未完整读出，请刷新卡片后核对完整稿件。",
      };
    }
  }, [before, after, compare]);
  return (
    <section className="assistant-card-preview" aria-label="正文提议只读对照">
      <p className="assistant-card-preview__note">
        展开后查看具体增删；列表与强调等格式可在完整稿件中核对。这里展示此提议保存的原稿与拟稿，不代表当前正文。
      </p>
      <details onToggle={(event) => setCompare(event.currentTarget.open)}>
        <summary>查看具体文字增删</summary>
        {compare &&
          text &&
          (text.error ? (
            <p className="notice error" role="alert">
              {text.error}
            </p>
          ) : (
            <TextChangePreview
              before={text.before}
              after={text.after}
              beforeLabel="提议基准原稿"
              afterLabel="提议拟稿 · 执行结果见卡片"
            />
          ))}
      </details>
      <details onToggle={(event) => setOriginal(event.currentTarget.open)}>
        <summary>查看完整原稿与格式</summary>
        {original && (
          <div
            className="assistant-card-preview__full"
            tabIndex={0}
            role="region"
            aria-label="完整原稿滚动区域"
          >
            <AuthoringRichSnapshot
              bidId={bidId}
              content={before}
              label="提议保存的完整原稿"
            />
          </div>
        )}
      </details>
      <details onToggle={(event) => setProposal(event.currentTarget.open)}>
        <summary>查看完整拟稿与格式</summary>
        {proposal && (
          <div
            className="assistant-card-preview__full"
            tabIndex={0}
            role="region"
            aria-label="完整拟稿滚动区域"
          >
            <AuthoringRichSnapshot
              bidId={bidId}
              content={after}
              label="提议保存的完整拟稿"
            />
          </div>
        )}
      </details>
    </section>
  );
}
