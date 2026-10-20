import { useEffect, useRef, useState } from "react";
import { api, ApiError, supportsApi } from "./api";
import { ErrorNotice } from "./components";
import PackagePreparedFactPicker from "./PackagePreparedFactPicker";
import type {
  PackageExecutionInputView,
  PackageFactScopeObservation,
  PackageFactScopeView,
  PackagePreparedFactSummary,
} from "./contracts";
import type { FreezeScope } from "./packageFrozenInput";
import { executionPath } from "./executionInputRecovery";
import { executionId } from "./executionInputValidation";
import { loadFactScopeRecord, storeFactScopeRecord } from "./factScopeRecovery";
import type {
  FactScopeKey,
  FactScopeRecord,
  PendingFactScope,
} from "./factScopeRecovery";
import {
  scopeLabels,
  validateScopeObservation,
  validateScopeRecord,
} from "./factScopeValidation";

type Props = {
  scope: FreezeScope;
  frozenId: string;
  prepared: PackageExecutionInputView;
  factIds: string[];
};
const rejected = new Set([
  "PACKAGE_FACT_SCOPE_UNPROVEN",
  "PACKAGE_FACT_SCOPE_CHANGED",
  "PACKAGE_FACT_SCOPE_REJECTED",
  "PACKAGE_EXECUTION_INPUT_CHANGED",
  "PACKAGE_FACT_NOT_FOUND",
  "PROJECT_WORK_CLOSED",
  "INVALID_REQUEST",
  "IDEMPOTENCY_REQUIRED",
]);
export default function PackageFactScopeWorkspace(props: Props) {
  const keyScope = {
    ...props.scope,
    frozenId: props.frozenId,
    preparedId: props.prepared.manifest.id,
    preparedDigest: props.prepared.digest,
  };
  return (
    <Workspace key={JSON.stringify(keyScope)} {...props} keyScope={keyScope} />
  );
}
function Workspace({
  scope,
  frozenId,
  prepared,
  factIds,
  keyScope,
}: Props & { keyScope: FactScopeKey }) {
  const [loaded] = useState(() => {
    try {
      return { record: loadFactScopeRecord(keyScope), error: null };
    } catch (error) {
      return { record: null, error };
    }
  });
  const [record, setRecord] = useState<FactScopeRecord | null>(loaded.record),
    recordRef = useRef(record);
  const [factId, setFactId] = useState(
    loaded.record?.pending?.body.fact_id ?? loaded.record?.lastFactId ?? "",
  );
  const [historyId, setHistoryId] = useState(loaded.record?.lastId ?? "");
  const [observation, setObservation] =
    useState<PackageFactScopeObservation | null>(null);
  const [result, setResult] = useState<PackageFactScopeView | null>(null);
  const [selectedFact, setSelectedFact] =
    useState<PackagePreparedFactSummary | null>(null);
  const [subjectKind, setSubjectKind] = useState(""),
    [reason, setReason] = useState("");
  const [error, setError] = useState<unknown>(loaded.error),
    [reading, setReading] = useState(false),
    [busy, setBusy] = useState(false);
  const active = useRef(false),
    writing = useRef(false),
    ticket = useRef(0);
  const base = `${executionPath(scope, frozenId)}/${prepared.manifest.id}`,
    path = `${base}/fact-scope-declarations`;
  const available = supportsApi("POST", path);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  function persist(next: FactScopeRecord) {
    storeFactScopeRecord(next);
    recordRef.current = next;
    setRecord(next);
  }
  function changeFact(value: string) {
    ticket.current++;
    setReading(false);
    setObservation(null);
    setResult(null);
    setSubjectKind("");
    setFactId(value);
    setSelectedFact(null);
  }
  async function observe(id = factId.trim(), expectedFact = selectedFact) {
    if (!executionId(id) || writing.current) return;
    const current = ++ticket.current;
    setReading(true);
    setError(null);
    setObservation(null);
    setSubjectKind("");
    try {
      const { data } = await api<PackageFactScopeObservation>(
        `${base}/facts/${id}/scope-declaration`,
      );
      await validateScopeObservation(data, scope, frozenId, prepared, id);
      if (
        expectedFact?.fact_id === id &&
        data.head &&
        data.head.manifest.binding.fact_item_digest !==
          expectedFact.fact_item_digest
      )
        throw new Error("当前声明与选定原事实摘要不符，未采纳。");
      if (active.current && ticket.current === current) setObservation(data);
    } catch (failure) {
      if (active.current && ticket.current === current) setError(failure);
    } finally {
      if (active.current && ticket.current === current) setReading(false);
    }
  }
  async function readHistory() {
    const id = historyId.trim();
    if (!executionId(id) || writing.current) return;
    const current = ++ticket.current;
    setReading(true);
    setError(null);
    setResult(null);
    try {
      const { data } = await api<PackageFactScopeView>(`${path}/${id}`);
      await validateScopeRecord(data, prepared);
      if (data.manifest.id !== id)
        throw new Error("返回的范围记录不是明确选择的历史记录。");
      if (active.current && ticket.current === current) {
        setResult(data);
        setObservation(null);
        setSubjectKind("");
        setFactId(data.manifest.binding.fact_id);
        setSelectedFact(null);
      }
    } catch (failure) {
      if (active.current && ticket.current === current) setError(failure);
    } finally {
      if (active.current && ticket.current === current) setReading(false);
    }
  }
  const choice = observation?.subject_choices.find(
    (x) => x.kind === subjectKind,
  );
  const canBind =
    !!observation?.matches_prepared_input &&
    observation.provenance_status === "verified" &&
    !!choice;
  const canWithdraw = observation?.head?.manifest.action === "bind";
  async function write(action: "bind" | "withdraw", recover = false) {
    const current = recordRef.current;
    if (!current || writing.current || !available) return;
    if (
      !recover &&
      (current.pending ||
        !observation ||
        (action === "bind" ? !canBind : !canWithdraw) ||
        !reason.trim())
    )
      return;
    const pending: PendingFactScope | null = recover
      ? current.pending
      : observation
        ? {
            key: crypto.randomUUID(),
            body: {
              execution_input_digest: prepared.digest,
              fact_id: observation.fact_id,
              action,
              subject:
                action === "bind" && choice
                  ? { kind: choice.kind, id: choice.id }
                  : null,
              reason: reason.trim(),
              previous_digest: observation.head?.digest ?? null,
            },
          }
        : null;
    if (!pending) return;
    writing.current = true;
    ticket.current++;
    setReading(false);
    setBusy(true);
    setResult(null);
    setError(null);
    setObservation(null);
    try {
      persist({ ...current, pending });
      let data: PackageFactScopeView;
      try {
        ({ data } = await api<PackageFactScopeView>(path, {
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
      await validateScopeRecord(
        data,
        prepared,
        pending.body.fact_id,
        pending.body,
        scope.memberId,
      );
      if (
        selectedFact?.fact_id === pending.body.fact_id &&
        data.manifest.binding.fact_item_digest !== selectedFact.fact_item_digest
      )
        throw new Error("保存回执与选定原事实摘要不符；原请求仍保留。");
      if (!active.current) return;
      persist({
        ...current,
        pending: null,
        lastId: data.manifest.id,
        lastFactId: pending.body.fact_id,
      });
      setFactId(pending.body.fact_id);
      setSelectedFact((value) =>
        value?.fact_id === pending.body.fact_id ? value : null,
      );
      setHistoryId(data.manifest.id);
      setObservation(null);
      setSubjectKind("");
      setReason("");
      setResult(data);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      writing.current = false;
      if (active.current) setBusy(false);
    }
  }
  return (
    <details
      className="package-frozen-input__fact-scope"
      open={record?.pending ? true : undefined}
    >
      <summary>事实适用范围</summary>
      <p>
        明确事实适用的工程、标段、轮次或投标主体。声明另行留存，不改旧准备快照；仍需正式资格核验。
      </p>
      {!available && <p>当前服务尚未提供事实范围保存。</p>}
      {record?.pending && (
        <div role="status">
          <p>有一条范围操作的结果尚未确认。请按原请求恢复，再进行其他保存。</p>
          <p>
            原操作：
            {record.pending.body.action === "bind" ? "声明范围" : "撤回声明"}
            ；理由：{record.pending.body.reason}
          </p>
          <p>
            原事实编号：<code>{record.pending.body.fact_id}</code>
          </p>
          <button
            type="button"
            className="button secondary"
            disabled={busy || !available}
            onClick={() => void write(record.pending!.body.action, true)}
          >
            {busy ? "正在恢复原请求…" : "恢复范围原请求"}
          </button>
        </div>
      )}
      <PackagePreparedFactPicker
        scope={scope}
        frozenId={frozenId}
        prepared={prepared}
        disabled={busy}
        onSelect={(item) => {
          changeFact(item.fact_id);
          setSelectedFact(item);
          void observe(item.fact_id, item);
        }}
      />
      {selectedFact && (
        <div role="status">
          <p>
            选定原事实：{selectedFact.name} · {selectedFact.value_preview}
            {selectedFact.unit ? ` ${selectedFact.unit}` : ""}
          </p>
          <p>
            原主体：{selectedFact.subject}；原范围：{selectedFact.scope}
            。自由文本仅作原记录展示，适用对象仍须明确选择。
          </p>
          {selectedFact.preview_truncated && (
            <p>摘要有截断，请结合完整原资料核对。</p>
          )}
        </div>
      )}
      <label>
        待核对的事实编号
        <input
          value={factId}
          list={`fact-scope-${prepared.manifest.id}`}
          disabled={busy}
          onChange={(e) => changeFact(e.target.value)}
          placeholder="选择逐项核对中的事实，或输入原事实编号"
        />
      </label>
      <datalist id={`fact-scope-${prepared.manifest.id}`}>
        {factIds.map((id) => (
          <option value={id} key={id} />
        ))}
      </datalist>
      <button
        type="button"
        className="button secondary"
        disabled={busy || reading || !executionId(factId.trim())}
        onClick={() => void observe()}
      >
        {reading ? "正在读取范围…" : "读取当前事实范围"}
      </button>
      {observation && (
        <div role="status">
          <p>
            {observation.binding_status === "matches_current_input"
              ? "范围声明与当前输入匹配。"
              : observation.binding_status === "withdrawn"
                ? "此事实的范围声明已撤回。"
                : observation.head
                  ? "已有声明，但当前适用性仍待核对。"
                  : "此事实尚无范围声明。"}
          </p>
          {!observation.matches_prepared_input && (
            <p>
              当前输入已变化或无法完整核对。旧声明保留；新绑定需重新准备输入，已有声明仍可撤回。
            </p>
          )}
          {observation.provenance_status === "unproven" && (
            <p>事实依据链尚未证明，暂不能新增范围声明。</p>
          )}
          <p>
            观察时间：{new Date(observation.checked_at).toLocaleString()}
            。此观察不授予执行资格。
          </p>
          {observation.head && (
            <p>
              当前声明编号：<code>{observation.head.manifest.id}</code>；理由：
              {observation.head.manifest.reason}
            </p>
          )}
          <label>
            明确适用对象
            <select
              value={subjectKind}
              disabled={busy || !!record?.pending}
              onChange={(e) => setSubjectKind(e.target.value)}
            >
              <option value="">请选择适用对象</option>
              {observation.subject_choices.map((x) => (
                <option key={x.kind} value={x.kind}>
                  {scopeLabels[x.kind]}：{x.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            声明或撤回理由
            <textarea
              value={reason}
              maxLength={2000}
              disabled={busy || !!record?.pending}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
            />
          </label>
          <div className="package-frozen-input__fact-scope-actions">
            <button
              type="button"
              className="button secondary"
              disabled={
                !record ||
                busy ||
                !!record.pending ||
                !available ||
                !canBind ||
                !reason.trim()
              }
              onClick={() => void write("bind")}
            >
              保存范围声明
            </button>
            <button
              type="button"
              className="button secondary"
              disabled={
                !record ||
                busy ||
                !!record.pending ||
                !available ||
                !canWithdraw ||
                !reason.trim()
              }
              onClick={() => void write("withdraw")}
            >
              撤回范围声明
            </button>
          </div>
        </div>
      )}
      {result && (
        <div role="status">
          <p>
            范围{result.manifest.action === "withdraw" ? "撤回" : "声明"}
            记录已读回校验；当前有效性需另行重读。
          </p>
          <p>
            记录编号：<code>{result.manifest.id}</code>
          </p>
          <p>
            适用对象：{scopeLabels[result.manifest.subject.kind]}；理由：
            {result.manifest.reason}
          </p>
        </div>
      )}
      <details>
        <summary>读取已有范围记录</summary>
        <label>
          范围记录编号
          <input
            value={historyId}
            disabled={busy}
            onChange={(e) => {
              ticket.current++;
              setReading(false);
              setResult(null);
              setHistoryId(e.target.value);
            }}
          />
        </label>
        <button
          type="button"
          className="button secondary"
          disabled={busy || reading || !executionId(historyId.trim())}
          onClick={() => void readHistory()}
        >
          读取范围原记录
        </button>
      </details>
      {error != null && <ErrorNotice error={error} />}
    </details>
  );
}
