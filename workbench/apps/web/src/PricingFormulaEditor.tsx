import { useState } from "react";
import { api } from "./api";
import type { ApiResult } from "./api";
import type {
  PricingContext,
  PricingEvidenceQuote,
  PricingFormulaSourcePage,
  PricingFormulaView,
  PricingPackageContext,
  PricingRegisterFormula,
} from "./contracts";
import { ErrorNotice } from "./components";
import { EvidenceLinks } from "./EvidenceLinks";
import { knowledgeStorageKey, useKnowledgeInput } from "./knowledgeStorage";
import { ResourceState } from "./ResourceState";
import { useCursorList } from "./useCursorList";
import { useRecordedCommand } from "./useRecordedCommand";
import {
  pricingContextPath,
  pricingScopeKey,
  samePricingBinding,
} from "./packagePricing";
import type { PackagePricingBinding } from "./packagePricing";

const fields = [
  ["method", "基准价方法"],
  ["maximum", "价格满分"],
  ["minimum_price", "最低价格边界"],
  ["maximum_price", "最高价格边界"],
  ["minimum_valid_bids", "最少有效报价数"],
  ["above_coefficient", "高于基准价系数"],
  ["below_coefficient", "低于基准价系数"],
  ["amount_unit", "完整金额单位声明"],
  ["currency", "币种声明"],
  ["rounding_policy", "最终取整规则"],
  ["baseline_set", "基准价有效集合"],
  ["exclusions", "不作去极值等排除"],
  ["intermediate_rounding", "不作中间取整"],
  ["clamping", "分数限制于零至满分"],
] as const;
type Inputs = {
  title: string;
  method: string;
  maximum: string;
  minimum: string;
  maximumPrice: string;
  noMinimum: boolean;
  noMaximum: boolean;
  minimumCount: string;
  above: string;
  below: string;
  unit: string;
  currency: string;
  rounding: string;
  reason: string;
  terms: boolean;
  matches: boolean;
  quotes: PricingEvidenceQuote[];
};
const empty: Inputs = {
  title: "",
  method: "",
  maximum: "",
  minimum: "",
  maximumPrice: "",
  noMinimum: false,
  noMaximum: false,
  minimumCount: "",
  above: "",
  below: "",
  unit: "",
  currency: "",
  rounding: "",
  reason: "",
  terms: false,
  matches: false,
  quotes: [],
};
const decimal = "^(0|[1-9][0-9]{0,23})(\\.[0-9]{1,12})?$";

export function PricingFormulaEditor({
  bidId,
  memberId,
  initialContext,
  onSaved,
  onClose,
  packageBinding,
}: {
  bidId: string;
  memberId: string;
  initialContext: ApiResult<PricingContext | PricingPackageContext>;
  onSaved: (formula: PricingFormulaView) => void;
  onClose: () => void;
  packageBinding?: PackagePricingBinding;
}) {
  const [input, setInput] = useKnowledgeInput<Inputs>(
    knowledgeStorageKey(memberId, bidId) +
      "pricing-formula" +
      pricingScopeKey(packageBinding),
    empty,
  );
  const [basis, setBasis] = useState(initialContext);
  const [error, setError] = useState<unknown>(null);
  const [reading, setReading] = useState(false);
  const sources = useCursorList<PricingFormulaSourcePage>(
    packageBinding
      ? `/bids/${bidId}/package-pricing-formula-sources?limit=50&${new URLSearchParams(packageBinding)}`
      : `/bids/${bidId}/pricing-formula-sources?limit=50`,
    (item) => item.evidence_id,
  );
  const command = useRecordedCommand(
    `pricing-formula:${memberId}:${bidId}${pricingScopeKey(packageBinding)}`,
    ({ data }) => verifyFormula(data),
  );
  const requiredFields = fields.filter(
    ([field]) =>
      input.method !== "lowest_valid_ratio" ||
      !["above_coefficient", "below_coefficient"].includes(field),
  );
  const locked = command.busy || !!command.pending;
  const set = (key: keyof Inputs, value: string | boolean) =>
    setInput((old) => ({ ...old, [key]: value }));
  function verifyFormula(data: unknown) {
    const value = data as Partial<PricingFormulaView> | null;
    if (
      !value?.formula ||
      value.formula.bid_id !== bidId ||
      value.formula.formula_version_id !== value.formula_version_id ||
      !samePricingBinding(value.formula.package_binding, packageBinding)
    )
      throw new Error("公式返回身份无法核对，请重读目录，未使用其他项目公式。");
  }
  async function received(value: PricingFormulaView) {
    setInput(empty);
    onSaved(value);
  }
  async function save() {
    setError(null);
    try {
      if (!basis.etag || basis.data.bid_id !== bidId)
        throw new Error("请读取本项目报价依据后再登记。");
      if (
        !["lowest_valid_ratio", "mean_valid_deviation"].includes(
          input.method,
        ) ||
        !["元", "万元"].includes(input.unit) ||
        !["CNY", "unknown"].includes(input.currency) ||
        !["half_up_2dp", "half_even_2dp"].includes(input.rounding)
      )
        throw new Error(
          "请按完整原文选择支持的方法、量尺及取整规则，不能近似代替未知条款。",
        );
      if (
        !input.terms ||
        !input.matches ||
        !input.reason.trim() ||
        !input.quotes.length
      )
        throw new Error("请逐项核对完整条款、精确出处及参数对应解释。");
      const supported = new Set(
        input.quotes.flatMap((quote) => quote.supported_fields),
      );
      const missing = requiredFields.filter(([field]) => !supported.has(field));
      if (missing.length)
        throw new Error(
          `请为以下字段选择支持它的完整原文出处：${missing.map(([, label]) => label).join("、")}。`,
        );
      if (
        input.quotes.some(
          (quote) => !quote.quote.trim() || !quote.supported_fields.length,
        )
      )
        throw new Error("所选出处必须有逐字引文及其实际支持字段。");
      const body: PricingRegisterFormula = {
        title: input.title.trim(),
        formula: {
          method: input.method as "lowest_valid_ratio" | "mean_valid_deviation",
          maximum: input.maximum,
          minimum_price: input.noMinimum ? null : input.minimum,
          maximum_price: input.noMaximum ? null : input.maximumPrice,
          minimum_valid_bids: Number(input.minimumCount),
          above_coefficient:
            input.method === "lowest_valid_ratio" ? "0" : input.above,
          below_coefficient:
            input.method === "lowest_valid_ratio" ? "0" : input.below,
        },
        amount_unit: input.unit as "元" | "万元",
        currency: input.currency === "CNY" ? "CNY" : null,
        rounding_policy: input.rounding as "half_up_2dp" | "half_even_2dp",
        interpretation: {
          baseline_set: "own_and_all_numerically_eligible_assumptions",
          exclusions: "none",
          random_parameters: "none",
          intermediate_rounding: "none",
          clamping: "zero_to_maximum",
        },
        terms_complete_confirmed: true,
        matches_source_confirmed: true,
        evidence_quotes: input.quotes,
        reason: input.reason.trim(),
      };
      const result = await command.run<PricingFormulaView>(
        `/bids/${bidId}/${packageBinding ? "package-pricing-formulas" : "pricing-formulas"}`,
        packageBinding ? { ...body, package_binding: packageBinding } : body,
        basis.etag,
      );
      if (result) await received(result.data);
    } catch (failure) {
      setError(failure);
    }
  }
  async function reread() {
    if (reading || locked) return;
    setReading(true);
    setError(null);
    try {
      const next = await api<PricingContext | PricingPackageContext>(
        pricingContextPath(bidId, packageBinding),
      );
      if (next.data.bid_id !== bidId) throw new Error("报价项目身份不一致。");
      if (
        packageBinding &&
        !(
          "package_binding" in next.data &&
          samePricingBinding(next.data.package_binding, packageBinding)
        )
      )
        throw new Error("重读报价依据与明确选择的包修订不一致。");
      setBasis(next);
      await sources.reload();
      command.clearError();
    } catch (failure) {
      setError(failure);
    } finally {
      setReading(false);
    }
  }
  return (
    <section className="panel pricing-formula-editor">
      <h2>确认并登记有据公式</h2>
      <p>
        仅支持最低有效报价比值、有效报价算术均值偏差两种精确方法。随机系数、去极值、分段、中间取整及原文歧义不能近似计算。
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <fieldset disabled={locked} className="pricing-fields">
          <label>
            公式标题
            <input
              value={input.title}
              maxLength={200}
              required
              onChange={(event) => set("title", event.target.value)}
            />
          </label>
          <label>
            原文基准价方法
            <select
              value={input.method}
              required
              onChange={(event) => set("method", event.target.value)}
            >
              <option value="">选择原文明确的方法</option>
              <option value="lowest_valid_ratio">最低有效报价比值</option>
              <option value="mean_valid_deviation">有效报价算术均值偏差</option>
            </select>
          </label>
          <label>
            价格满分
            <input
              inputMode="decimal"
              pattern={decimal}
              value={input.maximum}
              required
              onChange={(event) => set("maximum", event.target.value)}
            />
          </label>
          <label>
            最少有效报价数（包含本方）
            <input
              type="number"
              min={1}
              max={201}
              step={1}
              value={input.minimumCount}
              required
              onChange={(event) => set("minimumCount", event.target.value)}
            />
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={input.noMinimum}
              onChange={(event) => set("noMinimum", event.target.checked)}
            />
            已核对原文无最低价格边界
          </label>
          {!input.noMinimum && (
            <label>
              最低价格边界
              <input
                value={input.minimum}
                pattern={decimal}
                inputMode="decimal"
                required
                onChange={(event) => set("minimum", event.target.value)}
              />
            </label>
          )}
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={input.noMaximum}
              onChange={(event) => set("noMaximum", event.target.checked)}
            />
            已核对原文无最高价格边界
          </label>
          {!input.noMaximum && (
            <label>
              最高价格边界
              <input
                value={input.maximumPrice}
                pattern={decimal}
                inputMode="decimal"
                required
                onChange={(event) => set("maximumPrice", event.target.value)}
              />
            </label>
          )}
          {input.method === "mean_valid_deviation" ? (
            <>
              <label>
                高于基准价系数
                <input
                  value={input.above}
                  pattern={decimal}
                  inputMode="decimal"
                  required
                  onChange={(event) => set("above", event.target.value)}
                />
              </label>
              <label>
                低于基准价系数
                <input
                  value={input.below}
                  pattern={decimal}
                  inputMode="decimal"
                  required
                  onChange={(event) => set("below", event.target.value)}
                />
              </label>
            </>
          ) : (
            input.method && (
              <p className="small-note">
                比值法上下双向系数固定为0；服务端仍核对完整原文。
              </p>
            )
          )}
          <label>
            完整原文金额单位
            <select
              value={input.unit}
              required
              onChange={(event) => set("unit", event.target.value)}
            >
              <option value="">选择明确单位</option>
              <option value="元">元</option>
              <option value="万元">万元</option>
            </select>
          </label>
          <label>
            原文币种
            <select
              value={input.currency}
              required
              onChange={(event) => set("currency", event.target.value)}
            >
              <option value="">核对原文币种</option>
              <option value="CNY">人民币 CNY</option>
              <option value="unknown">原文未明确，记为未知</option>
            </select>
          </label>
          <label>
            原文最终取整规则
            <select
              value={input.rounding}
              required
              onChange={(event) => set("rounding", event.target.value)}
            >
              <option value="">选择有据规则</option>
              <option value="half_up_2dp">最终四舍五入保留两位</option>
              <option value="half_even_2dp">最终半偶数舍入保留两位</option>
            </select>
          </label>
        </fieldset>
        <h3>选择本项目权威原页与支持字段</h3>
        <p className="small-note">
          金额与币种引文须包含自身完整声明，并与计分方法对应同一原件、解析和物理页。单字“元”、不相关页或未读懂的边界不能当作依据。
        </p>
        <ResourceState
          {...sources}
          hasData={!!sources.data}
          onRetry={() => void sources.reload()}
        />
        <ErrorNotice error={sources.moreError} />
        {sources.items.map((source) => {
          const selected = input.quotes.find(
            (quote) => quote.evidence_id === source.evidence_id,
          );
          return (
            <article className="pricing-source" key={source.evidence_id}>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={!!selected}
                  disabled={
                    locked ||
                    !source.source_registered ||
                    source.source_revision === null
                  }
                  onChange={(event) =>
                    setInput((old) => ({
                      ...old,
                      quotes: event.target.checked
                        ? [
                            ...old.quotes,
                            {
                              source_id: source.source_id,
                              source_revision: source.source_revision!,
                              document_version_id: source.document_version_id,
                              parse_id: source.parse_id,
                              physical_page: source.physical_page,
                              evidence_id: source.evidence_id,
                              quote: source.quote,
                              supported_fields: [],
                            },
                          ]
                        : old.quotes.filter(
                            (quote) => quote.evidence_id !== source.evidence_id,
                          ),
                    }))
                  }
                />
                使用此原文出处 · {source.filename} · 物理页{" "}
                {source.physical_page}
              </label>
              {!source.source_registered && (
                <p className="small-note">
                  当前来源尚不可用于新公式，请就地重读，不绕过来源效力。
                </p>
              )}
              <blockquote>{source.quote}</blockquote>
              <EvidenceLinks ids={[source.evidence_id]} label="核对公式原页" />
              {selected && (
                <fieldset disabled={locked}>
                  <legend>此出处实际支持的字段</legend>
                  <label>
                    逐字引文（保留完整计分及量尺声明）
                    <textarea
                      rows={4}
                      maxLength={20000}
                      value={selected.quote}
                      onChange={(event) =>
                        setInput((old) => ({
                          ...old,
                          quotes: old.quotes.map((quote) =>
                            quote.evidence_id === source.evidence_id
                              ? { ...quote, quote: event.target.value }
                              : quote,
                          ),
                        }))
                      }
                    />
                  </label>
                  <div className="pricing-evidence-fields">
                    {requiredFields.map(([field, label]) => (
                      <label className="checkbox-label" key={field}>
                        <input
                          type="checkbox"
                          checked={selected.supported_fields.includes(field)}
                          onChange={(event) =>
                            setInput((old) => ({
                              ...old,
                              quotes: old.quotes.map((quote) =>
                                quote.evidence_id === source.evidence_id
                                  ? {
                                      ...quote,
                                      supported_fields: event.target.checked
                                        ? [...quote.supported_fields, field]
                                        : quote.supported_fields.filter(
                                            (item) => item !== field,
                                          ),
                                    }
                                  : quote,
                              ),
                            }))
                          }
                        />
                        {label}
                      </label>
                    ))}
                  </div>
                </fieldset>
              )}
            </article>
          );
        })}
        {sources.hasMore && (
          <button
            type="button"
            className="text-button"
            disabled={sources.moreBusy}
            onClick={() => void sources.more()}
          >
            加载更多公式原页
          </button>
        )}
        {input.quotes.some(
          (quote) =>
            !sources.items.some(
              (source) => source.evidence_id === quote.evidence_id,
            ),
        ) && (
          <p className="small-note">
            保留了上次所选出处，可能在后续页或来源已经变化。请加载并核对；服务端会再次检查精确来源。
          </p>
        )}
        {input.quotes
          .filter(
            (quote) =>
              !sources.items.some(
                (source) => source.evidence_id === quote.evidence_id,
              ),
          )
          .map((quote) => (
            <article className="pricing-source" key={quote.evidence_id}>
              <p>
                保留的原页选择 · 物理页 {quote.physical_page} ·{" "}
                {quote.document_version_id.slice(0, 8)}
              </p>
              <blockquote>{quote.quote}</blockquote>
              <EvidenceLinks
                ids={[quote.evidence_id]}
                label="回看保留的出处原页"
              />
              <button
                type="button"
                className="text-button"
                disabled={locked}
                onClick={() =>
                  setInput((old) => ({
                    ...old,
                    quotes: old.quotes.filter(
                      (item) => item.evidence_id !== quote.evidence_id,
                    ),
                  }))
                }
              >
                移除此未在当前列表找到的出处选择
              </button>
            </article>
          ))}
        <fieldset disabled={locked} className="pricing-fields">
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={input.terms}
              onChange={(event) => set("terms", event.target.checked)}
              required
            />
            已核对完整条款：本方及所有数值区间内对手假设共同形成基准集合，不去极值、不含随机参数、不作中间取整，最终限制于零至满分
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={input.matches}
              onChange={(event) => set("matches", event.target.checked)}
              required
            />
            原文与受限参数完全一致，金额单位有完整声明，币种明确或据实记未知，未使用近似解释
          </label>
          <label>
            参数对应原文的解释
            <textarea
              rows={3}
              maxLength={4000}
              required
              value={input.reason}
              onChange={(event) => set("reason", event.target.value)}
            />
          </label>
        </fieldset>
        <ErrorNotice error={error ?? command.error} />
        {(!!command.error || !!error) && !command.pending && (
          <button
            type="button"
            className="button secondary"
            disabled={reading || locked}
            onClick={() => void reread()}
          >
            重新核对生效资料，保留全部输入
          </button>
        )}
        {command.pending && !command.busy && (
          <div className="notice warning">
            <div>
              <p>原公式登记结果尚未取得，将复用原请求身份和精确依据。</p>
              <button
                type="button"
                className="button secondary"
                disabled={command.busy}
                onClick={() =>
                  void command.retry<PricingFormulaView>().then((result) => {
                    if (result) void received(result.data).catch(setError);
                  })
                }
              >
                恢复原公式登记结果
              </button>
            </div>
          </div>
        )}
        <div className="review-shortcuts">
          <button
            className="button primary"
            disabled={locked || reading || command.conflict}
          >
            {command.busy ? "正在登记…" : "确认并登记公式"}
          </button>
          <button
            type="button"
            className="text-button"
            disabled={locked}
            onClick={onClose}
          >
            收起，保留公式输入
          </button>
        </div>
      </form>
    </section>
  );
}
