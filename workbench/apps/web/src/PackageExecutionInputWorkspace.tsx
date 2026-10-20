import { useEffect, useRef, useState } from "react";
import { api, ApiError, supportsApi } from "./api";
import { ErrorNotice } from "./components";
import type {
  PackageExecutionInputView,
  PackageReviewEligibilityObservation,
  PackageReviewFrozenInputView,
} from "./contracts";
import type { FreezeScope } from "./packageFrozenInput";
import {
  executionId,
  validateExecutionInput,
} from "./executionInputValidation";
import {
  executionPath,
  executionScope,
  loadExecutionRecord,
  storeExecutionRecord,
} from "./executionInputRecovery";
import type {
  ExecutionRecord,
  ExecutionScope,
  PendingExecution,
} from "./executionInputRecovery";

type Props = {
  scope: FreezeScope;
  frozen: PackageReviewFrozenInputView;
  candidate: PackageReviewEligibilityObservation | null;
  disabled?: boolean;
};
const rejected = new Set([
  "PACKAGE_REVIEW_CONTEXT_CHANGED",
  "PACKAGE_REVIEW_INPUT_CHANGED",
  "PACKAGE_EXECUTION_INPUT_REJECTED",
  "PROJECT_WORK_CLOSED",
  "ORIGINAL_BYTES_CORRUPTED",
  "ORIGINAL_NOT_AVAILABLE",
]);
export default function PackageExecutionInputWorkspace(props: Props) {
  const scope = executionScope(props.scope, props.frozen);
  return (
    <Workspace key={JSON.stringify(scope)} {...props} recordScope={scope} />
  );
}
function Workspace({
  scope,
  frozen,
  candidate,
  disabled = false,
  recordScope,
}: Props & { recordScope: ExecutionScope }) {
  const [loaded] = useState(() => {
    try {
      return { record: loadExecutionRecord(recordScope), error: null };
    } catch (error) {
      return { record: null, error };
    }
  });
  const [record, setRecord] = useState<ExecutionRecord | null>(loaded.record);
  const recordRef = useRef(record),
    writing = useRef(false),
    active = useRef(false),
    ticket = useRef(0);
  const [error, setError] = useState<unknown>(loaded.error);
  const [busy, setBusy] = useState(false),
    [reading, setReading] = useState(false);
  const [result, setResult] = useState<PackageExecutionInputView | null>(null);
  const [historyId, setHistoryId] = useState(loaded.record?.lastId ?? "");
  const [historyError, setHistoryError] = useState<unknown>(null);
  const path = executionPath(scope, frozen.manifest.id);
  const available = supportsApi("POST", path);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  function persist(next: ExecutionRecord) {
    storeExecutionRecord(next);
    recordRef.current = next;
    setRecord(next);
  }
  async function save(recover: boolean) {
    const current = recordRef.current;
    if (
      !active.current ||
      writing.current ||
      !available ||
      !current ||
      (!recover && disabled)
    )
      return;
    const pending: PendingExecution | null = recover
      ? current.pending
      : !current.pending &&
          candidate &&
          candidate.parse_evidence_status === "matched"
        ? {
            key: crypto.randomUUID(),
            body: {
              frozen_digest: frozen.digest,
              context_digest: candidate.current_context.semantic_digest,
              rerun: null,
            },
            context: { ...candidate.current_context },
          }
        : null;
    if (!pending) return;
    writing.current = true;
    ticket.current++;
    setResult(null);
    setReading(false);
    setHistoryError(null);
    setBusy(true);
    setError(null);
    try {
      persist({ ...current, pending });
      let data: PackageExecutionInputView;
      try {
        ({ data } = await api<PackageExecutionInputView>(path, {
          method: "POST",
          key: pending.key,
          body: pending.body,
        }));
      } catch (failure) {
        if (
          active.current &&
          !recover &&
          failure instanceof ApiError &&
          rejected.has(failure.code)
        )
          persist({ ...current, pending: null });
        throw failure;
      }
      await validateExecutionInput(data, scope, frozen, pending);
      if (!active.current) return;
      persist({ ...current, pending: null, lastId: data.manifest.id });
      ticket.current++;
      setReading(false);
      setHistoryError(null);
      setHistoryId(data.manifest.id);
      setResult(data);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      writing.current = false;
      if (active.current) setBusy(false);
    }
  }
  async function read() {
    const id = historyId.trim();
    if (!executionId(id) || !supportsApi("GET", `${path}/${id}`)) return;
    const current = ++ticket.current;
    setReading(true);
    setResult(null);
    setHistoryError(null);
    try {
      const { data } = await api<PackageExecutionInputView>(`${path}/${id}`);
      await validateExecutionInput(data, scope, frozen, id);
      if (active.current && ticket.current === current) setResult(data);
    } catch (failure) {
      if (active.current && ticket.current === current)
        setHistoryError(failure);
    } finally {
      if (active.current && ticket.current === current) setReading(false);
    }
  }
  return (
    <section
      className="package-frozen-input__execution"
      aria-label="执行准备输入保存与恢复"
    >
      <h5>保存执行准备输入</h5>
      <p>
        保存当前完整事实、来源和方法上下文。服务端会重新核验原件；保存不会启动评审或创建任务。
      </p>
      {!available && <p>当前服务尚未提供执行准备输入保存。</p>}
      {!candidate && !record?.pending && (
        <p>先复核此冻结输入的当前条件，再保存。</p>
      )}
      {candidate?.parse_evidence_status === "mismatch" && (
        <p>精确解析证据不符，重新核对后再保存。</p>
      )}
      <button
        className="button secondary"
        type="button"
        disabled={
          !available ||
          !record ||
          !!record.pending ||
          !candidate ||
          candidate.parse_evidence_status !== "matched" ||
          busy ||
          disabled
        }
        onClick={() => void save(false)}
      >
        {busy ? "正在核对保存结果…" : "保存当前执行准备输入"}
      </button>
      {record?.pending && (
        <div>
          <p role="status">
            有一笔执行准备输入保存尚未确认，已保留原请求。恢复只重试原输入和幂等键。
          </p>
          <button
            className="button secondary"
            type="button"
            disabled={!available || busy}
            onClick={() => void save(true)}
          >
            恢复原执行准备请求
          </button>
        </div>
      )}
      {error != null && <ErrorNotice error={error} />}
      {result && (
        <div role="status">
          <p>执行准备输入已读回并校验，尚未启动评审。</p>
          <p>
            准备输入编号：<code>{result.manifest.id}</code>
          </p>
          <p>
            原件核验时点：
            {new Date(result.manifest.originals_verified_at).toLocaleString()}
            。保存时仍有 {result.manifest.blockers.length}{" "}
            项阻断；来源和事实资格需在正式启动前重新核对。
          </p>
          <details>
            <summary>准备输入身份</summary>
            <p>
              内容摘要：<code>{result.manifest.identity.content_digest}</code>
            </p>
            <p>
              执行摘要：<code>{result.manifest.identity.execution_digest}</code>
            </p>
            <p>
              记录摘要：<code>{result.digest}</code>
            </p>
          </details>
        </div>
      )}
      <details>
        <summary>读取已有执行准备输入</summary>
        <label>
          执行准备输入编号
          <input
            value={historyId}
            onChange={(e) => {
              ticket.current++;
              setReading(false);
              setHistoryError(null);
              setHistoryId(e.target.value);
            }}
            placeholder="输入准备记录 UUID"
          />
        </label>
        <button
          className="button secondary"
          type="button"
          disabled={reading || !executionId(historyId.trim())}
          onClick={() => void read()}
        >
          {reading ? "正在读取准备输入…" : "读取执行准备输入"}
        </button>
        {historyError != null && <ErrorNotice error={historyError} />}
      </details>
    </section>
  );
}
