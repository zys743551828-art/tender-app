import { PackageUnifiedReport } from "./PackageUnifiedReport";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { ErrorNotice } from "./components";

type Props = { bidId: string; scopeId: string; memberId: string };
type Pending = { certificate_id: string; command_id: string };
type Receipt = Pending & {
  schema: string;
  actor_id: string;
  bid_id: string;
  scope_id: string;
  state: "valid" | "stale" | "hidden";
  value: string | null;
  maximum: string | null;
  low: string | null;
  high: string | null;
  interval_level: string | null;
  training_groups: {
    fit: number;
    development: number;
    calibration: number;
  } | null;
  evaluation_project_mae: string | null;
  provider_requests: number;
};
type Job = Pending & {
  schema: string;
  actor_id: string;
  bid_id: string;
  scope_id: string;
  operation_id: string;
  state: string;
  prediction_ready: boolean;
  unified_report_state: string;
  provider_requests: number;
};
const jobStates: Record<string, string> = {
  queued: "已排队",
  retrying: "失败后等待原任务重试",
  running: "计算中",
  awaiting_publication: "计算完成，等待资格复验发布",
  published: "预测已发布；统一报告仍须选择同范围评审并复验",
  blocked: "资格或输入失效，已阻止发布",
  failed: "计算失败",
  cancel_requested: "正在取消",
  cancelled: "已取消",
  stale: "已发布历史结果失效",
};
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
export function PackageFormalPrediction(props: Props) {
  return <Workspace key={JSON.stringify(props)} {...props} />;
}
function Workspace(p: Props) {
  const key = `package-formal-prediction/1:${p.memberId}:${p.bidId}:${p.scopeId}`;
  const base = `/bids/${p.bidId}/technical-scopes/${p.scopeId}/formal-predictions`;
  const [certificate, setCertificate] = useState("");
  const [pending, setPending] = useState<Pending | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [suppressNumbers, setSuppressNumbers] = useState(false);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null),
    [corrupt, setCorrupt] = useState(false);
  const mounted = useRef(false),
    serial = useRef(0);
  useEffect(() => {
    mounted.current = true;
    serial.current++;
    try {
      const raw = localStorage.getItem(key);
      if (raw) {
        const value = JSON.parse(raw) as Pending;
        if (
          !value ||
          Object.keys(value).sort().join() !== "certificate_id,command_id" ||
          !uuid.test(value.certificate_id) ||
          !uuid.test(value.command_id)
        )
          throw new Error(
            "保存的请求身份损坏，请保留记录并核对，不能自动新建预测。",
          );
        setPending(value);
        setCertificate(value.certificate_id);
      }
    } catch (e) {
      setError(e);
      setCorrupt(true);
    }
    return () => {
      mounted.current = false;
    };
  }, [key]);
  async function perform(read: boolean) {
    const n = ++serial.current;
    setBusy(true);
    setError(null);
    setReceipt(null);
    try {
      const body = pending ?? {
        certificate_id: certificate,
        command_id: crypto.randomUUID(),
      };
      if (!uuid.test(body.certificate_id) || !uuid.test(body.command_id))
        throw new Error("请输入有效认证编号。");
      if (!pending) {
        localStorage.setItem(key, JSON.stringify(body));
        setPending(body);
      }
      let response;
      if (read) {
        response = await api<Receipt>(`${base}/${body.command_id}`);
      } else {
        const queued = await api<Job>(
          `/bids/${p.bidId}/technical-scopes/${p.scopeId}/prediction-tasks`,
          { method: "POST", body },
        );
        validateJob(queued.data, body);
        if (!mounted.current || n !== serial.current) return;
        setJob(queued.data);
        if (queued.data.state !== "published") return;
        response = await api<Receipt>(`${base}/${body.command_id}`);
      }
      const v = response.data;
      if (
        !v ||
        v.schema !== "package-formal-prediction/1" ||
        v.actor_id !== p.memberId ||
        v.bid_id !== p.bidId ||
        v.scope_id !== p.scopeId ||
        v.certificate_id !== body.certificate_id ||
        v.command_id !== body.command_id ||
        v.provider_requests !== 0 ||
        !["valid", "hidden", "stale"].includes(v.state) ||
        (v.state === "valid"
          ? typeof v.value !== "string" ||
            !/^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(v.value) ||
            Number(v.value) > 100 ||
            v.maximum !== "100" ||
            v.interval_level !== "0.8" ||
            typeof v.low !== "string" ||
            typeof v.high !== "string" ||
            !/^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(v.low) ||
            !/^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(v.high) ||
            Number(v.low) > Number(v.value) ||
            Number(v.high) < Number(v.value) ||
            Number(v.high) > 100 ||
            !v.training_groups ||
            ![
              v.training_groups.fit,
              v.training_groups.development,
              v.training_groups.calibration,
            ].every((n) => Number.isSafeInteger(n) && n > 0) ||
            typeof v.evaluation_project_mae !== "string" ||
            !/^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(
              v.evaluation_project_mae,
            ) ||
            Number(v.evaluation_project_mae) > 100
          : v.value !== null ||
            v.maximum !== null ||
            v.low !== null ||
            v.high !== null ||
            v.interval_level !== null ||
            v.training_groups !== null ||
            v.evaluation_project_mae !== null)
      )
        throw new Error("预测回执身份或展示状态异常。");
      if (mounted.current && n === serial.current) {
        setReceipt(v);
        setSuppressNumbers(false);
      }
    } catch (e) {
      if (mounted.current && n === serial.current) {
        setError(e);
        // Only a first, definite application rejection may discard the command.
        // Recovered/ambiguous requests always retain their original identity.
        if (
          !pending &&
          e instanceof ApiError &&
          [403, 409, 422, 503].includes(e.status) &&
          (e.code.startsWith("PACKAGE_PREDICTION_") ||
            e.code.startsWith("PREDICTION_TASK_"))
        ) {
          try {
            localStorage.removeItem(key);
            setPending(null);
          } catch {
            setCorrupt(true);
          }
        }
      }
    } finally {
      if (mounted.current && n === serial.current) setBusy(false);
    }
  }
  function validateJob(v: Job, body: Pending) {
    if (
      !v ||
      v.schema !== "package-prediction/1" ||
      v.actor_id !== p.memberId ||
      v.bid_id !== p.bidId ||
      v.scope_id !== p.scopeId ||
      v.command_id !== body.command_id ||
      v.certificate_id !== body.certificate_id ||
      !uuid.test(v.operation_id) ||
      !Object.hasOwn(jobStates, v.state) ||
      v.provider_requests !== 0 ||
      v.prediction_ready !== (v.state === "published") ||
      v.unified_report_state !==
        (v.state === "published" ? "selection_required" : "prediction_pending")
    )
      throw new Error("持久任务回执身份或状态异常。");
  }
  async function taskAction(action: "read" | "advance" | "cancel") {
    if (!pending) return;
    const n = ++serial.current;
    setBusy(true);
    setError(null);
    setReceipt(null);
    setSuppressNumbers(true);
    try {
      const path = `/bids/${p.bidId}/technical-scopes/${p.scopeId}/prediction-tasks/${pending.command_id}`;
      const { data: v } = await api<Job>(
        action === "read" ? path : `${path}/${action}`,
        action === "read" ? {} : { method: "POST", body: {} },
      );
      validateJob(v, pending);
      if (mounted.current && n === serial.current) {
        setJob(v);
        if (v.state === "published") await perform(true);
      }
    } catch (e) {
      if (mounted.current && n === serial.current) setError(e);
    } finally {
      if (mounted.current && n === serial.current) setBusy(false);
    }
  }
  return (
    <section aria-label="正式整包预测">
      <h4>正式整包预测</h4>
      <p>
        任务只消费当前认证绑定的完整材料；排队不等于发布，发布不等于统一报告已就绪。不会请求外部模型。
      </p>
      <label>
        认证编号
        <input
          value={certificate}
          disabled={busy || !!pending || corrupt}
          onChange={(e) => setCertificate(e.target.value)}
        />
      </label>
      <button
        disabled={busy || corrupt || !uuid.test(certificate)}
        onClick={() => void perform(false)}
      >
        {pending ? "恢复同一预测请求" : "验证并生成预测"}
      </button>
      <button
        disabled={busy || corrupt || !pending}
        onClick={() => void perform(true)}
      >
        读取最新资格与结果
      </button>
      {pending && (
        <div>
          <button disabled={busy} onClick={() => void taskAction("read")}>
            刷新持久任务
          </button>
          <button disabled={busy} onClick={() => void taskAction("advance")}>
            恢复资格复验与发布
          </button>
          <button
            disabled={
              busy || job?.state === "published" || job?.state === "stale"
            }
            onClick={() => void taskAction("cancel")}
          >
            取消尚未发布的预测
          </button>
        </div>
      )}
      {job && (
        <p role="status">
          持久预测任务：{jobStates[job.state]}；操作编号 {job.operation_id}
        </p>
      )}
      {job && ["failed", "cancelled", "blocked"].includes(job.state) && (
        <button
          disabled={busy}
          onClick={() => {
            try {
              localStorage.removeItem(key);
              setPending(null);
              setJob(null);
            } catch (e) {
              setError(e);
            }
          }}
        >
          保留失败历史并新建请求
        </button>
      )}
      {busy && <p role="status">正在复验材料和认证并处理预测…</p>}
      {error != null && <ErrorNotice error={error} />}
      {!busy && !receipt && (
        <p>
          尚无经当前资格复验的有效结果；请求失败或丢失回执时可恢复同一请求。
        </p>
      )}
      {receipt?.state === "valid" && !suppressNumbers && (
        <p role="status">
          正式预测：{receipt.value} / {receipt.maximum}
          （已校准，限当前认证绑定输入）
          <br />约 80% 区间：{receipt.low} – {receipt.high}
          <br />
          拟合/开发/校准项目组：{receipt.training_groups?.fit} /{" "}
          {receipt.training_groups?.development} /{" "}
          {receipt.training_groups?.calibration}；独立评估项目 MAE：
          {receipt.evaluation_project_mae}
        </p>
      )}
      {receipt && (receipt.state === "valid" || receipt.state === "hidden") && (
        <PackageUnifiedReport
          bidId={p.bidId}
          scopeId={p.scopeId}
          commandId={receipt.command_id}
          onRefresh={() => setSuppressNumbers(true)}
        />
      )}
      {receipt?.state === "stale" && (
        <p role="status">历史结果已失效，不能作为当前正式预测。</p>
      )}
      {receipt?.state === "hidden" && !suppressNumbers && (
        <p role="status">项目设置已隐藏预测分数。</p>
      )}
    </section>
  );
}
