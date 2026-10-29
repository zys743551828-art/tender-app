import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { ErrorNotice } from "./components";
import type { PackageReviewHumanDecisionPage } from "./contracts";
import type { PackageReviewRow } from "./packageReviewProtocol";
import type { PackageReviewDecisionProps } from "./packageReviewDecisionProtocol";
import {
  packageReviewDecisionLabels,
  packageReviewDecisionsPath,
  validatePackageReviewDecisionPage,
} from "./packageReviewDecisionProtocol";
import PackageReviewEvidence from "./PackageReviewEvidence";

export default function PackageReviewDecisionHistory({
  p,
  row,
}: {
  p: PackageReviewDecisionProps;
  row: PackageReviewRow;
}) {
  const [page, setPage] = useState<PackageReviewHumanDecisionPage | null>(null),
    [reading, setReading] = useState(false),
    [error, setError] = useState<unknown>(null);
  const active = useRef(false),
    busy = useRef(false),
    seenCursors = useRef(new Set<string>()),
    seenIds = useRef(new Set<string>());
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  async function read(next = false) {
    if (!active.current || busy.current || (next && !page?.next_cursor)) return;
    busy.current = true;
    setReading(true);
    setError(null);
    const cursor = next ? page!.next_cursor : null;
    try {
      const { data } = await api<unknown>(
        `${packageReviewDecisionsPath(p, row.requirement_id)}?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
      );
      const received = await validatePackageReviewDecisionPage(
        data,
        p.run,
        row,
      );
      if (
        next &&
        (received.items.some((item) => seenIds.current.has(item.manifest.id)) ||
          (received.next_cursor !== null &&
            (received.next_cursor === cursor ||
              seenCursors.current.has(received.next_cursor))))
      )
        throw new Error("人工历史游标重复或记录重叠，未将旧页当成新历史。");
      if (!active.current) return;
      if (!next) {
        seenCursors.current.clear();
        seenIds.current.clear();
      }
      if (cursor) seenCursors.current.add(cursor);
      received.items.forEach((item) => seenIds.current.add(item.manifest.id));
      setPage(received);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      if (active.current) {
        busy.current = false;
        setReading(false);
      }
    }
  }
  return (
    <details className="package-review__decision-history">
      <summary>此项人工记录与原引用历史</summary>
      <p className="muted">
        历史记录保留当时意见及所选原引用，不会自动变成当前版本。
      </p>
      <button
        type="button"
        className="button secondary"
        disabled={reading}
        onClick={() => void read()}
      >
        {reading ? "正在读取人工历史…" : "读取此项人工历史"}
      </button>
      {page && (
        <>
          {!page.items.length && <p>此项尚无人工处置记录。</p>}
          <ol className="package-review__decision-history-list">
            {page.items.map(({ manifest: m, digest }) => (
              <li key={m.id}>
                <strong>
                  第 {m.sequence_no} 版 · {packageReviewDecisionLabels[m.state]}
                </strong>
                <p>{m.reason}</p>
                <p className="muted">
                  {m.created_at} · 成员 <code>{m.actor_id}</code>
                </p>
                {m.selected_quotes.length ? (
                  m.selected_quotes.map((quote, index) => {
                    const document =
                      p.run.result!.manifest.submitted_documents.find(
                        (doc) =>
                          doc.package_role === quote.package_role &&
                          doc.member_id === quote.member_id &&
                          doc.document_version_id ===
                            quote.document_version_id &&
                          doc.parse_run_id === quote.parse_run_id,
                      )!;
                    return (
                      <div className="package-review__quotes" key={index}>
                        <p>
                          {quote.package_role === "target"
                            ? "投标原文"
                            : "招标依据"}{" "}
                          · {quote.member_id} · 物理页 {quote.physical_page}
                        </p>
                        <blockquote>{quote.quote}</blockquote>
                        <PackageReviewEvidence
                          quote={quote}
                          document={document}
                          bidId={p.run.scope.bid_id}
                        />
                      </div>
                    );
                  })
                ) : (
                  <p>本条人工意见未另选原引用。</p>
                )}
                <details>
                  <summary>人工记录身份</summary>
                  <p>
                    记录编号：<code>{m.id}</code>
                  </p>
                  <p>
                    记录摘要：<code>{digest}</code>
                  </p>
                  <p>
                    原条款摘要：<code>{m.row_digest}</code>
                  </p>
                </details>
              </li>
            ))}
          </ol>
          {page.has_more && (
            <button
              type="button"
              className="button secondary"
              disabled={reading}
              onClick={() => void read(true)}
            >
              读取更早的人工历史
            </button>
          )}
        </>
      )}
      {error != null && <ErrorNotice error={error} />}
    </details>
  );
}
