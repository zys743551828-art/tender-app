import { PackagePredictionReport } from "./PackagePredictionReport";
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
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
export function PackageFormalPrediction(props: Props) {
  return <Workspace key={JSON.stringify(props)} {...props} />;
}
function Workspace(p: Props) {
  const key = `package-formal-prediction/1:${p.memberId}:${p.bidId}:${p.scopeId}`;
  const base = `/bids/${p.bidId}/technical-scopes/${p.scopeId}/formal-predictions`;
  const [certificate, setCertificate] = useState("");
  const [pending, setPending] = useState<Pending | null>(null);
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
      const response = read
        ? await api<Receipt>(`${base}/${body.command_id}`)
        : await api<Receipt>(base, { method: "POST", body });
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
          e.code.startsWith("PACKAGE_PREDICTION_")
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
  return (
    <section aria-label="正式整包预测">
      <h4>正式整包预测</h4>
      <p>仅消费当前认证绑定的完整材料；缺少资格时不可用。不会请求外部模型。</p>
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
        <PackagePredictionReport
          bidId={p.bidId}
          scopeId={p.scopeId}
          commandId={receipt.command_id}
          certificateId={receipt.certificate_id}
          onRefresh={() => setSuppressNumbers(true)}
        />
      )}
      {receipt?.state === "stale" && (
        <p role="status">历史结果已失效，不能作为当前正式预测。</p>
      )}
      {receipt?.state === "hidden" && (
        <p role="status">项目设置已隐藏预测分数。</p>
      )}
    </section>
  );
}
