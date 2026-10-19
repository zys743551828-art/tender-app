import { useEffect, useRef, useState } from "react";
import { api, ApiError, supportsApi } from "./api";
import { ErrorNotice } from "./components";
import type {
  FreezePackageReviewInput,
  PackageReviewFrozenInputView,
} from "./contracts";
import {
  freezePath,
  loadFreezeRecord,
  storeFreezeRecord,
  validFreezeBody,
  validFrozenInputId,
  validateFrozenInput,
} from "./packageFrozenInput";
import type {
  FreezeRecord,
  FreezeScope,
  PendingFreeze,
} from "./packageFrozenInput";
import "./packageFrozenInput.css";

type Props = {
  scope: FreezeScope;
  candidate: FreezePackageReviewInput | null;
  disabled?: boolean;
};
// Only a first, definitively rejected attempt may release the selection. A retry can follow a lost ACK.
const rejected = new Set([
  "PACKAGE_REVIEW_CONTEXT_CHANGED",
  "PACKAGE_REVIEW_INPUT_CHANGED",
  "PACKAGE_REVIEW_FREEZE_REJECTED",
]);

export default function PackageFrozenInputWorkspace({
  scope,
  ...props
}: Props) {
  return <Workspace key={JSON.stringify(scope)} scope={scope} {...props} />;
}

function Workspace({ scope, candidate, disabled = false }: Props) {
  const [loaded] = useState(() => {
    try {
      return { record: loadFreezeRecord(scope), error: null };
    } catch (error) {
      return { record: null, error };
    }
  });
  const [record, setRecord] = useState<FreezeRecord | null>(loaded.record);
  const recordRef = useRef(record);
  const [error, setError] = useState<unknown>(loaded.error);
  const [busy, setBusy] = useState(false);
  const writing = useRef(false);
  const active = useRef(false);
  const [saved, setSaved] = useState<PackageReviewFrozenInputView | null>(null);
  const [historyId, setHistoryId] = useState(loaded.record?.lastId ?? "");
  const [history, setHistory] = useState<PackageReviewFrozenInputView | null>(
    null,
  );
  const [historyError, setHistoryError] = useState<unknown>(null);
  const [reading, setReading] = useState(false);
  const historyTicket = useRef(0);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const path = freezePath(scope);
  const available = supportsApi("POST", path);
  function persist(next: FreezeRecord) {
    storeFreezeRecord(next);
    recordRef.current = next;
    setRecord(next);
  }
  async function save(recover: boolean) {
    const current = recordRef.current;
    if (
      writing.current ||
      !current ||
      !active.current ||
      !available ||
      (!recover && disabled)
    )
      return;
    const pending: PendingFreeze | null = recover
      ? current.pending
      : !current.pending && candidate && validFreezeBody(candidate)
        ? { key: crypto.randomUUID(), body: { ...candidate } }
        : null;
    if (!pending) return;
    writing.current = true;
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      // A storage failure must happen before any network mutation.
      persist({ ...current, pending });
      let data: PackageReviewFrozenInputView;
      try {
        ({ data } = await api<PackageReviewFrozenInputView>(path, {
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
      await validateFrozenInput(data, scope, pending);
      if (!active.current) return;
      // Persist completion only after every ACK identity check, including its canonical digest.
      persist({ ...current, pending: null, lastId: data.manifest.id });
      setSaved(data);
      setHistoryId(data.manifest.id);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      writing.current = false;
      if (active.current) setBusy(false);
    }
  }
  async function readHistory() {
    const id = historyId.trim();
    if (!validFrozenInputId(id) || !supportsApi("GET", `${path}/${id}`)) return;
    const ticket = ++historyTicket.current;
    setReading(true);
    setHistory(null);
    setHistoryError(null);
    try {
      const { data } = await api<PackageReviewFrozenInputView>(`${path}/${id}`);
      await validateFrozenInput(data, scope, id);
      if (active.current && ticket === historyTicket.current) setHistory(data);
    } catch (failure) {
      if (active.current && ticket === historyTicket.current)
        setHistoryError(failure);
    } finally {
      if (active.current && ticket === historyTicket.current) setReading(false);
    }
  }
  function result(view: PackageReviewFrozenInputView) {
    return (
      <div className="package-frozen-input__result">
        <p>
          记录编号：<code>{view.manifest.id}</code>
        </p>
        <p>
          冻结时间：{new Date(view.manifest.frozen_at).toLocaleString()}。共保留{" "}
          {view.manifest.blockers.length} 项阻断，尚不可正式评审。
        </p>
        <details>
          <summary>冻结身份与边界</summary>
          <p>
            输入摘要：<code>{view.manifest.input_digest}</code>
          </p>
          <p>
            记录摘要：<code>{view.digest}</code>
          </p>
          <p>
            冻结事实 {view.manifest.execution_context.fact_count}{" "}
            条；事实输入资格尚未核验。记录保留保存时的状态，不代表当前来源仍有效。没有创建评审任务。
          </p>
        </details>
      </div>
    );
  }
  return (
    <section className="package-frozen-input" aria-label="冻结输入保存与历史">
      <h4>保存整包评审输入</h4>
      <p>
        核对原件后，可将本次明确选择及执行上下文保存为不可变记录。保存不会启动正式评审。
      </p>
      {!available && <p>当前服务尚未提供冻结输入保存。</p>}
      {!candidate && !record?.pending && (
        <p>先完成本次输入预检和原件核验，再保存。</p>
      )}
      <button
        className="button primary"
        type="button"
        disabled={
          disabled ||
          !available ||
          !record ||
          !!record.pending ||
          !candidate ||
          busy
        }
        onClick={() => void save(false)}
      >
        保存本次冻结输入
      </button>
      {record?.pending && (
        <div>
          <p role="status">
            有一笔保存尚未确认。已保留原始输入和幂等键；即使当前选择变化，也只重试原请求。
          </p>
          <button
            className="button secondary"
            type="button"
            disabled={!available || busy}
            onClick={() => void save(true)}
          >
            {busy ? "正在核对保存结果…" : "恢复原保存请求"}
          </button>
        </div>
      )}
      {error != null && <ErrorNotice error={error} />}
      {saved && (
        <div role="status">
          <p>冻结输入已保存。</p>
          {result(saved)}
        </div>
      )}
      <details>
        <summary>读取历史冻结输入</summary>
        <p>
          输入此清单下的记录编号，从服务端读取原始记录。自动填入本标签页最近成功保存的编号；此处尚无历史目录。
        </p>
        <label>
          冻结输入记录编号
          <input
            value={historyId}
            onChange={(event) => {
              historyTicket.current++;
              setReading(false);
              setHistory(null);
              setHistoryError(null);
              setHistoryId(event.target.value);
            }}
            placeholder="粘贴记录 UUID"
          />
        </label>
        <button
          className="button secondary"
          type="button"
          disabled={
            reading ||
            !validFrozenInputId(historyId.trim()) ||
            !supportsApi("GET", `${path}/${historyId.trim()}`)
          }
          onClick={() => void readHistory()}
        >
          {reading ? "正在读取冻结记录…" : "读取历史记录"}
        </button>
        {historyError != null && <ErrorNotice error={historyError} />}
        {history && result(history)}
      </details>
    </section>
  );
}
