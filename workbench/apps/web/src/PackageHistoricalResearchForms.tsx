import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type {
  PackageHistoricalAdmission,
  PackageHistoricalAdmissionView,
  PackageHistoricalProtocol,
  PackageHistoricalProtocolTemplate,
  PackageHistorySelection,
} from "./contracts";
import { ErrorNotice } from "./components";
import {
  historyBase,
  validateHistoryAdmission,
  validateHistoryTemplate,
} from "./packageHistoricalResearchProtocol";
import { usePackageHistoryDirectory } from "./usePackageHistoryDirectory";
import {
  HistoryDirectoryStatus,
  type HistoryCommands,
} from "./PackageHistoricalResearchCommon";
import {
  HistoryAdmissionDetails,
  HistoryOrigin,
  HistoryProtocolDetails,
} from "./PackageHistoricalResearchDetails";
import { historyPurposeNames, historyTime } from "./packageHistoryPresentation";

export type HistorySelection = {
  admission: PackageHistoricalAdmission;
  purpose: PackageHistorySelection["purpose"] | "";
};
const noFilters = {
  bid_id: null,
  scope_id: null,
  protocol_id: null,
  cohort_id: null,
};

export function HistoryAdmissionPicker({
  selected,
  onSelected,
  commands,
  onOpenBid,
  onContinue,
}: {
  selected: HistorySelection[];
  onSelected: (value: HistorySelection[]) => void;
  commands: HistoryCommands;
  onOpenBid?: (bidId: string) => void;
  onContinue: () => void;
}) {
  const directory = usePackageHistoryDirectory("admissions", noFilters);
  const [details, setDetails] = useState<PackageHistoricalAdmissionView | null>(
    null,
  );
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  const active = useRef(false),
    running = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  async function open(id: string, digest: string) {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    setDetails(null);
    try {
      const response = await api<unknown>(`${historyBase}/admissions/${id}`);
      const checked = await validateHistoryAdmission(
        response.data,
        id,
        response.etag,
      );
      if (checked.admission.digest !== digest)
        throw new Error(
          "准入详情与所选目录的原记录摘要不一致，未使用这份资料。",
        );
      if (active.current) setDetails(checked);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  const alreadySelected =
    details &&
    selected.some(
      (item) =>
        item.admission.submission_id === details.admission.submission_id,
    );
  return (
    <section className="package-history-step" aria-label="选择已准入资料">
      <h3>1. 选择已经独立核验的整包资料</h3>
      <p className="small-note">
        新准入从项目内的确切技术范围、实交和官方成绩发起。本页只发现已保存的准入记录，不补造配对资料或历史时点。
      </p>
      <HistoryDirectoryStatus
        noun="准入资料"
        page={directory.page}
        count={directory.items.length}
        busy={directory.busy}
        error={directory.error}
        onLoad={() => void directory.load()}
        onMore={() => void directory.load(true)}
      />
      <div className="package-history-directory-list">
        {directory.items.map((item, index) => (
          <article
            className="package-history-record"
            key={item.id}
            aria-current={
              details?.admission.id === item.id ? "true" : undefined
            }
          >
            <strong>
              整包资料 {index + 1} · {historyTime(item.historical_as_of)}
            </strong>
            <HistoryOrigin origin={item.origin} />
            <p className="small-note">
              标签知悉：{historyTime(item.label_known_at)}
              <br />
              准入登记：{historyTime(item.created_at)}
            </p>
            <small>记录 {item.id}</small>
            <button
              type="button"
              className="button secondary"
              disabled={busy || directory.busy || !!directory.error}
              onClick={() => void open(item.id, item.digest)}
            >
              核对资料 {index + 1} 的准入详情
            </button>
          </article>
        ))}
      </div>
      {busy && <p role="status">正在核对这一份准入记录的当前依据…</p>}
      <ErrorNotice error={error} />
      {details && (
        <section className="package-history-record" aria-label="当前准入详情">
          <h4>已读取的准入依据</h4>
          <HistoryAdmissionDetails value={details} onOpenBid={onOpenBid} />
          <button
            type="button"
            className="button primary"
            disabled={
              commands.blocked ||
              !details.current ||
              !!alreadySelected ||
              selected.length >= 1000
            }
            onClick={() =>
              onSelected([
                ...selected,
                { admission: details.admission, purpose: "" },
              ])
            }
          >
            {alreadySelected ? "该实交已在本次选择中" : "明确选入研究方案"}
          </button>
        </section>
      )}
      <HistorySelectionEditor
        selected={selected}
        onSelected={onSelected}
        disabled={commands.blocked}
      />
      <div>
        <button type="button" className="button primary" onClick={onContinue}>
          继续核对研究协议与分组
        </button>
      </div>
    </section>
  );
}

export function HistorySelectionEditor({
  selected,
  onSelected,
  disabled,
}: {
  selected: HistorySelection[];
  onSelected: (value: HistorySelection[]) => void;
  disabled: boolean;
}) {
  return (
    <section
      className="package-history-selection"
      aria-label="本次明确选择的资料"
    >
      <h4>本次选择 {selected.length} 份资料</h4>
      {!selected.length && (
        <p className="small-empty">
          尚未选择资料。读取准入目录并核对详情后，逐份明确选入。
        </p>
      )}
      {selected.map((item, index) => (
        <div className="package-history-selection-row" key={item.admission.id}>
          <div>
            <strong>已选资料 {index + 1}</strong>
            <small>
              {historyTime(item.admission.historical_as_of)} ·{" "}
              {item.admission.origin === "synthetic"
                ? "合成机制资料"
                : "外部证据资料"}
            </small>
            <small>{item.admission.id}</small>
          </div>
          <label>
            资料 {index + 1} 的请求用途
            <select
              value={item.purpose}
              disabled={disabled}
              onChange={(event) =>
                onSelected(
                  selected.map((previous) =>
                    previous.admission.id === item.admission.id
                      ? {
                          ...previous,
                          purpose: event.target
                            .value as HistorySelection["purpose"],
                        }
                      : previous,
                  ),
                )
              }
            >
              <option value="">明确选择用途</option>
              {(["fit", "development", "calibration", "final"] as const).map(
                (purpose) => (
                  <option value={purpose} key={purpose}>
                    {historyPurposeNames[purpose]}
                  </option>
                ),
              )}
            </select>
          </label>
          <button
            type="button"
            className="text-button"
            disabled={disabled}
            onClick={() =>
              onSelected(
                selected.filter(
                  (previous) => previous.admission.id !== item.admission.id,
                ),
              )
            }
          >
            移除资料 {index + 1}
          </button>
        </div>
      ))}
      <p className="small-note">
        保存时服务端会重新核对完整来源与关联组。至少需要两个独立拟合组、开发选择组和最终评估组；同组不能跨用途。区间校准组可另选，缺少时区间保持未取得。
      </p>
    </section>
  );
}

export function HistoryProtocolPicker({
  selected,
  onSelected,
  commands,
}: {
  selected: PackageHistoricalProtocol | null;
  onSelected: (value: PackageHistoricalProtocol) => void;
  commands: HistoryCommands;
}) {
  const directory = usePackageHistoryDirectory("protocols", noFilters);
  const [template, setTemplate] =
    useState<PackageHistoricalProtocolTemplate | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  const [seed, setSeed] = useState(""),
    [iterations, setIterations] = useState(""),
    [reason, setReason] = useState(""),
    [confirmed, setConfirmed] = useState(false);
  const active = useRef(false),
    running = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  async function loadTemplate() {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    setTemplate(null);
    setConfirmed(false);
    try {
      const response = await api<unknown>(
        `${historyBase}/cpu-protocol-template`,
      );
      const checked = await validateHistoryTemplate(
        response.data,
        response.etag,
      );
      if (active.current) {
        setTemplate(checked);
        setSeed(String(checked.document.seed));
        setIterations(String(checked.document.bootstrap_iterations));
      }
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  async function save() {
    if (!template?.schema_configured || !confirmed) return;
    const receipt = await commands.send({
      kind: "protocol",
      path: `${historyBase}/protocols`,
      key: crypto.randomUUID(),
      etag: null,
      body: {
        method_digest: template.method_digest,
        seed: Number(seed),
        bootstrap_iterations: Number(iterations),
        reason,
      },
      expected: {},
    });
    if (active.current && receipt && "document" in receipt) {
      onSelected(receipt);
      setConfirmed(false);
    }
  }
  return (
    <section className="package-history-form" aria-label="CPU研究协议">
      <h4>选择已冻结协议，或明确冻结一份新协议</h4>
      <HistoryDirectoryStatus
        noun="CPU协议"
        page={directory.page}
        count={directory.items.length}
        busy={directory.busy}
        error={directory.error}
        onLoad={() => void directory.load()}
        onMore={() => void directory.load(true)}
      />
      <div className="package-history-directory-list">
        {directory.items.map((item, index) => (
          <article
            className="package-history-record"
            key={item.id}
            aria-current={selected?.id === item.id ? "true" : undefined}
          >
            <strong>CPU 协议 {index + 1}</strong>
            <p className="small-note">
              种子 {item.document.seed} · 重采样{" "}
              {item.document.bootstrap_iterations} 次<br />
              冻结于 {historyTime(item.created_at)}
            </p>
            <button
              type="button"
              className="button secondary"
              disabled={commands.blocked || directory.busy || !!directory.error}
              onClick={() =>
                onSelected({
                  id: item.id,
                  digest: item.digest,
                  document: item.document,
                  research_only: true,
                  formal_eligibility: "unavailable",
                })
              }
            >
              {selected?.id === item.id
                ? "已选择这份协议"
                : `选择协议 ${index + 1}`}
            </button>
          </article>
        ))}
      </div>
      <details>
        <summary>冻结新 CPU 研究协议</summary>
        <div className="package-history-form">
          <p className="small-note">
            固定 mean/median
            方法与确定的重采样设置，保存协议不会开始训练，也不会调用外部模型。
          </p>
          <div>
            <button
              type="button"
              className="button secondary"
              disabled={busy || commands.blocked}
              onClick={() => void loadTemplate()}
            >
              {busy ? "正在读取方法…" : "读取当前 CPU 方法"}
            </button>
          </div>
          <ErrorNotice error={error} />
          {template && !template.schema_configured && (
            <p className="notice neutral">
              独立历史研究服务未完整配置，暂不能冻结协议。
            </p>
          )}
          {template?.schema_configured && (
            <fieldset
              disabled={commands.blocked}
              className="package-history-form"
            >
              <div className="package-history-form-grid">
                <label>
                  随机种子
                  <input
                    type="number"
                    min={0}
                    max={2147483647}
                    step={1}
                    value={seed}
                    onChange={(event) => {
                      setSeed(event.target.value);
                      setConfirmed(false);
                    }}
                  />
                </label>
                <label>
                  组级重采样次数
                  <input
                    type="number"
                    min={100}
                    max={10000}
                    step={1}
                    value={iterations}
                    onChange={(event) => {
                      setIterations(event.target.value);
                      setConfirmed(false);
                    }}
                  />
                </label>
              </div>
              <label>
                冻结协议的原因
                <textarea
                  value={reason}
                  maxLength={4000}
                  rows={2}
                  onChange={(event) => {
                    setReason(event.target.value);
                    setConfirmed(false);
                  }}
                />
              </label>
              <label className="package-history-check">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(event) => setConfirmed(event.target.checked)}
                />
                我已核对 CPU 方法、种子与重采样设置，仅冻结回溯研究协议。
              </label>
              <div>
                <button
                  type="button"
                  className="button primary"
                  disabled={
                    !confirmed ||
                    !reason.trim() ||
                    !seed ||
                    !iterations ||
                    !Number.isSafeInteger(Number(seed)) ||
                    !Number.isSafeInteger(Number(iterations)) ||
                    Number(seed) < 0 ||
                    Number(seed) > 2147483647 ||
                    Number(iterations) < 100 ||
                    Number(iterations) > 10000
                  }
                  onClick={() => void save()}
                >
                  明确冻结 CPU 协议
                </button>
              </div>
            </fieldset>
          )}
        </div>
      </details>
      {selected && (
        <article className="package-history-record">
          <h4>本次明确选择的协议</h4>
          <HistoryProtocolDetails value={selected} />
        </article>
      )}
    </section>
  );
}

export function HistoryCohortForm({
  selected,
  onSelected,
  protocol,
  onProtocol,
  commands,
}: {
  selected: HistorySelection[];
  onSelected: (value: HistorySelection[]) => void;
  protocol: PackageHistoricalProtocol | null;
  onProtocol: (value: PackageHistoricalProtocol) => void;
  commands: HistoryCommands;
}) {
  const [split, setSplit] = useState(""),
    [cutoff, setCutoff] = useState(""),
    [precise, setPrecise] = useState(false),
    [preciseSplit, setPreciseSplit] = useState(""),
    [preciseCutoff, setPreciseCutoff] = useState(""),
    [reason, setReason] = useState(""),
    [confirmed, setConfirmed] = useState(false);
  const zonedTime =
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/;
  const splitTime = precise
    ? preciseSplit
    : `${split}${split.length === 16 ? ":00" : ""}+08:00`;
  const cutoffTime = precise
    ? preciseCutoff
    : `${cutoff}${cutoff.length === 16 ? ":00" : ""}+08:00`;
  const timeReady = [splitTime, cutoffTime].every(
    (value) => zonedTime.test(value) && Number.isFinite(Date.parse(value)),
  );
  const selectionKey = JSON.stringify(
    selected.map((item) => ({ id: item.admission.id, purpose: item.purpose })),
  );
  useEffect(() => setConfirmed(false), [selectionKey, protocol?.id]);
  const mixed = new Set(selected.map((item) => item.admission.origin)).size > 1;
  const purposesReady =
    selected.length >= 4 &&
    selected.every((item) => item.purpose) &&
    selected.filter((item) => item.purpose === "fit").length >= 2 &&
    selected.some((item) => item.purpose === "development") &&
    selected.some((item) => item.purpose === "final");
  async function save() {
    if (!protocol || !purposesReady || !confirmed || mixed || !timeReady)
      return;
    await commands.send({
      kind: "cohort",
      path: `${historyBase}/cohorts`,
      key: crypto.randomUUID(),
      etag: null,
      body: {
        protocol_id: protocol.id,
        submission_split_at: splitTime,
        label_available_as_of: cutoffTime,
        selections: selected.map((item) => ({
          admission_id: item.admission.id,
          purpose: item.purpose as PackageHistorySelection["purpose"],
        })),
        reason,
      },
      expected: { protocolDigest: protocol.digest },
    });
  }
  return (
    <section className="package-history-step" aria-label="冻结研究方案">
      <h3>2. 冻结协议、用途和时间边界</h3>
      <HistoryProtocolPicker
        selected={protocol}
        onSelected={onProtocol}
        commands={commands}
      />
      <HistorySelectionEditor
        selected={selected}
        onSelected={onSelected}
        disabled={commands.blocked}
      />
      {mixed && (
        <p className="notice warning">
          合成机制资料与外部证据不能混为同一研究组，请分别选择。
        </p>
      )}
      <fieldset className="package-history-form" disabled={commands.blocked}>
        <label className="package-history-check">
          <input
            type="checkbox"
            checked={precise}
            onChange={(event) => {
              setPrecise(event.target.checked);
              setConfirmed(false);
            }}
          />
          使用含时区的精确时间（可保留微秒）
        </label>
        <div className="package-history-form-grid" hidden={precise}>
          <label>
            实交分界（北京时间 UTC+08:00）
            <input
              type="datetime-local"
              step="1"
              value={split}
              onChange={(event) => {
                setSplit(event.target.value);
                setConfirmed(false);
              }}
            />
          </label>
          <label>
            标签可用截止（北京时间 UTC+08:00）
            <input
              type="datetime-local"
              step="1"
              value={cutoff}
              onChange={(event) => {
                setCutoff(event.target.value);
                setConfirmed(false);
              }}
            />
          </label>
        </div>
        {precise && (
          <>
            <div className="package-history-form-grid">
              <label>
                精确实交分界（必须含时区）
                <input
                  type="text"
                  value={preciseSplit}
                  placeholder="2026-10-22T09:00:00.123456+08:00"
                  onChange={(event) => {
                    setPreciseSplit(event.target.value);
                    setConfirmed(false);
                  }}
                />
              </label>
              <label>
                精确标签可用截止（必须含时区）
                <input
                  type="text"
                  value={preciseCutoff}
                  placeholder="2026-10-22T09:00:00.123456+08:00"
                  onChange={(event) => {
                    setPreciseCutoff(event.target.value);
                    setConfirmed(false);
                  }}
                />
              </label>
            </div>
            <p className="small-note">
              使用完整 ISO 8601 时间，明确填写 Z 或 ±HH:MM
              时区；最多保留六位小数，按原值冻结，不自动舍入或转换为本机时区。
            </p>
          </>
        )}
        <p className="small-note">
          最终评估使用分界时点及之后的实交；其余用途在分界前。原实交时点和训练冻结时点由原记录与服务端固定，不能在本表回填。
        </p>
        <label>
          冻结研究组的原因
          <textarea
            value={reason}
            maxLength={4000}
            rows={3}
            onChange={(event) => {
              setReason(event.target.value);
              setConfirmed(false);
            }}
          />
        </label>
        <label className="package-history-check">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          我已核对所选协议、全部资料用途和两个时间边界。接受服务端按完整关联组排除；最终集曝光后不能重新选组。
        </label>
        <div>
          <button
            type="button"
            className="button primary"
            disabled={
              !protocol ||
              !purposesReady ||
              mixed ||
              !confirmed ||
              !timeReady ||
              !reason.trim()
            }
            onClick={() => void save()}
          >
            明确冻结研究组
          </button>
        </div>
      </fieldset>
      {!purposesReady && (
        <p className="small-note">
          请至少选择四份资料，并明确两个拟合、一个开发选择和一个最终评估用途。真实独立分组仍由服务端复核。
        </p>
      )}
    </section>
  );
}
