import { useEffect, useRef, useState } from "react";
import { api, objectFetch } from "./api";
import { ErrorNotice } from "./components";
import PackageReviewEvidence from "./PackageReviewEvidence";
type Citation = {
  evidence_id: string;
  document_version_id: string;
  parse_run_id: string;
  physical_page: number;
  quote: string;
  file_digest: string;
};
type Report = {
  schema: string;
  command_id: string;
  bid_id: string;
  scope_id: string;
  certificate_id: string;
  state: "valid" | "hidden";
  score: Record<string, unknown> | null;
  topics: {
    rule_id: string;
    observations: Record<string, string>;
    observed_band_gap: string | null;
    rule_maximum: string | null;
    evidence: Citation[];
  }[];
  limitations: string[];
};
type Props = {
  bidId: string;
  scopeId: string;
  commandId: string;
  certificateId: string;
  onRefresh?: () => void;
};
function validTopic(t: Report["topics"][number]): boolean {
  return (
    !!t &&
    typeof t.rule_id === "string" &&
    !!t.observations &&
    Object.entries(t.observations).every(
      ([k, v]) =>
        ["specificity", "validity", "consistency"].includes(k) &&
        ["supported", "needs_review"].includes(v),
    ) &&
    Array.isArray(t.evidence) &&
    t.evidence.every(
      (e) =>
        !!e &&
        [e.evidence_id, e.document_version_id, e.parse_run_id, e.quote].every(
          (s) => typeof s === "string" && s.length > 0,
        ) &&
        Number.isSafeInteger(e.physical_page) &&
        e.physical_page > 0 &&
        /^[a-f0-9]{64}$/.test(e.file_digest),
    ) &&
    [t.rule_maximum, t.observed_band_gap].every(
      (v) =>
        v === null ||
        (typeof v === "string" && /^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(v)),
    )
  );
}
export function PackagePredictionReport(p: Props) {
  return <View key={JSON.stringify(p)} {...p} />;
}
function View(p: Props) {
  const [report, setReport] = useState<Report | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  const active = useRef(false),
    serial = useRef(0);
  useEffect(() => {
    active.current = true;
    serial.current++;
    return () => {
      active.current = false;
    };
  }, []);
  const base = `/bids/${p.bidId}/technical-scopes/${p.scopeId}/formal-predictions/${p.commandId}`;
  async function load(word: boolean) {
    const n = ++serial.current;
    p.onRefresh?.();
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      if (word) {
        const response = await objectFetch(`/api/v1${base}/report.docx`, {
          cache: "no-store",
        });
        if (
          !response.ok ||
          !response.headers
            .get("content-type")
            ?.startsWith(
              "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ) ||
          !response.headers.get("cache-control")?.includes("no-store")
        )
          throw new Error("Word 报告资格复验失败，未下载旧文件。");
        const blob = await response.blob();
        if (!active.current || n !== serial.current) return;
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "prediction-report.docx";
        a.click();
        URL.revokeObjectURL(url);
      } else {
        const { data: v } = await api<Report>(`${base}/report`);
        if (
          !v ||
          v.schema !== "package-formal-prediction-report/1" ||
          v.command_id !== p.commandId ||
          v.bid_id !== p.bidId ||
          v.scope_id !== p.scopeId ||
          v.certificate_id !== p.certificateId ||
          !["valid", "hidden"].includes(v.state) ||
          !Array.isArray(v.topics) ||
          v.topics.length > 10 ||
          !Array.isArray(v.limitations) ||
          !v.limitations.every((t) => typeof t === "string") ||
          !v.topics.every(validTopic) ||
          (v.state === "hidden" &&
            (v.score !== null ||
              v.topics.some(
                (t) => t.observed_band_gap !== null || t.rule_maximum !== null,
              )))
        )
          throw new Error("报告身份或隐藏设置不匹配。");
        if (active.current && n === serial.current) setReport(v);
      }
    } catch (e) {
      if (active.current && n === serial.current) setError(e);
    } finally {
      if (active.current && n === serial.current) setBusy(false);
    }
  }
  const names: Record<string, string> = {
    specificity: "具体性",
    validity: "有效性",
    consistency: "一致性",
  };
  return (
    <section aria-label="预测报告与原文证据">
      <button disabled={busy} onClick={() => void load(false)}>
        复验并查看预测报告
      </button>
      <button disabled={busy} onClick={() => void load(true)}>
        复验并下载 Word 报告
      </button>
      {error != null && <ErrorNotice error={error} />}
      {report && (
        <>
          <h5>可能的失分点 {report.topics.length} 处</h5>
          {report.limitations.map((t) => (
            <p key={t}>{t}</p>
          ))}
          {report.topics.map((t) => (
            <article key={t.rule_id}>
              <h6>条款 {t.rule_id}</h6>
              <p>
                {Object.entries(t.observations)
                  .map(
                    ([k, v]) =>
                      `${names[k] ?? k}：${v === "supported" ? "三次一致支持" : "需要复核"}`,
                  )
                  .join("；")}
              </p>
              {report.state === "valid" && (
                <p>
                  条款满分 {t.rule_maximum}；档位观察差额 {t.observed_band_gap}
                  （非模型总分归因）
                </p>
              )}
              {t.evidence.map((e, i) => (
                <div key={i}>
                  <blockquote>{e.quote}</blockquote>
                  <PackageReviewEvidence
                    bidId={p.bidId}
                    document={e}
                    quote={e}
                  />
                </div>
              ))}
            </article>
          ))}
        </>
      )}
    </section>
  );
}
