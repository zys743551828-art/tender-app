import { useEffect, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import type { PackageHistoricalProtocol } from "./contracts";
import { Badge, ErrorNotice } from "./components";
import { useNavigationGuard } from "./navigationGuard";
import {
  definitiveHistoryFailure,
  historySame,
  validateHistoryPending,
  validateHistoryReceipt,
  type HistoryPending,
  type HistoryReceipt,
} from "./packageHistoricalResearchProtocol";
import {
  readHistoryRecovery,
  writeHistoryRecovery,
} from "./packageHistoricalResearchRecovery";
import {
  HistoryAdmissionPicker,
  HistoryCohortForm,
  type HistorySelection,
} from "./PackageHistoricalResearchForms";
import { HistoryJobsWorkspace } from "./PackageHistoricalResearchJobs";
import { historyStateNames } from "./packageHistoryPresentation";
import "./PackageHistoricalResearch.css";

export function PackageHistoricalResearch({
  memberId,
  onOpenBid,
}: {
  memberId: string;
  onOpenBid?: (bidId: string) => void;
}) {
  return (
    <HistoricalResearchWorkspace
      key={memberId}
      memberId={memberId}
      onOpenBid={onOpenBid}
    />
  );
}

function HistoricalResearchWorkspace({
  memberId,
  onOpenBid,
}: {
  memberId: string;
  onOpenBid?: (bidId: string) => void;
}) {
  const [initial] = useState(() => {
    try {
      return { pending: readHistoryRecovery(memberId), error: null as unknown };
    } catch (error) {
      return { pending: null, error };
    }
  });
  const [pending, setPending] = useState<HistoryPending | null>(
    initial.pending,
  );
  const [error, setError] = useState<unknown>(initial.error),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState("");
  const [step, setStep] = useState(
    initial.pending?.kind === "job" || initial.pending?.kind === "control"
      ? 2
      : initial.pending
        ? 1
        : 0,
  );
  const [selections, setSelections] = useState<HistorySelection[]>([]);
  const [protocol, setProtocol] = useState<PackageHistoricalProtocol | null>(
    null,
  );
  const [cohortId, setCohortId] = useState<string | null>(
    initial.pending?.kind === "job" || initial.pending?.kind === "control"
      ? initial.pending.expected.cohortId
      : null,
  );
  const [jobId, setJobId] = useState<string | null>(
    initial.pending?.kind === "control"
      ? (initial.pending.path.split("/").at(-2) ?? null)
      : null,
  );
  const [cohortDigest, setCohortDigest] = useState<string | null>(null);
  const [jobKind, setJobKind] = useState<"train" | "evaluate" | null>(
    initial.pending?.kind === "control"
      ? initial.pending.expected.jobKind
      : initial.pending?.kind === "job"
        ? initial.pending.body.kind
        : null,
  );
  const [revision, setRevision] = useState(0),
    [dirty, setDirty] = useState(false);
  const active = useRef(false),
    running = useRef(false),
    record = useRef(pending);
  const guard = useRef(async () => true);
  guard.current = async () =>
    !dirty ||
    window.confirm(
      "研究表单中还有本页选择或未发送输入。离开会清空这些表单内容；已发送的原请求仍可恢复。是否离开？",
    );
  useNavigationGuard(guard);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    if (!dirty) return;
    function leaving(event: BeforeUnloadEvent) {
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", leaving);
    return () => window.removeEventListener("beforeunload", leaving);
  }, [dirty]);

  async function send(input: HistoryPending): Promise<HistoryReceipt | null> {
    if (running.current || initial.error || !active.current) return null;
    let prepared: HistoryPending;
    try {
      prepared = validateHistoryPending(JSON.parse(JSON.stringify(input)));
      if (prepared.kind === "admission")
        throw new Error("新的历史准入须从项目技术范围工作面发起。");
      if (record.current && !historySame(record.current, prepared))
        throw new Error(
          "尚有未核对的原研究请求，请先恢复原操作，不能替换正文、条件头或请求键。",
        );
      if (!supportsApi("POST", prepared.path))
        throw new Error("当前服务版本尚未开放此研究操作，输入已保留。");
    } catch (failure) {
      setError(failure);
      return null;
    }
    running.current = true;
    setBusy(true);
    setError(null);
    setNotice("");
    record.current = prepared;
    setPending(prepared);
    try {
      // Persist the exact request before sending. A storage failure leaves this
      // same in-memory intent recoverable and performs no network mutation.
      writeHistoryRecovery(memberId, "research", prepared);
      const response = await api<unknown>(prepared.path, {
        method: "POST",
        body: prepared.body,
        etag: prepared.etag,
        key: prepared.key,
      });
      const checked = await validateHistoryReceipt(
        response.data,
        prepared,
        response.etag,
      );
      if (!active.current) return null;
      writeHistoryRecovery(memberId, "research", null);
      record.current = null;
      setPending(null);
      if (prepared.kind === "protocol" && "document" in checked) {
        setProtocol(checked);
        setStep(1);
        setNotice(
          "已确认协议冻结回执。协议已明确选入本次方案，尚未训练或评估。",
        );
      } else if (prepared.kind === "cohort" && "members" in checked) {
        setCohortId(checked.id);
        setCohortDigest(checked.digest);
        setJobId(null);
        setJobKind(null);
        setStep(2);
        setDirty(false);
        setNotice(
          `已确认研究组冻结回执：${checked.members.length} 份记录。下方另行读取当前依据，尚未创建任务。`,
        );
      } else if (
        (prepared.kind === "job" || prepared.kind === "control") &&
        "job_id" in checked
      ) {
        setCohortId(checked.cohort_id);
        if (cohortId !== checked.cohort_id) setCohortDigest(null);
        setJobId(checked.job_id);
        setJobKind(checked.kind);
        setStep(2);
        setNotice(
          `已确认原任务回执：${historyStateNames[checked.state]}，第 ${checked.generation} 代。下方当前状态通过独立读取核对；该回执不会随任务推进而改写。`,
        );
      }
      setRevision((value) => value + 1);
      return checked;
    } catch (failure) {
      if (!active.current) return null;
      if (definitiveHistoryFailure(failure)) {
        try {
          writeHistoryRecovery(memberId, "research", null);
          record.current = null;
          setPending(null);
        } catch (storageFailure) {
          setError(storageFailure);
          return null;
        }
      }
      setError(failure);
      return null;
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  const commands = {
    blocked: busy || !!pending || !!initial.error,
    busy,
    send,
  };
  return (
    <section
      className="panel package-history-workspace"
      aria-label="严格整包历史研究"
    >
      <header className="section-heading">
        <div>
          <h2>整包历史研究</h2>
          <p className="small-note">
            明确选择已经核验的整包资料，冻结回溯研究方案，再查看独立任务与结果。
          </p>
        </div>
        <Badge>CPU 基线 · 不调用外部模型</Badge>
      </header>
      <p className="notice neutral">
        研究结果与正式施组预测分别管理。当前提供 mean/median
        常数基线机制，尚未接通完整图文三评特征和正式模型发布；没有真实配对资料时不形成真实精度结论。
      </p>
      <ErrorNotice error={error} />
      {notice && (
        <p className="notice neutral" role="status">
          {notice}
        </p>
      )}
      {pending && (
        <section
          className="notice warning package-history-pending"
          aria-label="待恢复的原研究请求"
        >
          <strong>
            {busy ? "正在核对原研究请求回执" : "原研究请求回执尚未确认"}
          </strong>
          <p>
            已固定原正文、原条件头和原幂等键。切换步骤、重新读取目录或当前状态都不会替换它；在回执核清前暂不发起其他写入。
          </p>
          <details>
            <summary>核对待恢复操作</summary>
            <p>
              操作：
              {
                {
                  protocol: "冻结 CPU 协议",
                  cohort: "冻结研究组",
                  job: "创建研究任务",
                  control: "控制研究任务",
                  admission: "历史准入",
                }[pending.kind]
              }
            </p>
            <p>原因：{pending.body.reason}</p>
            <pre>{JSON.stringify(pending.body, null, 2)}</pre>
          </details>
          <button
            type="button"
            className="button secondary"
            disabled={busy || !!initial.error}
            onClick={() => void send(pending)}
          >
            {busy ? "正在恢复…" : "恢复原研究请求结果"}
          </button>
        </section>
      )}
      <nav className="package-history-steps" aria-label="整包历史研究步骤">
        {["1. 选择已准入资料", "2. 冻结研究方案", "3. 任务与结果"].map(
          (label, index) => (
            <button
              type="button"
              className="button secondary"
              aria-current={step === index ? "step" : undefined}
              key={label}
              onClick={() => setStep(index)}
            >
              {label}
            </button>
          ),
        )}
      </nav>
      <div hidden={step !== 0} onChangeCapture={() => setDirty(true)}>
        <HistoryAdmissionPicker
          selected={selections}
          onSelected={(value) => {
            setSelections(value);
            setDirty(true);
          }}
          commands={commands}
          onOpenBid={onOpenBid}
          onContinue={() => setStep(1)}
        />
      </div>
      <div hidden={step !== 1} onChangeCapture={() => setDirty(true)}>
        <HistoryCohortForm
          selected={selections}
          onSelected={(value) => {
            setSelections(value);
            setDirty(true);
          }}
          protocol={protocol}
          onProtocol={(value) => {
            setProtocol(value);
            setDirty(true);
          }}
          commands={commands}
        />
      </div>
      <div hidden={step !== 2} onChangeCapture={() => setDirty(true)}>
        <HistoryJobsWorkspace
          commands={commands}
          cohortId={cohortId}
          cohortDigest={cohortDigest}
          jobId={jobId}
          jobKind={jobKind}
          revision={revision}
          onSelectCohort={(id, digest) => {
            setCohortId(id);
            setCohortDigest(digest);
            setJobId(null);
            setJobKind(null);
          }}
          onSelectJob={(id, kind) => {
            setJobId(id);
            setJobKind(kind);
          }}
        />
      </div>
    </section>
  );
}
