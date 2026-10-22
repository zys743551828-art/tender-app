import { useEffect, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import type {
  PackageSubmissionView,
  PackageTechnicalScopeView,
  ResearchOutcomeView,
} from "./contracts";
import { ErrorNotice } from "./components";
import { outcomeInstant, validateOutcomePage } from "./packageOutcomeProtocol";
import {
  technicalScaleConfigured,
  technicalScales,
  technicalSubmissions,
  type TechnicalScaleChoice,
} from "./packageTechnicalEligibilityCatalog";
import {
  validateTechnicalEligibility,
  type TechnicalEligibility,
  type TechnicalEligibilitySelection,
} from "./packageTechnicalEligibilityProtocol";
import { TechnicalPager } from "./PackageTechnicalScopeSnapshot";
import { PackageHistoricalAdmission } from "./PackageHistoricalAdmission";

const time = (value: string | null) =>
  value === null
    ? "尚未登记"
    : new Date(value).toLocaleString("zh-CN", {
        timeZone: "Asia/Shanghai",
        hour12: false,
      });
const scaleStates: Record<string, string> = {
  pending: "待核对",
  confirmed: "已确认",
  withdrawn: "已撤回",
  superseded: "已被更正",
  needs_revalidation: "需重新核对",
};
const normalizedDecimal = (value: string | null) =>
  value === null
    ? null
    : value.replace(/\.0+$/, "").replace(/(\.[0-9]*[1-9])0+$/, "$1");

export function PackageTechnicalEligibility({
  saved,
  memberId = "",
}: {
  saved: PackageTechnicalScopeView;
  memberId?: string;
}) {
  return (
    <EligibilityWorkspace
      key={`${memberId}:${saved.digest}`}
      saved={saved}
      memberId={memberId}
    />
  );
}

function EligibilityWorkspace({
  saved,
  memberId,
}: {
  saved: PackageTechnicalScopeView;
  memberId: string;
}) {
  const scope = saved.manifest.preview.manifest.scope;
  const base = `/bids/${scope.bid_id}/packages/${scope.package_id}/revisions/${scope.revision_id}/technical-scopes/${saved.manifest.id}`;
  const [purpose, setPurpose] =
    useState<TechnicalEligibilitySelection["purpose"]>("current_prebid");
  const [scaleId, setScaleId] = useState("");
  const [scales, setScales] = useState<TechnicalScaleChoice[]>([]);
  const [scaleStatus, setScaleStatus] = useState("");
  const [submissions, setSubmissions] = useState<PackageSubmissionView[]>([]);
  const [submissionsRead, setSubmissionsRead] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [submissionId, setSubmissionId] = useState("");
  const [outcomes, setOutcomes] = useState<ResearchOutcomeView[]>([]);
  const [outcomesRead, setOutcomesRead] = useState(false);
  const [outcomeId, setOutcomeId] = useState("");
  const [result, setResult] = useState<TechnicalEligibility | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [gapPage, setGapPage] = useState(0);
  const active = useRef(false),
    running = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const chosenSubmission = submissions.find(
    (entry) => entry.id === submissionId,
  );
  const chosenOutcome = outcomes.find((entry) => entry.id === outcomeId);
  const visibleScales = scales.filter(
    (entry) =>
      entry.purpose === purpose &&
      (purpose === "current_prebid" || entry.submission_id === submissionId),
  );

  function clearResult() {
    setResult(null);
    setError(null);
    setGapPage(0);
  }
  function changePurpose(value: TechnicalEligibilitySelection["purpose"]) {
    if (running.current) return;
    setPurpose(value);
    setScaleId("");
    // Keep explicitly chosen historical metadata and its unsent admission form.
    // Purpose-specific scale and condition results are still invalidated below.
    setScales([]);
    setScaleStatus("");
    clearResult();
  }
  async function read(action: () => Promise<void>) {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      running.current = false;
      if (active.current) setBusy(false);
    }
  }
  async function loadScales() {
    await read(async () => {
      const capabilities = await api<unknown>("/technical-scale-capabilities");
      const configured = technicalScaleConfigured(capabilities.data);
      if (!active.current) return;
      if (!configured) {
        setScales([]);
        setScaleStatus("当前服务尚未配置有据满分登记。可继续检查其他缺口。");
        return;
      }
      const response = await api<unknown>(
        `/bids/${scope.bid_id}/technical-scales`,
      );
      const choices = technicalScales(response.data, scope.bid_id);
      if (!active.current) return;
      setScales(choices);
      setScaleStatus(
        choices.length === 200
          ? "已读取最近200条量尺记录，不能据此认定更早记录不存在。"
          : `已读取${choices.length}条量尺记录。选择后将重新核对原文及适用性。`,
      );
    });
  }
  async function loadSubmissions(more = false) {
    await read(async () => {
      const cursor = more ? nextCursor : null;
      const response = await api<unknown>(
        `/bids/${scope.bid_id}/submissions?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
      );
      const page = await technicalSubmissions(response.data, saved);
      if (page.nextCursor !== null && page.nextCursor === cursor)
        throw new Error("实交目录游标未推进，请重新读取。");
      if (!active.current) return;
      if (
        more &&
        page.items.some((entry) =>
          submissions.some((previous) => previous.id === entry.id),
        )
      )
        throw new Error("实交目录出现重复记录，请重新读取。");
      setSubmissions((old) => (more ? [...old, ...page.items] : page.items));
      setNextCursor(page.nextCursor);
      setSubmissionsRead(true);
      if (!more) {
        setSubmissionId("");
        setOutcomeId("");
        setOutcomes([]);
        setOutcomesRead(false);
        setScaleId("");
        clearResult();
      }
    });
  }
  async function loadOutcomes() {
    if (!chosenSubmission) return;
    await read(async () => {
      const response = await api<unknown>(`/bids/${scope.bid_id}/outcomes`);
      const page = validateOutcomePage(response.data, scope.bid_id);
      if (!active.current) return;
      setOutcomes(
        page.items.filter((entry) => entry.submission_id === submissionId),
      );
      setOutcomesRead(true);
      setOutcomeId("");
      clearResult();
    });
  }
  async function check() {
    if (purpose === "historical_backtest" && !chosenSubmission) return;
    clearResult();
    const selection: TechnicalEligibilitySelection = {
      purpose,
      scaleId: scaleId || null,
      ...(purpose === "historical_backtest"
        ? { submissionId, outcomeId: outcomeId || null }
        : {}),
    };
    await read(async () => {
      const query = new URLSearchParams();
      if (scaleId) query.set("scale_id", scaleId);
      if (purpose === "historical_backtest") {
        query.set("submission_id", submissionId);
        if (outcomeId) query.set("outcome_id", outcomeId);
      }
      const response = await api<unknown>(
        `${base}/${purpose === "current_prebid" ? "scoring-context" : "sample-context"}${query.size ? `?${query}` : ""}`,
      );
      const checked = await validateTechnicalEligibility(
        response.data,
        response.etag,
        saved,
        selection,
      );
      if (checked.purpose === "historical_backtest") {
        if (
          !chosenSubmission ||
          checked.submission.binding_digest !==
            chosenSubmission.package_binding.digest ||
          outcomeInstant(checked.submission.submitted_at) !==
            outcomeInstant(chosenSubmission.submitted_at) ||
          outcomeInstant(checked.submission.recorded_at) !==
            outcomeInstant(chosenSubmission.recorded_at) ||
          (chosenOutcome &&
            (checked.official_result.score_kind !== chosenOutcome.score_kind ||
              outcomeInstant(checked.official_result.label_known_at) !==
                outcomeInstant(chosenOutcome.known_at) ||
              normalizedDecimal(checked.official_result.technical_value) !==
                (chosenOutcome.score_kind === "technical_total"
                  ? normalizedDecimal(chosenOutcome.value)
                  : null) ||
              normalizedDecimal(checked.official_result.reported_maximum) !==
                (chosenOutcome.score_kind === "technical_total" &&
                chosenOutcome.value !== null
                  ? normalizedDecimal(chosenOutcome.maximum)
                  : null)))
        ) {
          throw new Error("所选实交或成绩记录发生变化，请重新读取后检查。");
        }
      }
      if (active.current) setResult(checked);
    });
  }

  return (
    <section
      className="technical-scope__eligibility"
      aria-label="技术评分与历史样本条件"
    >
      <h4>评分与样本条件</h4>
      <p>
        检查这份已保存范围及明确选定的依据。当前尚未开放整包数值估分和正式样本准入。
      </p>
      <label>
        检查用途
        <select
          aria-label="技术范围检查用途"
          disabled={busy}
          value={purpose}
          onChange={(event) =>
            changePurpose(
              event.target.value as TechnicalEligibilitySelection["purpose"],
            )
          }
        >
          <option value="current_prebid">当前评分条件</option>
          <option value="historical_backtest">历史样本条件</option>
        </select>
      </label>
      {purpose === "historical_backtest" && (
        <fieldset>
          <legend>明确关联实际提交与官方成绩</legend>
          <p>
            仅列出这份包修订的实交记录。检查结果保留待补状态，成绩关联通过也不会自动形成训练样本。
          </p>
          <div className="technical-scope__actions">
            <button
              type="button"
              disabled={busy}
              onClick={() => void loadSubmissions()}
            >
              读取实交记录
            </button>
            {nextCursor && (
              <button
                type="button"
                disabled={busy}
                onClick={() => void loadSubmissions(true)}
              >
                更多实交记录
              </button>
            )}
          </div>
          {submissionsRead && !submissions.length && (
            <p>
              {nextCursor
                ? "已读页中没有匹配记录，可继续读取。"
                : "已读目录中没有这份包修订的实交记录。"}
            </p>
          )}
          <label>
            实际提交
            <select
              aria-label="检查所用实交记录"
              disabled={busy}
              value={submissionId}
              onChange={(event) => {
                setSubmissionId(event.target.value);
                setOutcomeId("");
                setOutcomes([]);
                setOutcomesRead(false);
                setScaleId("");
                clearResult();
              }}
            >
              <option value="">请明确选择</option>
              {submissions.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {time(entry.submitted_at)} ·{" "}
                  {entry.current ? "当前记录" : "原历史记录"} ·{" "}
                  {entry.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={busy || !chosenSubmission}
            onClick={() => void loadOutcomes()}
          >
            读取该实交的成绩记录
          </button>
          {outcomesRead && !outcomes.length && (
            <p>这次实交尚无已登记的成绩记录，可先检查其余条件。</p>
          )}
          <label>
            官方成绩记录
            <select
              aria-label="检查所用成绩记录"
              disabled={busy || !chosenSubmission}
              value={outcomeId}
              onChange={(event) => {
                setOutcomeId(event.target.value);
                clearResult();
              }}
            >
              <option value="">不选择，标签保持未知</option>
              {outcomes.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {time(entry.known_at)} ·{" "}
                  {entry.score_kind === "technical_total"
                    ? "技术分"
                    : entry.score_kind === "comprehensive_total"
                      ? "综合分"
                      : "分数类型未知"}{" "}
                  · {entry.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
        </fieldset>
      )}
      {memberId && (
        <PackageHistoricalAdmission
          memberId={memberId}
          saved={saved}
          activePurpose={purpose === "historical_backtest"}
          submission={chosenSubmission ?? null}
          outcome={chosenOutcome ?? null}
        />
      )}
      <fieldset>
        <legend>有据技术满分</legend>
        <p>未选择时满分保持未知；官方成绩中记载的满分不会替代招标依据。</p>
        <button
          type="button"
          disabled={
            busy || !supportsApi("GET", "/technical-scale-capabilities")
          }
          onClick={() => void loadScales()}
        >
          读取可选量尺
        </button>
        {scaleStatus && <p role="status">{scaleStatus}</p>}
        <label>
          用于本次检查的量尺
          <select
            aria-label="检查所用技术量尺"
            disabled={busy}
            value={scaleId}
            onChange={(event) => {
              setScaleId(event.target.value);
              clearResult();
            }}
          >
            <option value="">不选择，满分保持未知</option>
            {visibleScales.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {time(entry.created_at)} · {scaleStates[entry.state]} ·{" "}
                {entry.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
      </fieldset>
      {error != null && <ErrorNotice error={error} />}
      <button
        type="button"
        disabled={
          busy ||
          (purpose === "historical_backtest" && !chosenSubmission) ||
          !supportsApi(
            "GET",
            `${base}/${purpose === "current_prebid" ? "scoring-context" : "sample-context"}`,
          )
        }
        onClick={() => void check()}
      >
        {busy
          ? "正在核对…"
          : purpose === "current_prebid"
            ? "检查当前评分条件"
            : "检查历史样本条件"}
      </button>
      {result && (
        <div
          className="technical-scope__eligibility-result"
          aria-label="技术条件检查结果"
        >
          <h5>
            {result.purpose === "current_prebid"
              ? "当前评分条件检查"
              : "历史样本条件检查"}
          </h5>
          <p>
            观察时间：{time(result.observed_at)}
            （北京时间）；来源变化后请重新检查。
          </p>
          <dl>
            <dt>有据技术满分</dt>
            <dd>
              {result.denominator.maximum_usable
                ? `${result.denominator.technical_maximum} 分 · ${result.denominator.scale_description}`
                : "未知"}
            </dd>
            <dt>官方聚合规则</dt>
            <dd>尚不可执行</dd>
            <dt>有效独立判断</dt>
            <dd>0 / 3；失败与重试不计入</dd>
            <dt>数值估分</dt>
            <dd>尚不可生成</dd>
            {result.purpose === "current_prebid" && (
              <>
                <dt>当前输入与保存范围</dt>
                <dd>
                  {result.current_input.state === "matched"
                    ? "数据库身份一致，正式执行前仍需复核原字节"
                    : result.current_input.state === "changed"
                      ? "已变化"
                      : "暂不可核对"}
                </dd>
              </>
            )}
            {result.purpose === "historical_backtest" && (
              <>
                <dt>实际提交与范围</dt>
                <dd>
                  {result.submission.matches_scope
                    ? "确切包与修订一致"
                    : "不一致"}
                </dd>
                <dt>官方技术分</dt>
                <dd>
                  {result.official_result.technical_value === null
                    ? "未知或非技术分"
                    : `${result.official_result.technical_value} 分（${result.official_result.current_association ? "关联已核验" : "关联尚未通过当前核验"}）`}
                </dd>
                <dt>成绩记录中的满分</dt>
                <dd>
                  {result.official_result.reported_maximum === null
                    ? "未知"
                    : `${result.official_result.reported_maximum} 分（仅作原记录展示）`}
                </dd>
                <dt>样本状态</dt>
                <dd>待补条件，尚未创建正式样本</dd>
                <dt>范围冻结时间</dt>
                <dd>{time(result.timing.scope_frozen_at)}</dd>
                <dt>实交／历史输入截止</dt>
                <dd>{time(result.timing.historical_as_of)}</dd>
                <dt>标签知晓时间</dt>
                <dd>{time(result.timing.label_known_at)}</dd>
                <dt>训练冻结／实交分割／标签可用截止</dt>
                <dd>均尚未由研究记录冻结</dd>
                <dt>范围是否在实交前冻结</dt>
                <dd>
                  {result.original_scope_precedes_submission ? "是" : "否"}
                </dd>
              </>
            )}
          </dl>
          {result.denominator.evidence_refs.length > 0 && (
            <details>
              <summary>查看满分的冻结原文依据</summary>
              {result.denominator.evidence_refs.map((ref) => (
                <blockquote className="technical-scope__quote" key={ref.id}>
                  物理页 {ref.physical_page}：{ref.quote}
                </blockquote>
              ))}
            </details>
          )}
          <h5>尚需补齐的条件（{result.blockers.length}）</h5>
          <ul>
            {result.blockers
              .slice(gapPage * 20, (gapPage + 1) * 20)
              .map((gap) => (
                <li key={gap.id}>{gap.message}</li>
              ))}
          </ul>
          {result.blockers.length > 20 && (
            <TechnicalPager
              page={gapPage}
              total={result.blockers.length}
              onPage={setGapPage}
              label="条件"
            />
          )}
        </div>
      )}
    </section>
  );
}
