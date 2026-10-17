import { useEffect, useRef, useState } from "react";
import { api, ApiError, supportsApi } from "./api";
import type { ApiResult } from "./api";
import type { SettingsView } from "./contracts";
import type {
  PricingContext,
  PricingFormulaPage,
  PricingFormulaView,
  PricingPlanPage,
  PricingPlanView,
  PricingRequest,
  PricingSimulationView,
} from "./contracts";
import { Badge, ErrorNotice } from "./components";
import { EvidenceLinks } from "./EvidenceLinks";
import { knowledgeStorageKey, useKnowledgeInput } from "./knowledgeStorage";
import { PricingFormulaEditor } from "./PricingFormulaEditor";
import { PricingResults } from "./PricingResults";
import { pricingInputDigest, pricingRequestSignature } from "./pricingInput";
import { ResourceState } from "./ResourceState";
import { useCursorList } from "./useCursorList";
import { useRecordedCommand } from "./useRecordedCommand";
import { useResource } from "./useResource";

export function PricingPanel({
  bidId,
  memberId,
  onSettings,
}: {
  bidId: string;
  memberId: string;
  onSettings: () => void;
}) {
  const available = supportsApi("GET", `/bids/${bidId}/pricing-context`);
  const settings = useResource<SettingsView>(
    available ? `/bids/${bidId}/settings` : null,
    5000,
  );
  if (!available)
    return (
      <div className="module-unavailable">
        <strong>报价工作面尚未开放</strong>
        <p>
          相关服务版本尚未提供，不形成报价结果。资料、风险和已保存方案继续留存。
        </p>
      </div>
    );
  if (
    settings.data?.bid_id === bidId &&
    settings.data.settings?.pricing === false
  )
    return (
      <section className="panel">
        <h2>本项目报价辅助已关闭</h2>
        <p>公式、历史方案与未提交输入保留。开启后不会自动重跑或保存。</p>
        <button className="button secondary" onClick={onSettings}>
          在项目设置中开启报价辅助
        </button>
      </section>
    );
  if (!settings.data || settings.error)
    return (
      <ResourceState
        {...settings}
        hasData={false}
        onRetry={() => void settings.reload()}
      />
    );
  if (settings.data.bid_id !== bidId)
    return (
      <div className="notice error">设置项目身份不一致，未读取报价结果。</div>
    );
  if (typeof settings.data.settings?.pricing !== "boolean")
    return (
      <div className="notice error" role="alert">
        <div>
          <strong>报价设置尚未完整核对</strong>
          <p>未读取公式或情景结果，请重新核对当前项目设置。</p>
          <button
            className="button secondary"
            onClick={() => void settings.reload()}
          >
            重读报价设置
          </button>
        </div>
      </div>
    );
  return (
    <PricingWorkbench
      key={`${memberId}:${bidId}`}
      bidId={bidId}
      memberId={memberId}
    />
  );
}

function PricingWorkbench({
  bidId,
  memberId,
}: {
  bidId: string;
  memberId: string;
}) {
  const formulas = useCursorList<PricingFormulaPage>(
    `/bids/${bidId}/pricing-formulas?limit=25`,
    (item) => item.formula_version_id,
  );
  const plans = useCursorList<PricingPlanPage>(
    `/bids/${bidId}/pricing-plans?limit=25`,
    (item) => item.id,
  );
  const [selected, setSelected] = useKnowledgeInput(
    knowledgeStorageKey(memberId, bidId) + "pricing-selected",
    "",
  );
  const formula = useResource<PricingFormulaView>(
    selected ? `/bids/${bidId}/pricing-formulas/${selected}` : null,
  );
  const [editor, setEditor] = useState<ApiResult<PricingContext> | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [reading, setReading] = useState(false);
  const [planId, setPlanId] = useState<string | null>(null);
  const validFormula =
    formula.data?.formula.bid_id === bidId &&
    formula.data.formula_version_id === selected &&
    formula.data.formula.formula_version_id === selected;
  async function beginFormula() {
    if (reading) return;
    setReading(true);
    setError(null);
    try {
      const snapshot = await api<PricingContext>(
        `/bids/${bidId}/pricing-context`,
      );
      if (snapshot.data.bid_id !== bidId || !snapshot.etag)
        throw new Error("报价依据项目或条件版本无法核对。");
      setEditor(snapshot);
    } catch (failure) {
      setError(failure);
    } finally {
      setReading(false);
    }
  }
  return (
    <>
      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>报价情景</h2>
            <p className="small-note">
              有据公式、对手假设与价格分单独记录，不改变核心提交检查，不预测中标概率。
            </p>
          </div>
          <button
            className="button secondary"
            disabled={reading}
            onClick={() => void beginFormula()}
          >
            登记新的有据公式
          </button>
        </div>
        <ResourceState
          {...formulas}
          hasData={!!formulas.data}
          onRetry={() => void formulas.reload()}
        />
        <ErrorNotice error={formulas.moreError ?? error} />
        <label>
          选择已确认公式
          <select
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
          >
            <option value="">选择公式版本</option>
            {selected &&
              !formulas.items.some(
                (item) => item.formula_version_id === selected,
              ) && (
                <option value={selected}>正在恢复先前选择的固定公式版本</option>
              )}
            {formulas.items.map((item) => (
              <option
                key={item.formula_version_id}
                value={item.formula_version_id}
              >
                {item.title} · {item.formula_version_id.slice(0, 8)} ·{" "}
                {item.current_applicability.applicable
                  ? "当前可适用"
                  : "历史依据或已失效"}
              </option>
            ))}
          </select>
        </label>
        {formulas.hasMore && (
          <button
            className="text-button"
            disabled={formulas.moreBusy}
            onClick={() => void formulas.more()}
          >
            加载更多公式版本
          </button>
        )}
        {formulas.data && !formulas.items.length && (
          <p className="small-empty">
            尚无已登记公式。从本项目生效招标或补遗原页核对条款，一次明确登记后即可试算。
          </p>
        )}
        <ResourceState
          {...formula}
          hasData={!!formula.data}
          onRetry={() => void formula.reload()}
        />
        {formula.data && !validFormula && (
          <div className="notice error">
            公式身份与当前项目或选定版本不一致，未试算。
          </div>
        )}
        {validFormula && (
          <>
            <h3>{formula.data!.formula.title}</h3>
            <p className="small-note">
              固定公式 {selected.slice(0, 8)} · 确认于{" "}
              {new Date(formula.data!.formula.confirmed_at).toLocaleString(
                "zh-CN",
              )}{" "}
              · 输入单位 {formula.data!.formula.amount_unit} ·{" "}
              {formula.data!.formula.currency === "CNY" ? "人民币" : "币种未知"}
              ，不自动换算。
            </p>
            <EvidenceLinks
              ids={formula.data!.formula.evidence_quotes.map(
                (quote) => quote.evidence_id,
              )}
              label="查看已确认公式全部原页"
            />
            {!formula.data!.current_applicability.applicable && (
              <div className="notice warning">
                <div>
                  <strong>公式依据已更新，请核对后重新试算</strong>
                  <p>
                    {formula.data!.current_applicability.reasons.join("；")}
                  </p>
                  <button
                    className="text-button"
                    onClick={() => void formula.reload()}
                  >
                    重新核对该固定公式的适用性
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </section>
      {editor && (
        <PricingFormulaEditor
          key={editor.etag}
          bidId={bidId}
          memberId={memberId}
          initialContext={editor}
          onClose={() => setEditor(null)}
          onSaved={(value) => {
            setSelected(value.formula_version_id);
            setEditor(null);
            void formulas.reload();
          }}
        />
      )}
      {validFormula && (
        <PricingScenario
          key={selected}
          bidId={bidId}
          memberId={memberId}
          formula={formula.data!}
          formulaEtag={formula.etag}
          formulaLoading={formula.loading}
          formulaError={formula.error}
          onRecheck={() => void formula.reload()}
          onSaved={() => void plans.reload()}
        />
      )}
      <section className="panel">
        <h2>已保存情景方案</h2>
        <p className="small-note">
          试算不自动保存方案。历史采用当时公式、输入与结果，不按最新条款重算。
        </p>
        <ResourceState
          {...plans}
          hasData={!!plans.data}
          onRetry={() => void plans.reload()}
        />
        <ErrorNotice error={plans.moreError} />
        {plans.items.map((plan) =>
          plan.formula_snapshot.bid_id !== bidId ? (
            <div className="notice error" key={plan.id}>
              方案项目身份不一致，未展示其他项目结果。
            </div>
          ) : (
            <article key={plan.id} className="pricing-plan-summary">
              <div>
                <strong>{plan.formula_snapshot.title}</strong>
                <p className="small-note">
                  {new Date(plan.created_at).toLocaleString("zh-CN")} · 方案{" "}
                  {plan.id.slice(0, 8)} · 本方情景 {plan.result.candidate_price}{" "}
                  {plan.formula_snapshot.amount_unit} · 价格分{" "}
                  {plan.result.price_score ?? "未知"}
                </p>
                <p className="small-note">
                  {plan.current_applicability.applicable
                    ? "当前依据可适用"
                    : "历史方案，当前依据有变化"}
                </p>
              </div>
              <button
                className="button secondary"
                onClick={() => setPlanId(plan.id)}
              >
                回看此固定情景方案
              </button>
            </article>
          ),
        )}
        {plans.data && !plans.items.length && (
          <p className="small-empty">
            尚无已保存方案。情景结果可单独试算后按需保存。
          </p>
        )}
        {plans.hasMore && (
          <button
            className="text-button"
            disabled={plans.moreBusy}
            onClick={() => void plans.more()}
          >
            加载更多历史方案
          </button>
        )}
        {planId && (
          <HistoricalPlan
            key={planId}
            bidId={bidId}
            id={planId}
            onClose={() => setPlanId(null)}
          />
        )}
      </section>
    </>
  );
}

type ScenarioInput = {
  candidate: string;
  competitors: string;
  additional: string;
  curve: boolean;
  lower: string;
  upper: string;
  points: string;
  reason: string;
};
const initial: ScenarioInput = {
  candidate: "",
  competitors: "",
  additional: "",
  curve: false,
  lower: "",
  upper: "",
  points: "21",
  reason: "",
};
const decimal = /^(0|[1-9][0-9]{0,23})(\.[0-9]{1,12})?$/;

function PricingScenario({
  bidId,
  memberId,
  formula,
  formulaEtag,
  formulaLoading,
  formulaError,
  onRecheck,
  onSaved,
}: {
  bidId: string;
  memberId: string;
  formula: PricingFormulaView;
  formulaEtag: string | null;
  formulaLoading: boolean;
  formulaError: unknown;
  onRecheck: () => void;
  onSaved: () => void;
}) {
  const id = formula.formula_version_id;
  const [input, setInput] = useKnowledgeInput<ScenarioInput>(
    knowledgeStorageKey(memberId, bidId) + `pricing-scenario:${id}`,
    initial,
  );
  const [armed, setArmed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{
    value: ApiResult<PricingSimulationView>;
    signature: string;
  } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const simulate = useRecordedCommand(
    `pricing-simulate:${memberId}:${bidId}:${id}`,
  );
  const save = useRecordedCommand(`pricing-save:${memberId}:${bidId}:${id}`);
  const [saved, setSaved] = useState<PricingPlanView | null>(null);
  const [needsResimulation, setNeedsResimulation] = useState(false);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  let body: PricingRequest | null = null;
  let inputError = "";
  try {
    const competitors = lines(input.competitors, 200, "对手假设");
    const additional = lines(input.additional, 50, "补充候选");
    if (!decimal.test(input.candidate))
      throw new Error("请填写有界十进制本方报价，不能使用科学计数法或负数。");
    if (
      input.curve &&
      (!decimal.test(input.lower) ||
        !decimal.test(input.upper) ||
        !/^\d+$/.test(input.points) ||
        Number(input.points) < 2 ||
        Number(input.points) > 101)
    )
      throw new Error("曲线需要明确上下界与2—101个点。");
    body = {
      formula_version_id: id,
      candidate_price: input.candidate,
      competitor_price_assumptions: competitors,
      candidate_prices: additional,
      curve_range: input.curve
        ? {
            lower: input.lower,
            upper: input.upper,
            points: Number(input.points),
          }
        : null,
      amount_unit: formula.formula.amount_unit,
      currency: formula.formula.currency,
      rounding_policy: formula.formula.rounding_policy,
    };
  } catch (failure) {
    inputError = failure instanceof Error ? failure.message : String(failure);
  }
  const serialized = body ? pricingRequestSignature(body) : null;
  const live = useRef(serialized);
  live.current = serialized;
  const lastAttempt = useRef("");
  const applicable =
    formula.current_applicability.applicable &&
    !formulaError &&
    !formulaLoading;
  const sourceChanged = [simulate.error, save.error].some(
    (failure) =>
      failure instanceof ApiError &&
      (failure.code === "PRICING_SOURCE_CHANGED" || failure.status === 412),
  );
  const stale =
    !!result &&
    (result.signature !== serialized ||
      !applicable ||
      sourceChanged ||
      needsResimulation);
  const currentCommand = useRef(simulate);
  currentCommand.current = simulate;
  useEffect(() => {
    if (
      !armed ||
      !serialized ||
      !formulaEtag ||
      !applicable ||
      sourceChanged ||
      simulate.busy ||
      simulate.pending
    )
      return;
    const fingerprint = JSON.stringify({ serialized, formulaEtag, attempt });
    if (lastAttempt.current === fingerprint) return;
    const timer = window.setTimeout(() => {
      lastAttempt.current = fingerprint;
      setError(null);
      setSaved(null);
      const request = JSON.parse(serialized) as PricingRequest;
      void (async () => {
        try {
          const digest = await pricingInputDigest(
            request,
            formula.formula_digest,
          );
          if (!active.current || live.current !== serialized) return;
          const response =
            await currentCommand.current.run<PricingSimulationView>(
              `/bids/${bidId}/pricing-simulations`,
              request,
              formulaEtag,
            );
          if (!response || !active.current || live.current !== serialized)
            return;
          if (
            response.data.input_digest !== digest ||
            response.data.formula_digest !== formula.formula_digest ||
            response.data.formula_snapshot.bid_id !== bidId
          )
            throw new Error(
              "情景响应与当前输入或固定公式身份不一致，未替换曲线。",
            );
          setResult({ value: response, signature: serialized });
          setNeedsResimulation(false);
        } catch (failure) {
          if (active.current && live.current === serialized) setError(failure);
        }
      })();
    }, 400);
    return () => window.clearTimeout(timer);
  }, [
    armed,
    serialized,
    formulaEtag,
    applicable,
    sourceChanged,
    simulate.busy,
    simulate.pending,
    attempt,
    bidId,
    formula.formula_digest,
  ]);
  async function recover() {
    setError(null);
    try {
      const response = await simulate.retry<PricingSimulationView>();
      if (!response || !active.current) return;
      const digest = await pricingInputDigest(
        response.data.input,
        response.data.formula_digest,
      );
      if (
        response.data.input_digest !== digest ||
        response.data.formula_snapshot.bid_id !== bidId ||
        response.data.formula_version_id !== id
      )
        throw new Error("原试算身份无法核对，未使用其他情景结果。");
      setResult({
        value: response,
        signature: pricingRequestSignature(response.data.input),
      });
    } catch (failure) {
      setError(failure);
    }
  }
  async function savePlan(retry = false) {
    setError(null);
    try {
      if (
        !retry &&
        (!result || stale || !result.value.etag || !input.reason.trim())
      )
        throw new Error(
          "请先取得当前情景结果，并填写保存理由。未知分数可保存，但缺口会保留。",
        );
      const response = retry
        ? await save.retry<PricingPlanView>()
        : await save.run<PricingPlanView>(
            `/bids/${bidId}/pricing-plans`,
            {
              simulation_id: result!.value.data.id,
              reason: input.reason.trim(),
            },
            result!.value.etag!,
          );
      if (response) {
        if (response.data.formula_snapshot.bid_id !== bidId)
          throw new Error("方案返回项目身份不一致。");
        setSaved(response.data);
        onSaved();
      }
    } catch (failure) {
      setError(failure);
    }
  }
  const change = (key: keyof ScenarioInput, value: string | boolean) =>
    setInput((old) => ({ ...old, [key]: value }));
  return (
    <section className="panel pricing-scenario">
      <h2>输入报价情景并试算</h2>
      <p className="small-note">
        单位固定为该有据公式的 {formula.formula.amount_unit} ·{" "}
        {formula.formula.currency === "CNY" ? "人民币" : "币种未知"}
        ；取整规则沿原公式，不自动换算。对手均为用户假设，不替代真实竞争信息。
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setArmed(true);
          setAttempt((old) => old + 1);
        }}
      >
        <fieldset
          className="pricing-fields"
          disabled={save.busy || !!save.pending}
        >
          <label>
            本方候选报价
            <input
              value={input.candidate}
              inputMode="decimal"
              onChange={(event) => change("candidate", event.target.value)}
              required
            />
          </label>
          <label>
            对手报价假设（每行一个，最多200项）
            <textarea
              rows={4}
              value={input.competitors}
              onChange={(event) => change("competitors", event.target.value)}
            />
          </label>
          <label>
            补充本方候选（每行一个，最多50项）
            <textarea
              rows={3}
              value={input.additional}
              onChange={(event) => change("additional", event.target.value)}
            />
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={input.curve}
              onChange={(event) => change("curve", event.target.checked)}
            />
            比较受限区间曲线
          </label>
          {input.curve && (
            <div className="pricing-curve-inputs">
              <label>
                曲线价格下界
                <input
                  value={input.lower}
                  inputMode="decimal"
                  onChange={(event) => change("lower", event.target.value)}
                  required
                />
              </label>
              <label>
                曲线价格上界
                <input
                  value={input.upper}
                  inputMode="decimal"
                  onChange={(event) => change("upper", event.target.value)}
                  required
                />
              </label>
              <label>
                曲线点数
                <input
                  type="number"
                  min={2}
                  max={101}
                  step={1}
                  value={input.points}
                  onChange={(event) => change("points", event.target.value)}
                  required
                />
              </label>
            </div>
          )}
        </fieldset>
        {armed && inputError && (
          <p className="notice warning" role="status">
            {inputError}
          </p>
        )}
        <button
          className="button primary"
          disabled={
            !body ||
            !applicable ||
            sourceChanged ||
            simulate.busy ||
            !!simulate.pending ||
            save.busy ||
            !!save.pending
          }
        >
          {simulate.busy ? "正在计算情景…" : "试算当前情景"}
        </button>
        {armed && (
          <p className="small-note">
            报价变化后稍候自动更新情景，始终保留您的输入。试算不会自动保存方案。
          </p>
        )}
      </form>
      <ErrorNotice error={error ?? simulate.error ?? save.error} />
      {sourceChanged && (
        <div className="notice warning">
          <div>
            <strong>公式依据或条件版本已经变化</strong>
            <p>
              输入保留。请核对原页与固定公式适用性，再明确重新试算；不会静默换用最新公式。
            </p>
            <button
              className="button secondary"
              onClick={() => {
                setArmed(false);
                setNeedsResimulation(true);
                simulate.clearError();
                save.clearError();
                onRecheck();
              }}
            >
              重新核对公式依据，保留情景
            </button>
          </div>
        </div>
      )}
      {simulate.pending && !simulate.busy && (
        <button
          className="button secondary"
          disabled={simulate.busy}
          onClick={() => void recover()}
        >
          恢复原试算结果
        </button>
      )}
      {result && (
        <PricingResults
          result={result.value.data}
          input={result.value.data.input}
          formula={result.value.data.formula_snapshot}
          stale={stale}
        />
      )}
      {result && (
        <form
          className="pricing-save"
          onSubmit={(event) => {
            event.preventDefault();
            void savePlan();
          }}
        >
          <label>
            保存此情景的理由
            <textarea
              rows={2}
              maxLength={4000}
              value={input.reason}
              onChange={(event) => change("reason", event.target.value)}
              disabled={save.busy || !!save.pending}
              required
            />
          </label>
          <button
            className="button secondary"
            disabled={
              stale ||
              sourceChanged ||
              simulate.busy ||
              !!simulate.pending ||
              save.busy ||
              !!save.pending ||
              !result.value.data.current_applicability.applicable
            }
          >
            保存当前情景方案
          </button>
        </form>
      )}
      {save.pending && !save.busy && (
        <button
          className="button secondary"
          disabled={save.busy}
          onClick={() => void savePlan(true)}
        >
          恢复原方案保存结果
        </button>
      )}
      {saved && (
        <p className="notice neutral" role="status">
          已保存固定情景方案 {saved.id.slice(0, 8)}。价格分{" "}
          {saved.result.price_score ?? "未知"}；不赋予实际报价或提交资格。
        </p>
      )}
    </section>
  );
}

function HistoricalPlan({
  bidId,
  id,
  onClose,
}: {
  bidId: string;
  id: string;
  onClose: () => void;
}) {
  const resource = useResource<PricingPlanView>(
    `/bids/${bidId}/pricing-plans/${id}`,
  );
  const plan = resource.data;
  return (
    <article className="historical-pricing-plan">
      <div className="section-heading">
        <h3>历史固定情景方案</h3>
        <button className="text-button" onClick={onClose}>
          收起此方案
        </button>
      </div>
      <ResourceState
        {...resource}
        hasData={!!plan}
        onRetry={() => void resource.reload()}
      />
      {plan && (plan.id !== id || plan.formula_snapshot.bid_id !== bidId) ? (
        <div className="notice error">历史方案身份不一致，未展示其他结果。</div>
      ) : (
        plan && (
          <>
            <p>
              保存于 {new Date(plan.created_at).toLocaleString("zh-CN")} ·{" "}
              {plan.reason}
            </p>
            <Badge>
              {plan.current_applicability.applicable
                ? "当前依据可适用"
                : "当前依据已变化，保留历史原值"}
            </Badge>
            {!plan.current_applicability.applicable && (
              <p className="small-note">
                {plan.current_applicability.reasons.join("；")}
              </p>
            )}
            <PricingResults
              result={plan.result}
              input={plan.input}
              formula={plan.formula_snapshot}
            />
          </>
        )
      )}
    </article>
  );
}
function lines(raw: string, maximum: number, label: string) {
  const values = raw
    .split(/\r?\n/)
    .map((value) => value.trim())
    .filter(Boolean);
  if (values.length > maximum || values.some((value) => !decimal.test(value)))
    throw new Error(
      `${label}请每行填写一个有界十进制金额，最多${maximum}项；对手同价假设会分别计数。`,
    );
  return values;
}
