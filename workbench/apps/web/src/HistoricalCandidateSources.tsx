import { useEffect, useState } from "react";
import { api } from "./api";
import { ErrorNotice, Loading } from "./components";
import type { HistoricalCandidateTrace } from "./contracts";
import { EvidenceLinks } from "./EvidenceLinks";
import {
  checkedHistoricalSources,
  historicalSourcesPath,
  type HistoricalCandidateProof,
} from "./historicalCandidateSources";

const PAGE = 20;
const roleLabel = { authority: "依据包", target: "工作投标包" };

export function HistoricalCandidateSources({
  proof,
}: {
  proof: HistoricalCandidateProof;
}) {
  const [attempt, setAttempt] = useState(0);
  const [trace, setTrace] = useState<HistoricalCandidateTrace | null>(null);
  const [failure, setFailure] = useState<unknown>(null);
  const [page, setPage] = useState(0);
  const path = historicalSourcesPath(proof);
  useEffect(() => {
    if (!attempt) return;
    let active = true;
    void (async () => {
      const { data } = await api<unknown>(path);
      if (!active) return;
      const checked = await checkedHistoricalSources(data, proof);
      if (active) setTrace(checked);
    })().catch((err: unknown) => {
      if (active) setFailure(err);
    });
    return () => {
      active = false;
    };
  }, [attempt, path, proof]);

  function request() {
    setTrace(null);
    setFailure(null);
    setPage(0);
    setAttempt((old) => old + 1);
  }

  return (
    <section aria-label="原候选引用追溯" className="snapshot-reading">
      {attempt === 0 && (
        <button className="button secondary" type="button" onClick={request}>
          查看本次候选引用的原页
        </button>
      )}
      {!!attempt && !trace && !failure && (
        <Loading text="正在核对本次候选与固定原页…" />
      )}
      {!!failure && <ErrorNotice error={failure} onRetry={request} />}
      {trace && (
        <>
          <p>
            对照的是本次候选的固定
            {trace.node.node_type === "paragraph" ? "段落" : "标题"}，
            不是整章、后续修改或当前草稿的核对结果。
          </p>
          <p className="identity-ref">稳定节点 {trace.node.node_id}</p>
          {trace.node.before_digest === trace.node.after_digest && (
            <p>本次候选未改变该节点的内容；不要把引用登记当成新增正文。</p>
          )}
          <p className="small-note">
            下列来源仅记录该候选实际引用的原文件、解析和物理页。没有重新核验原件字节或当前效力，也不表示条款覆盖、内容正确或已批准。
          </p>
          {trace.citations.length === 0 ? (
            <p>此候选没有登记引用。章节已有引用不代替本次候选的引用。</p>
          ) : (
            <>
              <p role="status">原候选引用 {trace.citations.length} 条</p>
              <ul>
                {trace.citations
                  .slice(page * PAGE, (page + 1) * PAGE)
                  .map((entry) => (
                    <li key={entry.evidence_id}>
                      <p>
                        原物理页 {entry.physical_page} ·{" "}
                        {entry.memberships
                          .map((s) => roleLabel[s.role])
                          .join("／")}
                      </p>
                      <p className="identity-ref">
                        文件版本 {entry.document_version_id}
                      </p>
                      <p className="identity-ref">解析 {entry.parse_run_id}</p>
                      <EvidenceLinks
                        ids={[entry.evidence_id]}
                        allowedSources={[
                          {
                            documentVersionId: entry.document_version_id,
                            parseRunId: entry.parse_run_id,
                          },
                        ]}
                        expectedPhysicalPage={entry.physical_page}
                        historicalBidId={trace.bid_id}
                      />
                    </li>
                  ))}
              </ul>
              {trace.citations.length > PAGE && (
                <div className="btn-row">
                  <button
                    className="button secondary"
                    type="button"
                    disabled={page === 0}
                    onClick={() => setPage(page - 1)}
                  >
                    上一页引用
                  </button>
                  <button
                    className="button secondary"
                    type="button"
                    disabled={(page + 1) * PAGE >= trace.citations.length}
                    onClick={() => setPage(page + 1)}
                  >
                    下一页引用
                  </button>
                </div>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
