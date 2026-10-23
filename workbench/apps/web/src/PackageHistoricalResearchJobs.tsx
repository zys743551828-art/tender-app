import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type {
  PackageHistoricalCohortView,
  PackageHistoricalJobView,
  PackageHistoryJobControl,
} from "./contracts";
import { Badge, ErrorNotice } from "./components";
import {
  historyBase,
  validateHistoryCohort,
  validateHistoryJob,
} from "./packageHistoricalResearchProtocol";
import { usePackageHistoryDirectory } from "./usePackageHistoryDirectory";
import {
  HistoryDirectoryStatus,
  type HistoryCommands,
} from "./PackageHistoricalResearchCommon";
import {
  HistoryCohortDetails,
  HistoryIdentity,
  HistoryJobResult,
  HistoryOrigin,
} from "./PackageHistoricalResearchDetails";
import { historyStateNames, historyTime } from "./packageHistoryPresentation";

type Tagged<T> = { value: T; etag: string };

export function HistoryJobsWorkspace({
  commands,
  cohortId,
  cohortDigest,
  jobId,
  jobKind,
  revision,
  onSelectCohort,
  onSelectJob,
}: {
  commands: HistoryCommands;
  cohortId: string | null;
  cohortDigest: string | null;
  jobId: string | null;
  jobKind: "train" | "evaluate" | null;
  revision: number;
  onSelectCohort: (id: string, digest: string) => void;
  onSelectJob: (id: string, kind: "train" | "evaluate") => void;
}) {
  const directory = usePackageHistoryDirectory("cohorts", {
    bid_id: null,
    scope_id: null,
    protocol_id: null,
    cohort_id: null,
  });
  const jobs = usePackageHistoryDirectory("jobs", {
    bid_id: null,
    scope_id: null,
    protocol_id: null,
    cohort_id: cohortId,
  });
  const [cohort, setCohort] =
      useState<Tagged<PackageHistoricalCohortView> | null>(null),
    [job, setJob] = useState<Tagged<PackageHistoricalJobView> | null>(null);
  const [cohortBusy, setCohortBusy] = useState(false),
    [jobBusy, setJobBusy] = useState(false);
  const [cohortError, setCohortError] = useState<unknown>(null),
    [jobError, setJobError] = useState<unknown>(null);
  const [startRequiresRead, setStartRequiresRead] = useState(false),
    [controlRequiresRead, setControlRequiresRead] = useState(false);
  const [kind, setKind] = useState<"" | "train" | "evaluate">(""),
    [reason, setReason] = useState(""),
    [confirmed, setConfirmed] = useState(false);
  const [control, setControl] = useState<
      "" | PackageHistoryJobControl["action"]
    >(""),
    [controlReason, setControlReason] = useState(""),
    [controlConfirmed, setControlConfirmed] = useState(false);
  const active = useRef(false),
    cohortTicket = useRef(0),
    jobTicket = useRef(0);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      cohortTicket.current += 1;
      jobTicket.current += 1;
    };
  }, []);
  const readCohort = useCallback(async () => {
    const own = ++cohortTicket.current;
    jobTicket.current += 1;
    setCohort(null);
    setJob(null);
    setCohortError(null);
    setJobError(null);
    setJobBusy(false);
    setConfirmed(false);
    setControlConfirmed(false);
    if (!cohortId) {
      setCohortBusy(false);
      return;
    }
    setCohortBusy(true);
    try {
      const response = await api<unknown>(`${historyBase}/cohorts/${cohortId}`);
      const checked = await validateHistoryCohort(
        response.data,
        cohortId,
        response.etag,
      );
      if (cohortDigest && checked.cohort.digest !== cohortDigest)
        throw new Error(
          "研究组详情与明确选择的原记录摘要不一致，未采用这份响应。",
        );
      if (active.current && own === cohortTicket.current && response.etag) {
        setCohort({ value: checked, etag: response.etag });
        setStartRequiresRead(false);
      }
    } catch (failure) {
      if (active.current && own === cohortTicket.current)
        setCohortError(failure);
    } finally {
      if (active.current && own === cohortTicket.current) setCohortBusy(false);
    }
  }, [cohortId, cohortDigest]);
  useEffect(() => {
    void readCohort();
  }, [readCohort, revision]);
  const readJob = useCallback(async () => {
    const own = ++jobTicket.current;
    setJob(null);
    setJobError(null);
    setControlConfirmed(false);
    if (!jobId || !cohort || cohort.value.cohort.id !== cohortId) {
      setJobBusy(false);
      return;
    }
    setJobBusy(true);
    try {
      const response = await api<unknown>(`${historyBase}/jobs/${jobId}`);
      const checked = await validateHistoryJob(
        response.data,
        jobId,
        response.etag,
        cohort.value.cohort,
      );
      if (jobKind && checked.kind !== jobKind)
        throw new Error("任务详情与所选原任务用途不一致，未采用这份响应。");
      if (active.current && own === jobTicket.current && response.etag) {
        setJob({ value: checked, etag: response.etag });
        setControl("");
        setControlRequiresRead(false);
      }
    } catch (failure) {
      if (active.current && own === jobTicket.current) setJobError(failure);
    } finally {
      if (active.current && own === jobTicket.current) setJobBusy(false);
    }
  }, [jobId, jobKind, cohort, cohortId]);
  useEffect(() => {
    void readJob();
  }, [readJob, revision]);
  useEffect(() => {
    setKind("");
    setReason("");
    setConfirmed(false);
    setControl("");
    setControlReason("");
    setControlConfirmed(false);
  }, [cohortId]);
  useEffect(() => {
    setControl("");
    setControlReason("");
    setControlConfirmed(false);
  }, [jobId]);
  async function start() {
    if (!cohort?.value.current || !kind || !confirmed) return;
    const receipt = await commands.send({
      kind: "job",
      path: `${historyBase}/cohorts/${cohort.value.cohort.id}/jobs`,
      key: crypto.randomUUID(),
      etag: cohort.etag,
      body: { kind, reason },
      expected: { cohortId: cohort.value.cohort.id },
    });
    if (active.current && receipt) {
      setKind("");
      setReason("");
      setConfirmed(false);
    }
    if (active.current && !receipt) {
      setConfirmed(false);
      setStartRequiresRead(true);
    }
  }
  async function controlJob() {
    if (!job || !control || !controlConfirmed) return;
    const receipt = await commands.send({
      kind: "control",
      path: `${historyBase}/jobs/${job.value.job_id}/control`,
      key: crypto.randomUUID(),
      etag: job.etag,
      body: {
        action: control,
        generation: job.value.generation,
        reason: controlReason,
      },
      expected: { cohortId: job.value.cohort_id, jobKind: job.value.kind },
    });
    if (active.current && receipt) {
      setControl("");
      setControlReason("");
      setControlConfirmed(false);
    }
    if (active.current && !receipt) {
      setControlConfirmed(false);
      setControlRequiresRead(true);
    }
  }
  const jobActive =
    job && !["succeeded", "failed", "cancelled"].includes(job.value.state);
  const currentCohort = cohort?.value.cohort.id === cohortId ? cohort : null;
  return (
    <section className="package-history-step" aria-label="历史研究任务与结果">
      <h3>3. 核对冻结研究组，明确创建或控制任务</h3>
      <p className="small-note">
        可以直接选择已经冻结的研究组。读取历史不重新训练，不打开新的最终评估，也不授予新的执行资格。
      </p>
      <HistoryDirectoryStatus
        noun="研究组"
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
            aria-current={cohortId === item.id ? "true" : undefined}
          >
            <strong>
              研究组 {index + 1} · {item.member_count} 份资料
            </strong>
            <HistoryOrigin origin={item.origin} />
            <p className="small-note">
              实交分界：{historyTime(item.submission_split_at)}
              <br />
              冻结于：{historyTime(item.created_at)}
            </p>
            <small>组 {item.id}</small>
            <button
              type="button"
              className="button secondary"
              disabled={
                commands.busy ||
                cohortBusy ||
                directory.busy ||
                !!directory.error
              }
              onClick={() => {
                if (item.id === cohortId) {
                  void readCohort();
                  return;
                }
                if (
                  item.id !== cohortId &&
                  (reason.trim() || controlReason.trim() || kind || control) &&
                  !window.confirm(
                    "切换研究组会清空当前未发送的任务表单。是否继续切换？",
                  )
                )
                  return;
                onSelectCohort(item.id, item.digest);
              }}
            >
              打开研究组 {index + 1}
            </button>
          </article>
        ))}
      </div>
      {cohortId && (
        <div className="package-history-toolbar">
          <button
            type="button"
            className="text-button"
            disabled={cohortBusy || commands.busy}
            onClick={() => void readCohort()}
          >
            重新核对所选研究组
          </button>
          <span className="small-note">当前选择 {cohortId}</span>
        </div>
      )}
      {cohortBusy && <p role="status">正在核对研究组的当前来源与关联组…</p>}
      <ErrorNotice error={cohortError} />
      {currentCohort && (
        <>
          <article
            className="package-history-record"
            aria-label="当前研究组详情"
          >
            <h4>固定研究组与实际成员</h4>
            <Badge tone={currentCohort.value.current ? "" : "warning"}>
              {currentCohort.value.current
                ? "本次读取时依据有效"
                : "当前依据已变化"}
            </Badge>
            {!currentCohort.value.current && (
              <p className="notice warning">
                来源、成绩或完整关联组已变化。原研究组和已有结果继续保留，本次不能开始新任务或恢复执行。
              </p>
            )}
            <HistoryCohortDetails
              key={currentCohort.value.cohort.digest}
              value={currentCohort.value.cohort}
            />
          </article>
          <fieldset
            className="package-history-form"
            disabled={
              commands.blocked ||
              !currentCohort.value.current ||
              cohortBusy ||
              startRequiresRead
            }
          >
            <h4>明确登记研究任务</h4>
            <label>
              本次任务
              <select
                value={kind}
                onChange={(event) => {
                  setKind(event.target.value as typeof kind);
                  setConfirmed(false);
                }}
              >
                <option value="">请选择任务</option>
                <option value="train">训练 CPU 常数基线</option>
                <option value="evaluate">独立最终评估</option>
              </select>
            </label>
            {kind === "evaluate" && (
              <p className="notice warning">
                独立评估需要同一研究组已冻结的训练结果。最终集曝光会持久记录；之后不能重新选择关联样本来调整结果。
              </p>
            )}
            <label>
              创建任务的原因
              <textarea
                value={reason}
                rows={2}
                maxLength={4000}
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
              我已核对本研究组、任务用途和当前依据，明确登记这一任务。
            </label>
            <div>
              <button
                type="button"
                className="button primary"
                disabled={!kind || !reason.trim() || !confirmed}
                onClick={() => void start()}
              >
                明确创建研究任务
              </button>
            </div>
          </fieldset>
          {startRequiresRead && (
            <p className="small-note">
              原操作未取得可确认回执。未决原请求先在上方恢复；若已明确拒绝，请「重新核对所选研究组」后再确认新的任务请求。
            </p>
          )}
          <p className="notice neutral">
            任务登记后等待已配置的独立研究服务执行。本工作面不会自动派发或运行训练；同组同类任务会复用原记录，不产生第二份研究结果。
          </p>
          <HistoryDirectoryStatus
            noun="组内任务"
            page={jobs.page}
            count={jobs.items.length}
            busy={jobs.busy}
            error={jobs.error}
            onLoad={() => void jobs.load()}
            onMore={() => void jobs.load(true)}
          />
          <div className="package-history-directory-list">
            {jobs.items.map((item, index) => (
              <article
                className="package-history-record"
                key={item.id}
                aria-current={jobId === item.id ? "true" : undefined}
              >
                <strong>
                  {item.job_kind === "train" ? "CPU 基线训练" : "独立最终评估"}
                </strong>
                <Badge>{historyStateNames[item.state]}</Badge>
                <p className="small-note">
                  第 {item.generation} 代 ·{" "}
                  {item.result_available
                    ? "有已发布结果，打开后核对"
                    : "尚无已发布结果"}
                  <br />
                  登记于 {historyTime(item.created_at)}
                </p>
                <button
                  type="button"
                  className="button secondary"
                  disabled={
                    commands.busy || jobBusy || jobs.busy || !!jobs.error
                  }
                  onClick={() => {
                    if (
                      item.id !== jobId &&
                      (controlReason.trim() || control) &&
                      !window.confirm(
                        "切换任务会清空当前未发送的控制表单。是否继续切换？",
                      )
                    )
                      return;
                    onSelectJob(item.id, item.job_kind);
                  }}
                >
                  打开任务 {index + 1}
                </button>
              </article>
            ))}
          </div>
          {jobId && (
            <div className="package-history-toolbar">
              <button
                type="button"
                className="text-button"
                disabled={jobBusy || commands.busy}
                onClick={() => void readJob()}
              >
                读取所选任务当前状态
              </button>
              <span className="small-note">当前任务 {jobId}</span>
            </div>
          )}
          {jobBusy && <p role="status">正在读取所选任务的当前状态…</p>}
          <ErrorNotice error={jobError} />
          {job && (
            <article
              className="package-history-record"
              aria-label="当前研究任务"
            >
              <div className="package-history-toolbar">
                <h4>
                  {job.value.kind === "train"
                    ? "CPU 基线训练任务"
                    : "独立最终评估任务"}
                </h4>
                <Badge>{historyStateNames[job.value.state]}</Badge>
                <Badge>第 {job.value.generation} 代</Badge>
              </div>
              {!job.value.current && (
                <p className="notice warning">
                  当前依据已变化。历史结果仍按原版本读取；不恢复执行或授予新用途资格。
                </p>
              )}
              {job.value.state === "queued" && (
                <p role="status">
                  任务已登记，等待独立研究服务领取；尚未证明训练或评估完成。
                </p>
              )}
              <HistoryJobResult value={job.value} />
              <HistoryIdentity
                values={{ 任务: job.value.job_id, 研究组: job.value.cohort_id }}
              />
              {jobActive && (
                <fieldset
                  className="package-history-form"
                  disabled={commands.blocked || jobBusy || controlRequiresRead}
                >
                  <label>
                    任务控制动作
                    <select
                      value={control}
                      onChange={(event) => {
                        setControl(event.target.value as typeof control);
                        setControlConfirmed(false);
                      }}
                    >
                      <option value="">请选择控制动作</option>
                      {job.value.state !== "paused" && (
                        <option value="pause">暂停</option>
                      )}
                      {job.value.state === "paused" && (
                        <option value="resume" disabled={!job.value.current}>
                          恢复执行
                        </option>
                      )}
                      <option value="cancel">取消</option>
                    </select>
                  </label>
                  <label>
                    控制任务的原因
                    <textarea
                      value={controlReason}
                      maxLength={4000}
                      rows={2}
                      onChange={(event) => {
                        setControlReason(event.target.value);
                        setControlConfirmed(false);
                      }}
                    />
                  </label>
                  <label className="package-history-check">
                    <input
                      type="checkbox"
                      checked={controlConfirmed}
                      onChange={(event) =>
                        setControlConfirmed(event.target.checked)
                      }
                    />
                    我已核对当前任务、第 {job.value.generation}{" "}
                    代及所选控制动作。
                  </label>
                  <div>
                    <button
                      type="button"
                      className="button secondary"
                      disabled={
                        !control ||
                        !controlReason.trim() ||
                        !controlConfirmed ||
                        (control === "resume" && !job.value.current)
                      }
                      onClick={() => void controlJob()}
                    >
                      明确执行任务控制
                    </button>
                  </div>
                </fieldset>
              )}
              {controlRequiresRead && (
                <p className="small-note">
                  原控制操作未取得可确认回执。未决请求先恢复原结果；若已明确拒绝，请「读取所选任务当前状态」后再确认新的控制动作。
                </p>
              )}
            </article>
          )}
        </>
      )}
    </section>
  );
}
