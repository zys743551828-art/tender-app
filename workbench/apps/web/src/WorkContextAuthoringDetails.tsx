import { useState } from "react";
import type {
  AuthoringWorkContext,
  WorkContextDraftSelection,
} from "./contracts";
import { ArtifactActions } from "./ArtifactActions";
import { AuthoringRichSnapshot } from "./AuthoringRichSnapshot";
import { Badge } from "./components";
import type { PackageNavigationTarget } from "./packageNavigation";
import { WorkContextBuildRelations } from "./WorkContextBuildRelations";
import { contextOperationNames } from "./workContextAuthoringProtocol";

export function WorkContextAuthoringDetails({
  context,
  onOpenDraft,
  onOpenSnapshot,
  onOpenPackage,
}: {
  context: AuthoringWorkContext;
  onOpenDraft: (id: string) => void;
  onOpenSnapshot: (selection: WorkContextDraftSelection) => void;
  onOpenPackage: (target: PackageNavigationTarget) => void;
}) {
  const [open, setOpen] = useState(false),
    [shown, setShown] = useState(20),
    [relations, setRelations] = useState(false);
  const s = context.selection,
    saved = context.snapshot,
    doc = context.document,
    built = context.build;
  const changed = Object.values(context.current_observation).some(
    (v) => v.status === "changed",
  );
  return (
    <section className="panel work-context-summary" aria-label="所选稿件摘要">
      <div className="section-heading">
        <div>
          <span className="eyebrow">已保存的确切历史</span>
          <h2>{saved.title}</h2>
          <p>
            草稿修订 {saved.draft_revision} · {saved.section_count} 个已保存章节
          </p>
        </div>
        <Badge tone={changed ? "warning" : "neutral"}>
          {changed ? "部分当前依据已变化" : "历史身份已核对"}
        </Badge>
      </div>
      <div className="work-context-summary__status">
        <article>
          <span>所选阶段</span>
          <strong>{s.kind === "build" ? "生成记录" : "已保存草稿"}</strong>
        </article>
        <article>
          <span>记录状态</span>
          <strong>
            {built ? contextOperationNames[built.operation_state] : "已保存"}
          </strong>
        </article>
        <article>
          <span>整包风险与正式技术分</span>
          <strong>尚未选择整包评估范围</strong>
        </article>
      </div>
      <p className="small-note">
        这是读取时已保存的历史稿件。来源可用性、完整依据关系及整包资格需要在后续工作面另行核对。
      </p>
      <div className="work-context-summary__actions">
        <button
          type="button"
          className="button"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          {open
            ? "收起记录详情"
            : s.kind === "build"
              ? "查看此次生成文件"
              : "阅读全文与目录"}
        </button>
        <button
          type="button"
          className="button secondary"
          onClick={() => onOpenDraft(s.draft_id)}
        >
          打开这份草稿的当前编辑稿
        </button>
        {s.kind === "build" && (
          <button
            type="button"
            className="text-button"
            onClick={() =>
              onOpenSnapshot(context.native_targets.draft_snapshot)
            }
          >
            查看生成时的已保存稿
          </button>
        )}
      </div>
      <details>
        <summary>当前依据观察</summary>
        <dl className="work-context-identity">
          {(["draft_head", "sources", "assets"] as const).map((key) => (
            <div key={key}>
              <dt>
                {
                  {
                    draft_head: "草稿当前版本",
                    sources: "直接引用来源",
                    assets: "图片资产版本",
                  }[key]
                }
              </dt>
              <dd>
                {
                  {
                    matched: "所记录版本与读取时相符",
                    changed: "所记录版本与读取时不同",
                    unknown: "尚不能判断当前资格",
                    not_applicable: "此项不适用",
                  }[context.current_observation[key].status]
                }
              </dd>
            </div>
          ))}
        </dl>
        <p>
          来源直接引用版本即使相同，也不能证明完整祖先关系与用途授权仍有效。
        </p>
      </details>
      {open && doc && (
        <section className="work-context-original" aria-label="已保存稿件全文">
          <h3>已保存正文</h3>
          {!doc.sections.length && <p>此已保存修订没有活动章节。</p>}
          {doc.outline && (
            <details>
              <summary>此修订的完整目录</summary>
              <ol>
                {doc.outline.map((n) => {
                  const section = doc.sections.find(
                    (item) => item.section_id === n.section_id,
                  )!;
                  let depth = 0,
                    cursor = n.parent_id;
                  while (cursor) {
                    depth++;
                    cursor =
                      doc.outline!.find((item) => item.section_id === cursor)
                        ?.parent_id ?? null;
                  }
                  return (
                    <li
                      key={n.section_id}
                      style={{ marginInlineStart: `${depth * 16}px` }}
                    >
                      {section.title}
                      {n.node_type === "appendix" ? "（附录）" : ""}
                    </li>
                  );
                })}
              </ol>
            </details>
          )}
          {doc.sections.slice(0, shown).map((section) => (
            <section
              className="work-context-saved-section"
              key={section.section_revision_id}
            >
              <h4>
                {section.ordinal + 1}. {section.title}
              </h4>
              <AuthoringRichSnapshot
                bidId={s.bid_id}
                content={section.content}
                expectedImages={doc.images}
                label={`已保存章节：${section.title}`}
              />
              <details>
                <summary>此章节版本与来源引用</summary>
                <p className="digest">
                  章节版本 {section.section_revision_id} · 修订{" "}
                  {section.section_revision}
                </p>
                <pre>
                  {JSON.stringify(
                    {
                      digest: section.digest,
                      rule_ids: section.content.attrs.rule_ids,
                      source_refs: section.content.attrs.source_refs,
                    },
                    null,
                    2,
                  )}
                </pre>
              </details>
            </section>
          ))}
          {shown < doc.sections.length && (
            <button
              type="button"
              className="button secondary"
              onClick={() => setShown((n) => n + 20)}
            >
              显示更多完整章节（已显示 {shown} / {doc.sections.length}）
            </button>
          )}
        </section>
      )}
      {open && built && (
        <section className="work-context-original" aria-label="此次生成文件">
          <h3>此次生成文件</h3>
          <ul className="work-context-choice-list">
            {built.outputs.map((out) => (
              <li key={out.format}>
                <div>
                  <strong>
                    {out.format.toUpperCase()}{" "}
                    {out.requested ? "请求生成的文件" : "生成过程的中间文件"}
                  </strong>
                  <p>
                    {
                      {
                        pending: "等待处理完成",
                        succeeded: "已发布文件",
                        failed: "此格式生成失败",
                        not_published: "处理已终止，未发布此文件",
                      }[out.state]
                    }
                  </p>
                </div>
                {out.document && (
                  <ArtifactActions
                    bidId={s.bid_id}
                    documentId={out.document.document_version_id}
                    isPdf={out.format === "pdf"}
                    expectedMediaType={out.document.media_type}
                    downloadLabel={`下载此次 ${out.format.toUpperCase()}`}
                  />
                )}
                {(out.gaps.length > 0 || out.document) && (
                  <details>
                    <summary>文件核对信息</summary>
                    {out.gaps.map((gap, i) => (
                      <p key={i}>{gap}</p>
                    ))}
                    {out.document && (
                      <pre>{JSON.stringify(out.document, null, 2)}</pre>
                    )}
                  </details>
                )}
              </li>
            ))}
          </ul>
          {s.kind === "build" && (
            <>
              <button
                type="button"
                className="button secondary"
                onClick={() => setRelations(!relations)}
                aria-expanded={relations}
              >
                {relations ? "收起入包关系" : "核对这次生成文件的入包关系"}
              </button>
              {relations && (
                <WorkContextBuildRelations
                  key={context.selection_digest}
                  selection={s}
                  outputs={built.outputs}
                  onOpenPackage={onOpenPackage}
                />
              )}
            </>
          )}
        </section>
      )}
      <details>
        <summary>固定选择与技术详情</summary>
        <p>读取于 {context.observed_at}</p>
        <pre>
          {JSON.stringify(
            {
              selection: s,
              selection_digest: context.selection_digest,
              observation_digest: context.observation_digest,
              current_observation: context.current_observation,
              limitations: context.limitations,
            },
            null,
            2,
          )}
        </pre>
      </details>
    </section>
  );
}
