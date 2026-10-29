import { useEffect, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import { ErrorNotice } from "./components";
import type {
  PackageHistoricalAdmission as Admission,
  PackageHistoricalAdmissionContext as AdmissionContext,
  PackageSubmissionView,
  PackageTechnicalScopeView,
  ResearchOutcomeView,
} from "./contracts";
import { outcomeInstant } from "./packageOutcomeProtocol";
import { usePackageScopeGuard } from "./packageScopeGuard";
import {
  definitiveHistoryFailure,
  validateHistoryAdmissionContext,
  validateHistoryReceipt,
  type HistoryPending,
} from "./packageHistoricalResearchProtocol";
import {
  readHistoryRecovery,
  writeHistoryRecovery,
} from "./packageHistoricalResearchRecovery";
import "./PackageHistoricalAdmission.css";

const when = (value: string | null) =>
  value === null
    ? "尚未取得"
    : new Date(value).toLocaleString("zh-CN", {
        timeZone: "Asia/Shanghai",
        hour12: false,
      });
const decimal = (value: string | null) =>
  value?.replace(/\.0+$/, "").replace(/(\.[0-9]*[1-9])0+$/, "$1") ?? null;

type Props = {
  memberId: string;
  saved: PackageTechnicalScopeView;
  submission: PackageSubmissionView | null;
  outcome: ResearchOutcomeView | null;
  activePurpose?: boolean;
};

export function PackageHistoricalAdmission(props: Props) {
  return (
    <AdmissionWorkspace
      key={`${props.memberId}:${props.saved.manifest.id}:${props.saved.digest}`}
      {...props}
    />
  );
}

function AdmissionWorkspace({
  memberId,
  saved,
  submission,
  outcome,
  activePurpose = true,
}: Props) {
  const scope = saved.manifest.preview.manifest.scope;
  const scopeId = saved.manifest.id;
  const workspace = `admission:${scope.bid_id}:${scopeId}`;
  const base = `/bids/${scope.bid_id}/packages/${scope.package_id}/revisions/${scope.revision_id}/technical-scopes/${scopeId}`;
  const [initial] = useState(() => {
    try {
      return { pending: readHistoryRecovery(memberId, workspace), error: null };
    } catch (error) {
      return { pending: null, error };
    }
  });
  const [pending, setPending] = useState<HistoryPending | null>(
    initial.pending,
  );
  const [error, setError] = useState<unknown>(initial.error);
  const [context, setContext] = useState<{
    data: AdmissionContext;
    etag: string;
    selection: string;
  } | null>(null);
  const [proofId, setProofId] = useState("");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [readBusy, setReadBusy] = useState(false);
  const [sendBusy, setSendBusy] = useState(false);
  const [result, setResult] = useState<Admission | null>(null);
  const active = useRef(false);
  const sending = useRef(false);
  const recorded = useRef(pending);
  const ticket = useRef(0);
  const selectionKey = `${submission?.id ?? ""}:${outcome?.id ?? ""}`;
  const selected = useRef(selectionKey);
  selected.current = selectionKey;
  const dirty = !!reason.trim() || !!proofId || confirmed;
  usePackageScopeGuard(`historical-admission:${scopeId}`, {
    busy: readBusy || sendBusy,
    pending: !!pending || !!initial.error,
    dirty,
  });
  useEffect(() => {
    if (!dirty) return;
    const leaving = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", leaving);
    return () => window.removeEventListener("beforeunload", leaving);
  }, [dirty]);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    ticket.current++;
    setContext(null);
    setProofId("");
    setConfirmed(false);
    setReadBusy(false);
  }, [selectionKey]);

  const subject = submission?.package_binding.manifest.subject;
  const selectionValid =
    submission !== null &&
    outcome !== null &&
    submission.bid_id === scope.bid_id &&
    subject?.package_id === scope.package_id &&
    subject?.revision_id === scope.revision_id &&
    outcome.bid_id === scope.bid_id &&
    outcome.submission_id === submission.id;
  const visible = context?.selection === selectionKey ? context : null;
  const proof = visible?.data.proofs.find((entry) => entry.id === proofId);
  const blocked =
    !visible ||
    visible.data.blockers.some(
      (item) =>
        item.code !== "PACKAGE_HISTORY_EXTERNAL_PROOF_ADAPTER_NOT_CONFIGURED" ||
        proof?.origin !== "synthetic",
    );
  const locked = sendBusy || pending !== null || initial.error !== null;

  function remember(value: HistoryPending | null) {
    writeHistoryRecovery(memberId, workspace, value);
    recorded.current = value;
    setPending(value);
  }

  async function readContext() {
    if (
      !activePurpose ||
      !selectionValid ||
      !submission ||
      !outcome ||
      readBusy ||
      sendBusy
    )
      return;
    const current = ++ticket.current;
    const chosen = selectionKey;
    setContext(null);
    setProofId("");
    setConfirmed(false);
    setReadBusy(true);
    setError(null);
    try {
      const query = new URLSearchParams({
        submission_id: submission.id,
        outcome_id: outcome.id,
      });
      const response = await api<unknown>(
        `${base}/historical-admission-context?${query}`,
      );
      const data = await validateHistoryAdmissionContext(
        response.data,
        { scopeId, submissionId: submission.id, outcomeId: outcome.id },
        response.etag,
      );
      if (
        (data.scope_frozen_at !== null &&
          outcomeInstant(data.scope_frozen_at) !==
            outcomeInstant(saved.manifest.frozen_at)) ||
        (data.historical_as_of !== null &&
          outcomeInstant(data.historical_as_of) !==
            outcomeInstant(submission.submitted_at)) ||
        (data.label_known_at !== null &&
          outcomeInstant(data.label_known_at) !==
            outcomeInstant(outcome.known_at)) ||
        (data.official_technical_value !== null &&
          (outcome.score_kind !== "technical_total" ||
            decimal(data.official_technical_value) !==
              decimal(outcome.value))) ||
        (data.official_maximum !== null &&
          decimal(data.official_maximum) !== decimal(outcome.maximum))
      )
        throw new Error(
          "历史准入依据与所选原记录不一致，请重新读取实交与成绩。",
        );
      if (
        !active.current ||
        current !== ticket.current ||
        chosen !== selected.current
      )
        return;
      setContext({ data, etag: response.etag!, selection: chosen });
    } catch (failure) {
      if (
        active.current &&
        current === ticket.current &&
        chosen === selected.current
      )
        setError(failure);
    } finally {
      if (active.current && current === ticket.current) setReadBusy(false);
    }
  }

  async function send(command: HistoryPending) {
    if (sending.current || initial.error || command.kind !== "admission")
      return;
    if (
      recorded.current &&
      JSON.stringify(recorded.current) !== JSON.stringify(command)
    ) {
      setError(new Error("尚有未核对的原准入请求，请先恢复原请求结果。"));
      return;
    }
    sending.current = true;
    setSendBusy(true);
    setError(null);
    try {
      if (!recorded.current) remember(command);
      const response = await api<unknown>(command.path, {
        method: "POST",
        body: command.body,
        etag: command.etag,
        key: command.key,
      });
      const checked = await validateHistoryReceipt(
        response.data,
        command,
        response.etag,
      );
      if (
        !("schema" in checked) ||
        checked.schema !== "package-historical-research-admission/1"
      )
        throw new Error("原准入回执类型不一致，已保留原请求供核对。");
      if (!active.current) return;
      remember(null);
      setResult(checked as Admission);
      setConfirmed(false);
      setContext(null);
      setProofId("");
      setReason("");
    } catch (failure) {
      if (!active.current) return;
      if (recorded.current && definitiveHistoryFailure(failure)) {
        try {
          remember(null);
          setContext(null);
          setProofId("");
          setConfirmed(false);
        } catch (storageError) {
          setError(storageError);
          return;
        }
      }
      setError(failure);
    } finally {
      sending.current = false;
      if (active.current) setSendBusy(false);
    }
  }

  function admit() {
    if (
      !activePurpose ||
      locked ||
      !selectionValid ||
      !submission ||
      !outcome ||
      !visible ||
      !visible.data.schema_configured ||
      blocked ||
      !visible.data.context_digest ||
      !proof ||
      !confirmed ||
      !reason.trim()
    )
      return;
    void send({
      kind: "admission",
      path: `${base}/historical-admissions`,
      key: crypto.randomUUID(),
      etag: visible.etag,
      body: {
        submission_id: submission.id,
        outcome_id: outcome.id,
        proof_id: proof.id,
        context_digest: visible.data.context_digest,
        reason: reason.trim(),
      },
      expected: {
        bidId: scope.bid_id,
        packageId: scope.package_id,
        revisionId: scope.revision_id,
        scopeId,
        scopeDigest: saved.digest,
        submissionBindingDigest: submission.package_binding.digest,
        proofOrigin: proof.origin,
      },
    });
  }

  return (
    <section
      className="panel package-history-admission"
      aria-label="严格整包历史准入"
      hidden={!activePurpose && !dirty && !pending && !initial.error && !result}
    >
      <h4>保存整包历史研究准入</h4>
      <p>
        为上方明确选择的技术范围、实交和官方成绩读取独立核验回执。
        准入记录用于回溯研究；保存后仍须在评分研究中明确选择研究用途。
      </p>
      {!activePurpose && (
        <p className="small-note">
          已保留这份历史准入的输入或回执。保存新准入前请切回「历史样本条件」；待核原请求仍可在这里恢复。
        </p>
      )}
      {!selectionValid && (
        <p className="small-empty">
          请先在上方选择同一包修订的实交和官方成绩记录。
        </p>
      )}
      {initial.error != null && (
        <p className="notice warning">
          本地恢复记录无法核对，新准入保持锁定，请保留记录。
        </p>
      )}
      {pending && (
        <div className="notice warning" role="status">
          <p>
            上次准入的回执尚未确认。恢复将沿用原实交、原成绩、原条件和原请求键。
          </p>
          <button
            type="button"
            className="button secondary"
            disabled={sendBusy || !!initial.error}
            onClick={() => void send(pending)}
          >
            {sendBusy ? "正在恢复原准入…" : "恢复原准入请求结果"}
          </button>
        </div>
      )}
      {error != null && <ErrorNotice error={error} />}
      {dirty && !pending && (
        <button
          type="button"
          className="button secondary"
          disabled={readBusy || sendBusy}
          onClick={() => {
            setContext(null);
            setProofId("");
            setReason("");
            setConfirmed(false);
            setError(null);
          }}
        >
          清空未发送的准入输入
        </button>
      )}
      <button
        type="button"
        className="button secondary"
        disabled={
          !activePurpose ||
          !selectionValid ||
          readBusy ||
          locked ||
          !supportsApi("GET", `${base}/historical-admission-context`)
        }
        onClick={() => void readContext()}
      >
        {readBusy ? "正在读取准入依据…" : "读取所选记录的严格准入依据"}
      </button>
      {visible && (
        <div aria-label="严格历史准入依据">
          <p className="small-note">
            观察于 {when(visible.data.observed_at)}（北京时间）。
          </p>
          <dl>
            <dt>实交／历史输入截止</dt>
            <dd>{when(visible.data.historical_as_of)}</dd>
            <dt>原范围冻结时间</dt>
            <dd>{when(visible.data.scope_frozen_at)}</dd>
            <dt>官方标签知晓时间</dt>
            <dd>{when(visible.data.label_known_at)}</dd>
            <dt>官方技术分</dt>
            <dd>{visible.data.official_technical_value ?? "未知"}</dd>
            <dt>官方技术满分</dt>
            <dd>{visible.data.official_maximum ?? "未知"}</dd>
          </dl>
          {!visible.data.schema_configured && (
            <p className="notice warning">
              严格历史准入能力未完成装配，当前不能保存准入。
            </p>
          )}
          {visible.data.blockers.length > 0 && (
            <div className="notice warning">
              <h5>
                {blocked ? "本次准入尚缺的条件" : "真实资料仍需补齐的条件"}
              </h5>
              <ul>
                {visible.data.blockers.map((item, index) => (
                  <li key={`${item.code}:${index}`}>{item.message}</li>
                ))}
              </ul>
            </div>
          )}
          <label>
            独立核验回执
            <select
              aria-label="严格历史准入核验回执"
              value={proofId}
              disabled={locked || !activePurpose}
              onChange={(event) => {
                setProofId(event.target.value);
                setConfirmed(false);
              }}
            >
              <option value="">请明确选择已核验回执</option>
              {visible.data.proofs.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.origin === "synthetic"
                    ? "合成机制资料"
                    : "外部证据资料"}
                  {" · "}
                  {when(item.verified_at)} · {item.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          {!visible.data.proofs.length && (
            <p>
              当前没有匹配的独立核验回执。证明需经已配置的独立核验流程取得。
            </p>
          )}
          {proof && (
            <p className="notice neutral">
              已选择
              {proof.origin === "synthetic" ? "合成机制资料" : "外部证据资料"}，
              证据核验时间为 {when(proof.verified_at)}
              。签名或回执的存在本身不证明真实业务效果。
            </p>
          )}
          <label>
            本次准入原因
            <textarea
              aria-label="严格历史准入原因"
              maxLength={4000}
              value={reason}
              disabled={locked || !activePurpose}
              onChange={(event) => {
                setReason(event.target.value);
                setConfirmed(false);
              }}
            />
          </label>
          <label className="package-history-admission__confirm">
            <input
              type="checkbox"
              checked={confirmed}
              disabled={locked || !proof || !activePurpose}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            <span>已核对所选实交、成绩和回执，仅保存回溯研究准入</span>
          </label>
          <button
            type="button"
            className="button primary"
            disabled={
              !activePurpose ||
              locked ||
              !visible.data.schema_configured ||
              blocked ||
              !visible.data.context_digest ||
              !proof ||
              !confirmed ||
              !reason.trim() ||
              !supportsApi("POST", `${base}/historical-admissions`)
            }
            onClick={admit}
          >
            {sendBusy ? "正在保存准入…" : "明确保存这份历史研究准入"}
          </button>
        </div>
      )}
      {result && (
        <div
          className="notice success"
          role="status"
          aria-label="严格历史准入保存回执"
        >
          <h5>原请求的准入记录已核对</h5>
          <p>
            {result.origin === "synthetic"
              ? "合成机制候选"
              : "外部证据回溯候选"}
            ； 原记录官方技术分 {result.official_technical_value} /{" "}
            {result.technical_maximum}。
            此回执保持原保存内容，后续研究将重新检查当前依据。
          </p>
          <p>
            可到「评分研究 →
            整包历史研究」读取并明确选用。正式样本、正式预测和在线指标资格仍未授予。
          </p>
          <details>
            <summary>查看原记录身份</summary>
            <dl className="technical-scope__identity">
              <dt>准入记录</dt>
              <dd>{result.id}</dd>
              <dt>实交记录</dt>
              <dd>{result.submission_id}</dd>
              <dt>官方成绩</dt>
              <dd>{result.outcome_id}</dd>
              <dt>固定范围摘要</dt>
              <dd>{result.scope_digest}</dd>
            </dl>
          </details>
        </div>
      )}
    </section>
  );
}
