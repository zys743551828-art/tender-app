import { useEffect, useRef, useState } from "react";
import { api, objectFetch } from "./api";
import { ErrorNotice } from "./components";
import PackageReviewEvidence from "./PackageReviewEvidence";
import type {
  PackageReviewDocument,
  PackageReviewQuote,
} from "./packageReviewProtocol";
type Props = {
  bidId: string;
  scopeId: string;
  commandId: string;
  onRefresh?: () => void;
  initialReviewId?: string;
};
type Report = {
  schema: string;
  snapshot_id: string;
  bid_id: string;
  scope_id: string;
  command_id: string;
  review_id: string;
  sections: [string, string[]][];
  documents: PackageReviewDocument[];
  matrix: {
    requirement_id: string;
    target_quotes: PackageReviewQuote[];
    authority_quotes: PackageReviewQuote[];
  }[];
};
export function PackageUnifiedReport(p: Props) {
  return (
    <View
      key={`${p.bidId}:${p.scopeId}:${p.commandId}:${p.initialReviewId ?? ""}`}
      {...p}
    />
  );
}
function View(p: Props) {
  const [review, setReview] = useState(p.initialReviewId ?? ""),
    [simulation, setSimulation] = useState(""),
    [report, setReport] = useState<Report | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  const mounted = useRef(false),
    serial = useRef(0);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  async function load(word: boolean) {
    const n = ++serial.current;
    p.onRefresh?.();
    setReport(null);
    setError(null);
    setBusy(true);
    try {
      const query = new URLSearchParams({ review_id: review });
      if (simulation) query.set("simulation_id", simulation);
      const path = `/bids/${p.bidId}/technical-scopes/${p.scopeId}/formal-predictions/${p.commandId}/unified-report${word ? ".docx" : ""}?${query}`;
      if (word) {
        const response = await objectFetch(`/api/v1${path}`, {
          cache: "no-store",
        });
        if (
          !response.ok ||
          !response.headers.get("cache-control")?.includes("no-store") ||
          !response.headers
            .get("content-type")
            ?.startsWith(
              "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        )
          throw new Error("统一报告复验失败，未下载旧文件。");
        const blob = await response.blob();
        if (!mounted.current || serial.current !== n) return;
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "unified-review-report.docx";
        a.click();
        URL.revokeObjectURL(url);
      } else {
        const { data: r } = await api<Report>(path);
        if (
          !r ||
          r.schema !== "package-unified-review-report/1" ||
          r.bid_id !== p.bidId ||
          r.scope_id !== p.scopeId ||
          r.command_id !== p.commandId ||
          r.review_id !== review ||
          !/^[a-f0-9]{64}$/.test(r.snapshot_id) ||
          !Array.isArray(r.sections) ||
          !r.sections.every(
            (s) =>
              Array.isArray(s) &&
              s.length === 2 &&
              typeof s[0] === "string" &&
              Array.isArray(s[1]) &&
              s[1].every((t) => typeof t === "string"),
          ) ||
          !Array.isArray(r.documents) ||
          !Array.isArray(r.matrix) ||
          !r.documents.every(
            (d) =>
              !!d &&
              [d.document_version_id, d.parse_run_id, d.file_digest].every(
                (v) => typeof v === "string",
              ),
          ) ||
          !r.matrix.every(
            (row) =>
              !!row &&
              typeof row.requirement_id === "string" &&
              [row.target_quotes, row.authority_quotes].every(
                (quotes) =>
                  Array.isArray(quotes) &&
                  quotes.every(
                    (q) =>
                      !!q &&
                      [
                        q.document_version_id,
                        q.parse_run_id,
                        q.evidence_id,
                        q.quote,
                      ].every((v) => typeof v === "string") &&
                      Number.isSafeInteger(q.physical_page) &&
                      q.physical_page > 0,
                  ),
              ),
          )
        )
          throw new Error("统一快照身份或报告内容异常。");
        if (mounted.current && serial.current === n) setReport(r);
      }
    } catch (e) {
      if (mounted.current && serial.current === n) setError(e);
    } finally {
      if (mounted.current && serial.current === n) setBusy(false);
    }
  }
  const uuid =
    /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
  return (
    <section aria-label="统一评审报告">
      <h5>统一评审报告</h5>
      <p>
        请选择同一冻结范围最近完成的评审。报价未选择时明确列为不可用；关闭报价模块时不组合报价。
      </p>
      <label>
        完成评审编号
        <input
          value={review}
          disabled={busy}
          onChange={(e) => {
            setReport(null);
            setReview(e.target.value);
          }}
        />
      </label>
      <label>
        报价模拟编号（可选）
        <input
          value={simulation}
          disabled={busy}
          onChange={(e) => {
            setReport(null);
            setSimulation(e.target.value);
          }}
        />
      </label>
      <button
        disabled={
          busy || !uuid.test(review) || (!!simulation && !uuid.test(simulation))
        }
        onClick={() => void load(false)}
      >
        复验统一报告
      </button>
      <button
        disabled={
          busy || !uuid.test(review) || (!!simulation && !uuid.test(simulation))
        }
        onClick={() => void load(true)}
      >
        下载统一 Word
      </button>
      {error != null && <ErrorNotice error={error} />}
      {report && (
        <>
          <p>统一快照 {report.snapshot_id}</p>
          {report.sections.map(([title, lines]) => (
            <article key={title}>
              <h6>{title}</h6>
              {lines.map((line, i) => (
                <p key={i}>{line}</p>
              ))}
            </article>
          ))}
          {report.matrix
            .flatMap((r) => [...r.target_quotes, ...r.authority_quotes])
            .map((q, i) => {
              const d = report.documents.find(
                (d) =>
                  d.document_version_id === q.document_version_id &&
                  d.parse_run_id === q.parse_run_id,
              );
              return d ? (
                <PackageReviewEvidence
                  key={i}
                  bidId={p.bidId}
                  document={d}
                  quote={q}
                />
              ) : null;
            })}
        </>
      )}
    </section>
  );
}
