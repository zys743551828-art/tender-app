import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { MaterialExecutionStatus } from "./MaterialExecutionStatus";
import { ErrorNotice } from "./components";
import { jsonDigest } from "./editorSchema";
import {
  executionId as uuid,
  executionSha as sha,
  recordObject as object,
} from "./executionInputValidation";

type Qualification = {
  id: string;
  digest: string;
  revision: number;
  state: string;
};
type Pending = { key: string; etag: string; body: Record<string, unknown> };
type Receipt = {
  request_digest: string;
  intent_id: string;
  state: string;
  pending_reason: string | null;
  job: { job_id: string; job_digest: string; generation: number } | null;
};
export function QualifiedMaterialJob({
  base,
  scopeId,
  scopeDigest,
  memberId,
  qualification,
}: {
  base: string;
  scopeId: string;
  scopeDigest: string;
  memberId: string;
  qualification: Qualification | null;
}) {
  const storage = `qualified-material-job:${memberId}:${scopeId}:${scopeDigest}`;
  const [renewal, setRenewal] = useState(""),
    [renewalDigest, setRenewalDigest] = useState("");
  const [pending, setPending] = useState<Pending | null>(null),
    [receipt, setReceipt] = useState<Receipt | null>(null);
  const [busy, setBusy] = useState(false),
    [corrupt, setCorrupt] = useState(false),
    [error, setError] = useState<unknown>(null);
  const context = useRef(storage),
    generation = useRef(0);
  context.current = storage;
  const active = useRef(false),
    running = useRef(false);
  function valid(p: Pending) {
    const b = p.body;
    return (
      uuid(p.key) &&
      typeof p.etag === "string" &&
      object(b) &&
      b.version === "material-qualified-job-request/1" &&
      b.scope_digest === scopeDigest &&
      uuid(b.qualification_id) &&
      sha(b.qualification_digest) &&
      Number.isSafeInteger(b.qualification_revision) &&
      (b.qualification_revision as number) >= 1 &&
      uuid(b.renewal_id) &&
      sha(b.renewal_digest) &&
      p.etag ===
        `"material-qualification:${b.qualification_id}:${b.qualification_revision}"`
    );
  }
  useEffect(() => {
    active.current = true;
    generation.current++;
    running.current = false;
    setReceipt(null);
    setPending(null);
    setBusy(false);
    setCorrupt(false);
    setError(null);
    try {
      const raw = sessionStorage.getItem(storage);
      if (raw) {
        const p = JSON.parse(raw) as Pending;
        if (!valid(p)) throw new Error("固定任务申请损坏，请保留记录后核对。");
        setPending(p);
      }
    } catch (e) {
      setCorrupt(true);
      setError(e);
    }
    return () => {
      active.current = false;
    };
    // The containing review workspace is keyed by member and exact scope.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storage]);
  async function send(old?: Pending) {
    if (running.current) return;
    const requestContext = storage,
      requestGeneration = generation.current;
    running.current = true;
    setBusy(true);
    setError(null);
    try {
      let p = old;
      if (!p) {
        if (!qualification || qualification.state !== "approved")
          throw new Error("请先读取获批资格。");
        p = {
          key: crypto.randomUUID(),
          etag: `"material-qualification:${qualification.id}:${qualification.revision}"`,
          body: {
            version: "material-qualified-job-request/1",
            scope_digest: scopeDigest,
            qualification_id: qualification.id,
            qualification_digest: qualification.digest,
            qualification_revision: qualification.revision,
            renewal_id: renewal,
            renewal_digest: renewalDigest,
          },
        };
      }
      if (!valid(p)) throw new Error("固定材料续验引用不完整。");
      sessionStorage.setItem(storage, JSON.stringify(p));
      setPending(p);
      const result = await api<unknown>(`${base}/material-qualified-jobs`, {
        method: "POST",
        body: p.body,
        etag: p.etag,
        key: p.key,
      });
      const v = result.data;
      if (
        !object(v) ||
        v.version !== "material-qualified-job-receipt/1" ||
        !uuid(v.intent_id) ||
        v.actor_id !== memberId ||
        v.scope_id !== scopeId ||
        v.request_digest !== (await jsonDigest(p.body)) ||
        (await jsonDigest(v.request)) !== (await jsonDigest(p.body)) ||
        v.request_key_digest !== (await jsonDigest(p.key)) ||
        v.send_authorized !== false ||
        v.accuracy_verified !== false ||
        v.fee_state !== "not_observed" ||
        !(v.state === "pending"
          ? v.job === null && typeof v.pending_reason === "string"
          : v.state === "accepted_preparation" &&
            v.pending_reason === null &&
            object(v.job) &&
            uuid(v.job.job_id) &&
            sha(v.job.job_digest) &&
            v.job.generation === 1)
      )
        throw new Error("任务回执身份、原请求或权限声明不一致，保留原请求。");
      if (
        active.current &&
        context.current === requestContext &&
        generation.current === requestGeneration
      )
        setReceipt(v as Receipt);
    } catch (e) {
      if (
        active.current &&
        context.current === requestContext &&
        generation.current === requestGeneration
      )
        setError(e);
    } finally {
      if (
        context.current === requestContext &&
        generation.current === requestGeneration
      ) {
        running.current = false;
        if (active.current) setBusy(false);
      }
    }
  }
  return (
    <section aria-label="获批材料任务接受">
      <h5>登记原生材料准备任务</h5>
      <p>
        使用获批资格和固定材料续验记录。任务接受不等于发送授权，费用状态未在此回执中读取；此入口不启用真实模型调用。
      </p>
      <ErrorNotice error={error} />
      <label>
        材料续验编号
        <input
          value={renewal}
          disabled={busy || !!pending || corrupt}
          onChange={(e) => setRenewal(e.target.value)}
        />
      </label>
      <label>
        材料续验摘要
        <input
          value={renewalDigest}
          disabled={busy || !!pending || corrupt}
          onChange={(e) => setRenewalDigest(e.target.value)}
        />
      </label>
      <button
        disabled={
          busy ||
          !!pending ||
          corrupt ||
          qualification?.state !== "approved" ||
          !uuid(renewal) ||
          !sha(renewalDigest)
        }
        onClick={() => void send()}
      >
        登记固定准备任务
      </button>
      {pending && (
        <button disabled={busy || corrupt} onClick={() => void send(pending)}>
          恢复原任务申请
        </button>
      )}
      {receipt && (
        <div aria-label="原生材料任务回执">
          <p>申请编号：{receipt.intent_id}</p>
          {receipt.job ? (
            <>
              <p>原生准备任务已接受：{receipt.job.job_id}</p>
              <p>任务摘要：{receipt.job.job_digest}</p>
            </>
          ) : (
            <p>任务接受尚未确认：{receipt.pending_reason}</p>
          )}
          <p>本回执不授予发送、收费或准确性资格。</p>
          <MaterialExecutionStatus
            key={`${memberId}:${scopeId}:${receipt.intent_id}`}
            base={base}
            memberId={memberId}
            scopeId={scopeId}
            intentId={receipt.intent_id}
            requestDigest={receipt.request_digest}
            job={receipt.job}
          />
        </div>
      )}
    </section>
  );
}
