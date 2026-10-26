import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { ErrorNotice } from "./components";
import { recordObject as object } from "./executionInputValidation";

type Props = {
  base: string;
  memberId: string;
  scopeId: string;
  intentId: string;
  requestDigest: string;
  job: { job_id: string; job_digest: string; generation: number } | null;
};
type Status = Record<string, unknown>;
const executionNames: Record<string, string> = {
  not_started: "尚未发送",
  ready: "等待执行",
  in_flight: "执行在途",
  unknown: "费用待核实",
  paused_invalid: "结果无效，已暂停",
  paused_stale: "材料已变化，已暂停",
  paused_overrun: "超出预估，已暂停",
  completed: "执行槽位已完成",
};
const feeNames: Record<string, string> = {
  not_started: "尚未预留",
  reserved: "预算已预留",
  in_flight: "在途，费用未确定",
  unknown: "费用未知，不自动重发",
  settled_estimate: "已按用量结算估算",
};
const qualificationNames: Record<string, string> = {
  approved: "审核已批准",
  changed: "审核版本已变化",
  revoked: "审核已撤销",
  expired: "审核已过期",
  not_approved: "尚未获批",
};
const amounts = [
  "reserved_minor",
  "held_minor",
  "known_estimated_minor",
  "released_minor",
] as const;
export function MaterialExecutionStatus(p: Props) {
  const identity = JSON.stringify(p),
    current = useRef(identity),
    serial = useRef(0),
    mounted = useRef(false);
  current.current = identity;
  const [value, setValue] = useState<Status | null>(null),
    [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    mounted.current = true;
    setValue(null);
    setError(null);
    setBusy(false);
    serial.current++;
    return () => {
      mounted.current = false;
    };
  }, [identity]);
  async function refresh() {
    const id = identity,
      n = ++serial.current;
    setBusy(true);
    setError(null);
    setValue(null);
    try {
      const { data: v } = await api<unknown>(
        `${p.base}/material-qualified-jobs/${p.intentId}/execution-state`,
      );
      if (
        !object(v) ||
        v.version !== "material-execution-status/1" ||
        v.intent_id !== p.intentId ||
        v.actor_id !== p.memberId ||
        v.scope_id !== p.scopeId ||
        v.request_digest !== p.requestDigest ||
        v.send_authorized !== false ||
        v.accuracy_verified !== false ||
        v.invoice_reconciled !== false ||
        v.task_state !== (p.job ? "accepted_preparation" : "pending") ||
        (p.job
          ? !object(v.job) ||
            v.job.job_id !== p.job.job_id ||
            v.job.job_digest !== p.job.job_digest ||
            v.job.generation !== p.job.generation
          : v.job !== null)
      )
        throw new Error("执行状态身份或权限声明异常。");
      if (v.available === true) {
        const integer = (x: unknown) =>
          Number.isSafeInteger(x) && (x as number) >= 0;
        const noLedger = v.execution_state === "not_started";
        if (
          (noLedger
            ? v.execution_mode !== null
            : !["qualified_live", "isolated_synthetic_mechanism"].includes(
                v.execution_mode as string,
              )) ||
          typeof v.execution_state !== "string" ||
          !Object.hasOwn(executionNames, v.execution_state) ||
          typeof v.fee_state !== "string" ||
          !Object.hasOwn(feeNames, v.fee_state) ||
          typeof v.qualification_state !== "string" ||
          !Object.hasOwn(qualificationNames, v.qualification_state) ||
          v.final_fee_minor !== null ||
          typeof v.observed_at !== "string" ||
          !Number.isFinite(Date.parse(v.observed_at)) ||
          !(
            v.last_settled_at === null ||
            (typeof v.last_settled_at === "string" &&
              Number.isFinite(Date.parse(v.last_settled_at)))
          ) ||
          !["attempt_count", "unsettled_count", "unknown_count"].every((k) =>
            integer(v[k]),
          ) ||
          !amounts.every((k) => (noLedger ? v[k] === null : integer(v[k]))) ||
          (noLedger
            ? v.currency !== null ||
              v.fee_state !== "not_started" ||
              v.attempt_count !== 0
            : !["USD", "CNY"].includes(v.currency as string)) ||
          (v.unknown_count as number) + (v.unsettled_count as number) >
            (v.attempt_count as number) ||
          (((v.unknown_count as number) > 0 ||
            v.execution_state === "unknown") &&
            v.fee_state !== "unknown")
        )
          throw new Error("执行费用数据不完整，不能推断为零费用。");
      } else if (
        v.available !== false ||
        v.reason !== "EXECUTION_OBSERVER_UNAVAILABLE"
      )
        throw new Error("执行观察接口异常。");
      if (mounted.current && current.current === id && serial.current === n)
        setValue(v);
    } catch (e) {
      if (mounted.current && current.current === id && serial.current === n)
        setError(e);
    } finally {
      if (mounted.current && current.current === id && serial.current === n)
        setBusy(false);
    }
  }
  return (
    <section aria-label="执行与费用状态">
      <button disabled={busy} onClick={() => void refresh()}>
        读取权威执行与费用状态
      </button>
      <ErrorNotice error={error} />
      {value &&
        (value.available === false ? (
          <p>执行观察尚未配置，费用未读取。</p>
        ) : (
          <>
            <p>
              任务接受：
              {value.task_state === "pending" ? "尚未确认" : "准备任务已接受"}
            </p>
            <p>
              执行模式：
              {value.execution_mode === "qualified_live"
                ? "获批发送通道"
                : value.execution_mode === "isolated_synthetic_mechanism"
                  ? "隔离机制测试"
                  : "尚未预留"}
            </p>
            <p>执行结果：{executionNames[value.execution_state as string]}</p>
            <p>
              资格：{qualificationNames[value.qualification_state as string]}
              ；本查询不授予发送。
            </p>
            <p>费用状态：{feeNames[value.fee_state as string]}</p>
            {value.currency !== null && (
              <dl>
                <dt>币种（以下为最小货币单位）</dt>
                <dd>{String(value.currency)}</dd>
                <dt>原预算预留</dt>
                <dd>{String(value.reserved_minor)}</dd>
                <dt>当前占用</dt>
                <dd>{String(value.held_minor)}</dd>
                <dt>已知用量估算（不是最终账单）</dt>
                <dd>{String(value.known_estimated_minor)}</dd>
                <dt>已释放预留</dt>
                <dd>{String(value.released_minor)}</dd>
              </dl>
            )}
            <p>最终账单尚未核对；执行完成不等于准确性验收。</p>
            <p>
              最近结算：
              {value.last_settled_at === null
                ? "尚无结算记录"
                : String(value.last_settled_at)}
              。可再次读取迟到结算。
            </p>
            <p>观察时间：{String(value.observed_at)}</p>
          </>
        ))}
    </section>
  );
}
