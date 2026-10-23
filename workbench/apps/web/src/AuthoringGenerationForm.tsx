import { useState } from "react";
import type {
  AuthoringGenerationBatchCapabilities,
  AuthoringGenerationBatchCreateRequest,
  DraftView,
  MaterialView,
} from "./contracts";
import { ResourceState } from "./ResourceState";
import { useResource } from "./useResource";
import {
  generationAmountText,
  parseGenerationAmount,
  sumGenerationLimits,
} from "./authoringGenerationBudget";
import {
  generationInteger,
  generationText,
} from "./authoringGenerationRecovery";
import { executionId, executionSha } from "./executionInputValidation";

export type GenerationFormValue = Omit<
  AuthoringGenerationBatchCreateRequest,
  "base_draft_revision" | "sections"
> & {
  sections: Omit<
    AuthoringGenerationBatchCreateRequest["sections"][number],
    "base_section_revision"
  >[];
};
type SectionInput = {
  instruction: string;
  sourceIds: string[];
  maxTokens: number;
  limit: string;
};

export function AuthoringGenerationForm({
  bidId,
  draft,
  capabilities,
  disabled,
  initial,
  onCreate,
}: {
  bidId: string;
  draft: DraftView;
  capabilities: AuthoringGenerationBatchCapabilities;
  disabled: boolean;
  initial?: AuthoringGenerationBatchCreateRequest;
  onCreate: (value: GenerationFormValue) => Promise<void>;
}) {
  const [selected, setSelected] = useState(
    initial?.sections.map((section) => section.section_id) ?? [],
  );
  const [fields, setFields] = useState<Record<string, SectionInput>>(() =>
    Object.fromEntries(
      (initial?.sections ?? []).map((section) => [
        section.section_id,
        {
          instruction: section.instruction,
          sourceIds: section.source_version_ids,
          maxTokens: section.max_tokens,
          limit: generationAmountText(section.budget_limit_minor),
        },
      ]),
    ),
  );
  const [totalText, setTotalText] = useState(
    initial ? generationAmountText(initial.total_limit_minor) : "",
  );
  const [reason, setReason] = useState(initial?.reason ?? "");
  const materials = useResource<MaterialView>(`/bids/${bidId}/materials`);
  const materialsValid =
    materials.data?.bid_id === bidId &&
    Array.isArray(materials.data.documents) &&
    materials.data.documents.every(
      (document) =>
        document.bid_id === bidId &&
        executionId(document.id) &&
        executionSha(document.sha256) &&
        typeof document.filename === "string" &&
        generationInteger(document.file_revision, 1),
    );
  const sources = materialsValid
    ? materials.data!.documents.filter(
        (document) =>
          document.role !== "official_result" &&
          document.artifact_kind !== "review_report" &&
          document.artifact_kind !== "annotated_review_copy",
      )
    : [];
  const price = capabilities.price;
  const total = parseGenerationAmount(totalText);
  const limits = selected.map((id) =>
    parseGenerationAmount(fields[id]?.limit ?? ""),
  );
  const allocated = limits.every((value): value is number => value !== null)
    ? sumGenerationLimits(limits)
    : null;
  const unknownSections = selected.filter(
    (id) => !draft.sections.some((section) => section.id === id),
  );
  const valid =
    !!price &&
    Date.parse(price.valid_until) > Date.now() &&
    selected.length > 0 &&
    selected.length <= capabilities.max_sections &&
    !unknownSections.length &&
    total !== null &&
    total > 0 &&
    total <= capabilities.max_limit_minor &&
    allocated !== null &&
    allocated <= total &&
    generationText(reason.trim()) &&
    selected.every((id) => {
      const value = fields[id],
        limit = parseGenerationAmount(value?.limit ?? "");
      const estimate = capabilities.estimates.find(
        (estimate) => estimate.max_tokens === value?.maxTokens,
      );
      return (
        !!value &&
        generationText(
          value.instruction.trim(),
          capabilities.max_instruction_chars,
        ) &&
        generationInteger(
          value.maxTokens,
          1,
          Math.min(8192, price.output_upper),
        ) &&
        limit !== null &&
        limit > 0 &&
        (!estimate || limit >= estimate.reservation_minor) &&
        value.sourceIds.length <= 30
      );
    });
  function change(id: string, update: Partial<SectionInput>) {
    setFields((old) => ({
      ...old,
      [id]: {
        ...(old[id] ?? {
          instruction: "",
          sourceIds: [],
          maxTokens: capabilities.default_max_tokens,
          limit: "",
        }),
        ...update,
      },
    }));
  }
  function toggle(id: string, checked: boolean) {
    if (disabled) return;
    if (checked) {
      if (selected.length >= capabilities.max_sections) return;
      change(id, {});
      setSelected((old) => [...old, id]);
    } else setSelected((old) => old.filter((value) => value !== id));
  }
  async function submit() {
    if (disabled || !valid || !price || total === null) return;
    await onCreate({
      price_version_id: price.price_version_id,
      currency: price.currency,
      amount_scale: capabilities.amount_scale,
      total_limit_minor: total,
      reason: reason.trim(),
      sections: selected.map((section_id) => ({
        section_id,
        instruction: fields[section_id].instruction.trim(),
        source_version_ids: [...fields[section_id].sourceIds].sort(),
        selected_node_ids: null,
        max_tokens: fields[section_id].maxTokens,
        budget_limit_minor: parseGenerationAmount(fields[section_id].limit)!,
      })),
    });
  }
  return (
    <form
      className="generation-form"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <p className="notice neutral">
        每章可以生成多处段落修改和新增段落。表格、图片、原节点属性与未选章节保持原样；候选须逐章核对后明确应用。
      </p>
      {price && (
        <details className="generation-price">
          <summary>
            本批模型价格 · {price.model} · {price.currency}
          </summary>
          <dl>
            <dt>价格版本</dt>
            <dd>
              {price.version} · {price.price_version_id}
            </dd>
            <dt>每百万输入 token</dt>
            <dd>
              {generationAmountText(price.input_per_million_minor)}{" "}
              {price.currency}
            </dd>
            <dt>每百万输出 token</dt>
            <dd>
              {generationAmountText(price.output_per_million_minor)}{" "}
              {price.currency}
            </dd>
            <dt>有效至</dt>
            <dd>{new Date(price.valid_until).toLocaleString("zh-CN")}</dd>
            <dt>价格来源</dt>
            <dd>
              {price.source_kind} · {price.source_uri}
            </dd>
          </dl>
        </details>
      )}
      <label>
        本批总预算（{price?.currency ?? "等待价格"}）
        <input
          aria-label="本批总预算"
          inputMode="decimal"
          value={totalText}
          disabled={disabled}
          onChange={(event) => setTotalText(event.target.value)}
          placeholder="明确填写金额，例如 0.50"
        />
      </label>
      <p className="small-note">
        金额支持最多9位小数。每章额度包含该章后续全部明确重试；未分配额度不会自动转给其他章节。预留是本地估算，不是模型供应方保证的最终费用封顶。
      </p>
      <fieldset className="generation-sections">
        <legend>
          选择本批章节 · 已选 {selected.length} / {capabilities.max_sections}
        </legend>
        {draft.sections.map((section) => (
          <label className="generation-check" key={section.id}>
            <input
              type="checkbox"
              aria-label={`本批选择章节：${section.title}`}
              checked={selected.includes(section.id)}
              disabled={
                disabled ||
                (!selected.includes(section.id) &&
                  selected.length >= capabilities.max_sections)
              }
              onChange={(event) => toggle(section.id, event.target.checked)}
            />
            <span>
              {section.title} <small>已保存章节修订 {section.revision}</small>
            </span>
          </label>
        ))}
        {!draft.sections.length && (
          <p>先新增章节并保存正文，再选择本批编写范围。</p>
        )}
      </fieldset>
      {!!unknownSections.length && (
        <p className="notice warning">
          已选章节在当前草稿中已移除。原输入仍保留，请取消失效章节后重新选择。
        </p>
      )}
      <ResourceState
        {...materials}
        hasData={!!materialsValid}
        onRetry={() => void materials.reload()}
      />
      {materials.data && !materialsValid && (
        <p className="notice error" role="alert">
          来源目录的项目或版本身份不一致，未提供其他项目来源。
        </p>
      )}
      {selected.map((id) => {
        const section = draft.sections.find((section) => section.id === id),
          value = fields[id];
        if (!value) return null;
        const limit = parseGenerationAmount(value.limit),
          estimate = capabilities.estimates.find(
            (estimate) => estimate.max_tokens === value.maxTokens,
          );
        const tokenOptions = [
          ...new Set([
            capabilities.default_max_tokens,
            ...capabilities.estimates.map((estimate) => estimate.max_tokens),
            value.maxTokens,
          ]),
        ].sort((a, b) => a - b);
        return (
          <fieldset key={id} className="generation-section-form">
            <legend>{section?.title ?? "已移除的章节"}</legend>
            {!section && (
              <button
                type="button"
                className="text-button"
                disabled={disabled}
                onClick={() => toggle(id, false)}
              >
                取消此失效章节
              </button>
            )}
            <label>
              本章编写目标
              <textarea
                aria-label={`${section?.title ?? id}的编写目标`}
                rows={3}
                maxLength={capabilities.max_instruction_chars}
                value={value.instruction}
                disabled={disabled}
                onChange={(event) =>
                  change(id, { instruction: event.target.value })
                }
              />
            </label>
            <div className="generation-budget-inputs">
              <label>
                本章额度（{price?.currency ?? "等待价格"}）
                <input
                  aria-label={`${section?.title ?? id}的额度`}
                  inputMode="decimal"
                  value={value.limit}
                  disabled={disabled}
                  onChange={(event) =>
                    change(id, { limit: event.target.value })
                  }
                />
              </label>
              <label>
                每次输出 token 上限
                <select
                  aria-label={`${section?.title ?? id}的输出上限`}
                  value={value.maxTokens}
                  disabled={disabled}
                  onChange={(event) =>
                    change(id, { maxTokens: Number(event.target.value) })
                  }
                >
                  {tokenOptions.map((tokens) => (
                    <option key={tokens} value={tokens}>
                      {tokens.toLocaleString()}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {estimate && (
              <p
                className={
                  limit !== null && limit < estimate.reservation_minor
                    ? "notice warning"
                    : "small-note"
                }
              >
                按本次价格，单次预计预留{" "}
                {generationAmountText(estimate.reservation_minor)}{" "}
                {price?.currency}。
                {limit !== null && limit < estimate.reservation_minor
                  ? "本章额度不足以预留一次调用。"
                  : "失败后的新尝试仍占用本章剩余额度。"}
              </p>
            )}
            <p className="small-note">
              范围：全章可编辑的段落和标题。模型只能使用冻结的当前正文与下面明确选择的资料版本；空来源不会自动搜索其他文件。
            </p>
            <details>
              <summary>
                本章确切资料版本 · 已选 {value.sourceIds.length} / 30
              </summary>
              <div className="generation-source-choices">
                {sources.map((source) => {
                  const checked = value.sourceIds.includes(source.id),
                    available = ["complete", "partial"].includes(
                      source.parse_coverage,
                    );
                  return (
                    <label className="generation-check" key={source.id}>
                      <input
                        type="checkbox"
                        aria-label={`${section?.title ?? id}的来源：${source.filename}版本${source.file_revision}`}
                        checked={checked}
                        disabled={
                          disabled ||
                          (!checked &&
                            (!available || value.sourceIds.length >= 30))
                        }
                        onChange={(event) =>
                          change(id, {
                            sourceIds: event.target.checked
                              ? [...value.sourceIds, source.id]
                              : value.sourceIds.filter(
                                  (selected) => selected !== source.id,
                                ),
                          })
                        }
                      />
                      <span>
                        {source.filename} · 版本 {source.file_revision}
                        <small>
                          {available
                            ? source.parse_coverage === "partial"
                              ? "部分解析；服务端将核对实际可用证据"
                              : "已有解析；服务端将再次核对来源"
                            : "尚无可用解析"}{" "}
                          · {source.id}
                        </small>
                      </span>
                    </label>
                  );
                })}
                {value.sourceIds
                  .filter(
                    (selected) =>
                      !sources.some((source) => source.id === selected),
                  )
                  .map((missing) => (
                    <p key={missing} className="notice warning">
                      原选择版本 {missing}{" "}
                      当前未列出；仍保留确切选择，不能按文件名自动换版。
                      <button
                        type="button"
                        className="text-button"
                        disabled={disabled}
                        onClick={() =>
                          change(id, {
                            sourceIds: value.sourceIds.filter(
                              (source) => source !== missing,
                            ),
                          })
                        }
                      >
                        移除此旧来源选择
                      </button>
                    </p>
                  ))}
                {!sources.length && (
                  <p className="small-note">
                    没有可列出的编写来源，可先补齐资料或明确仅依据当前章节提出修改。
                  </p>
                )}
              </div>
            </details>
          </fieldset>
        );
      })}
      <p
        className={
          allocated !== null && total !== null && allocated > total
            ? "notice error"
            : "small-note"
        }
      >
        已分配：
        {allocated === null
          ? "请补齐每章额度"
          : generationAmountText(allocated)}{" "}
        / 总上限 {total === null ? "待填写" : generationAmountText(total)}{" "}
        {price?.currency}。
        {allocated !== null && total !== null && allocated > total
          ? "分章额度之和超过本批上限，不能提交。"
          : ""}
      </p>
      <label>
        本次批量编写理由
        <input
          aria-label="本次批量编写理由"
          value={reason}
          maxLength={1000}
          disabled={disabled}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <button
        type="submit"
        className="button primary"
        disabled={disabled || !capabilities.enabled || !valid}
      >
        保存当前编辑并按预算生成 {selected.length} 章候选
      </button>
      <p className="small-note">
        此操作会按上述份额预留模型调用预算并创建任务；候选生成成功也不会自动改写草稿。
      </p>
    </form>
  );
}
