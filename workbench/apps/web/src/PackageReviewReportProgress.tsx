import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type {
  PackageReviewReportView,
  PackageReviewRunView,
} from "./contracts";
import type { DependencyProps } from "./inputDependencyProtocol";
import { ErrorNotice } from "./components";
import { packageReviewEnded } from "./packageReviewProtocol";
import {
  packageReviewReportPath,
  samePackageReviewReport,
  samePackageReviewReportArtifact,
  validatePackageReviewReport,
} from "./packageReviewReportProtocol";
import PackageReviewReportCancel from "./PackageReviewReportCancel";
import PackageReviewReportDownload from "./PackageReviewReportDownload";

type Props = DependencyProps & {
  run: PackageReviewRunView;
  report: PackageReviewReportView;
  onChange: (value: PackageReviewReportView) => void;
};
const labels = {
  queued: "报告申请已受理，等待生成",
  running: "正在生成报告副本",
  cancel_requested: "已请求取消报告生成，等待最终状态",
  cancelled: "本份报告生成已取消",
  failed: "本份报告生成失败",
  succeeded: "报告副本已生成",
};
export default function PackageReviewReportProgress({
  scope,
  frozen,
  prepared,
  run,
  report,
  onChange,
}: Props) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null),
    [checkedAt, setCheckedAt] = useState("");
  const active = useRef(false),
    reading = useRef(false),
    ticket = useRef(0),
    initial = useRef(report),
    current = useRef(report);
  current.current = report;
  const path = `${packageReviewReportPath({ scope, frozen, prepared }, run)}/${report.id}`;
  const read = useCallback(
    async (force = false) => {
      if (!active.current || (reading.current && !force)) return;
      const request = ++ticket.current;
      reading.current = true;
      setBusy(true);
      setError(null);
      try {
        const { data } = await api<unknown>(path),
          received = validatePackageReviewReport(data, run, initial.current.id);
        if (!samePackageReviewReport(initial.current, received))
          throw new Error("报告的不可变身份发生变化，未采用其他副本。");
        if (!active.current || request !== ticket.current) return;
        if (
          (packageReviewEnded(current.current.operation.state) &&
            received.operation.state !== current.current.operation.state) ||
          (current.current.result &&
            !samePackageReviewReportArtifact(
              current.current.result,
              received.result,
            ))
        )
          throw new Error(
            "报告已确认的终态或生成文件发生变化，保留原记录，请重新核对。",
          );
        current.current = received;
        onChange(received);
        setCheckedAt(new Date().toLocaleTimeString());
      } catch (failure) {
        if (active.current && request === ticket.current) setError(failure);
      } finally {
        if (active.current && request === ticket.current) {
          reading.current = false;
          setBusy(false);
        }
      }
    },
    [path, run, onChange],
  );
  const reload = useCallback(() => read(true), [read]);
  useEffect(() => {
    active.current = true;
    void read(true);
    const requests = ticket,
      timer = window.setInterval(() => {
        if (!packageReviewEnded(current.current.operation.state)) void read();
      }, 3000);
    return () => {
      active.current = false;
      requests.current++;
      window.clearInterval(timer);
    };
  }, [read]);
  return (
    <section className="package-review__progress" aria-label="本份报告生成状态">
      <div className="package-review__heading">
        <div>
          <h5>{report.format === "docx" ? "Word" : "PDF"} 报告副本</h5>
          <p role="status">{labels[report.operation.state]}</p>
        </div>
        <button
          type="button"
          className="button secondary"
          disabled={busy}
          onClick={() => void reload()}
        >
          刷新报告生成状态
        </button>
      </div>
      {checkedAt && <p className="muted">最近成功读取：{checkedAt}</p>}
      {!packageReviewEnded(report.operation.state) && (
        <p>
          生成在服务端进行，每 3
          秒读取一次状态。关闭页面不会自动取消，可从本轮报告历史继续取回。
        </p>
      )}
      {["failed", "cancelled"].includes(report.operation.state) && (
        <p className="package-review__notice">
          此次未形成可下载报告。可在上方重新读取生成依据，再明确申请新的副本；不会重跑模型核查。
          {report.operation.error_code && (
            <>
              错误编号：<code>{report.operation.error_code}</code>。
            </>
          )}
        </p>
      )}
      {error != null && (
        <ErrorNotice error={error} onRetry={() => void reload()} />
      )}
      {report.result && (
        <>
          <p>
            副本固定原运行与申请时的人工意见。下载成功不表示已排除风险或完成投递。
          </p>
          {report.result.gaps.length > 0 && (
            <p className="package-review__notice">
              转换仍有以下缺口：{report.result.gaps.join("、")}
              。请查看实际文件确认。
            </p>
          )}
          <PackageReviewReportDownload
            key={report.result.document_version_id}
            report={report}
          />
        </>
      )}
      <PackageReviewReportCancel
        memberId={scope.memberId}
        run={run}
        report={report}
        onReload={reload}
      />
      <details>
        <summary>本份报告的冻结身份</summary>
        <p>
          报告编号：<code>{report.id}</code>
        </p>
        <p>
          原核查编号：<code>{report.run_id}</code>
        </p>
        <p>
          生成依据摘要：<code>{report.context_digest}</code>
        </p>
        <p>
          报告输入摘要：<code>{report.report_input_digest}</code>
        </p>
        <p>
          原结果摘要：<code>{report.result_digest}</code>
        </p>
      </details>
    </section>
  );
}
