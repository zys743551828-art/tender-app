import { useState } from "react";
import type {
  PackageRequirementInventoryView,
  PackageRuleCorrection_RuleAddition as RuleAddition,
} from "./contracts";
import {
  PackageRuleCorrectionEvidence,
  type CorrectionQuoteChoice,
} from "./PackageRuleCorrectionEvidence";
import { RuleSemanticDetails } from "./PackageRuleCorrectionDiff";
import {
  correctionKindNames,
  correctionOperationNames,
  correctionRuleSemantic,
  type CorrectionChange,
} from "./packageRuleCorrectionProtocol";
import {
  correctionDecimal,
  validCorrectionRule,
  type CorrectionBase,
  type CorrectionScope,
} from "./packageRuleCorrectionRecovery";

type Band = RuleAddition["bands"][number];
type Operation = CorrectionChange["op"];
function Clauses({
  name,
  value,
  disabled,
  onChange,
}: {
  name: "条件" | "例外";
  value: string[];
  disabled: boolean;
  onChange: (value: string[]) => void;
}) {
  return (
    <fieldset>
      <legend>{name}（逐条保留原文）</legend>
      {value.length === 0 && <p className="small-note">未列{name}</p>}
      {value.map((text, index) => (
        <div key={index}>
          <label>
            {name} {index + 1}（逐字原文）
            <textarea
              rows={3}
              maxLength={8000}
              disabled={disabled}
              value={text}
              onChange={(event) =>
                onChange(
                  value.map((item, i) =>
                    i === index ? event.target.value : item,
                  ),
                )
              }
            />
          </label>
          <button
            type="button"
            className="text-button"
            disabled={disabled}
            onClick={() => onChange(value.filter((_, i) => i !== index))}
          >
            移除{name} {index + 1}
          </button>
        </div>
      ))}
      <button
        type="button"
        className="text-button"
        disabled={disabled || value.length >= 50}
        onClick={() => onChange([...value, ""])}
      >
        添加{name}
      </button>
    </fieldset>
  );
}
function Editor({
  scope,
  base,
  inventory,
  used,
  disabled,
  initial,
  onSave,
  onCancel,
}: {
  scope: CorrectionScope;
  base: CorrectionBase;
  inventory: PackageRequirementInventoryView;
  used: Set<string>;
  disabled: boolean;
  initial: { change: CorrectionChange; quotes: CorrectionQuoteChoice[] } | null;
  onSave: (change: CorrectionChange, quotes: CorrectionQuoteChoice[]) => void;
  onCancel: () => void;
}) {
  const initialRule =
    initial?.change.op !== "withdraw" ? initial?.change.rule : undefined;
  const [op, setOp] = useState<Operation>(initial?.change.op ?? "add");
  const [ruleId, setRuleId] = useState(
    initial && initial.change.op !== "add" ? initial.change.rule_id : "",
  );
  const [kind, setKind] = useState<RuleAddition["kind"]>(
    initialRule?.kind ?? "mandatory",
  );
  const [statement, setStatement] = useState(initialRule?.statement ?? "");
  const [description, setDescription] = useState(
    initialRule?.scope.description ?? "",
  );
  const [conditions, setConditions] = useState(initialRule?.conditions ?? []);
  const [exceptions, setExceptions] = useState(initialRule?.exceptions ?? []);
  const [maximum, setMaximum] = useState(initialRule?.maximum ?? "");
  const [bands, setBands] = useState<Band[]>(initialRule?.bands ?? []);
  const [quotes, setQuotes] = useState<CorrectionQuoteChoice[]>(
    initial?.quotes ?? [],
  );
  const [error, setError] = useState("");
  const binding = inventory.manifest.requirements.find(
    (item) => item.rule_id === ruleId,
  );
  const old = binding ? correctionRuleSemantic(binding.rule_snapshot) : null;
  const choices = inventory.manifest.requirements.filter(
    (item) =>
      item.rule_snapshot.provenance_status === "effective" &&
      !!correctionRuleSemantic(item.rule_snapshot),
  );
  const quoteIds = [
    ...new Set(quotes.map((item) => item.detail.evidence.evidence_id)),
  ];
  function chooseRule(id: string) {
    setRuleId(id);
    setQuotes([]);
    setError("");
    const selected = inventory.manifest.requirements.find(
      (item) => item.rule_id === id,
    );
    const value = selected
      ? correctionRuleSemantic(selected.rule_snapshot)
      : null;
    if (!value) return;
    setKind(value.kind);
    setStatement(value.statement);
    setDescription(String(value.applicability_scope.description ?? ""));
    setConditions(value.conditions);
    setExceptions(value.exceptions);
    setMaximum(value.max_points ?? "");
    setBands(value.bands.map((band) => ({ ...band, evidence_ids: [] })));
  }
  function save() {
    if (disabled) return;
    setError("");
    if (
      op !== "add" &&
      (!binding ||
        !old ||
        old.provenance_status !== "effective" ||
        used.has(binding.rule_id))
    ) {
      setError("请选择本清单尚未加入本次修订的有效旧条款。");
      return;
    }
    if (
      !quotes.length ||
      quotes.some(
        (item) => !item.detail.evidence.text_content.includes(item.quote),
      )
    ) {
      setError("请从冻结原页目录读取完整证据并采用至少一段逐字引用。");
      return;
    }
    const evidence_quotes = quotes.map((item) => ({
      evidence_id: item.detail.evidence.evidence_id,
      quote: item.quote,
    }));
    if (op === "withdraw") {
      onSave(
        {
          op,
          rule_id: binding!.rule_id,
          rule_digest: binding!.rule_digest,
          evidence_quotes,
        },
        quotes,
      );
      return;
    }
    const rule: RuleAddition = {
      kind,
      statement: statement.trim(),
      scope: { bid_id: scope.bidId, description: description.trim() },
      conditions,
      exceptions,
      maximum: kind === "scoring" ? maximum : null,
      bands: kind === "scoring" ? bands : [],
      evidence_quotes,
    };
    if (
      !validCorrectionRule(rule, scope.bidId) ||
      (kind === "scoring" && !correctionDecimal(maximum))
    ) {
      setError(
        "请补齐条款解释、适用范围和引用；评分分值须为精确十进制文字，每个分档须选择依据。",
      );
      return;
    }
    const joined = quotes.map((item) => item.quote).join("\n");
    if (
      [...rule.conditions, ...rule.exceptions].some(
        (item) => !joined.includes(item),
      )
    ) {
      setError("每项条件和例外都必须逐字包含在采用的引用中。");
      return;
    }
    if (rule.bands.some((band) => !joined.includes(band.description))) {
      setError("每个评分分档的要求都必须逐字包含在采用的引用中。");
      return;
    }
    onSave(
      op === "replace"
        ? {
            op,
            rule_id: binding!.rule_id,
            rule_digest: binding!.rule_digest,
            rule,
          }
        : { op: "add", rule },
      quotes,
    );
  }
  return (
    <section className="rule-correction-editor" aria-label="编辑本次条款修订">
      <h5>{initial ? "调整待预览的修订" : "增加一项修订"}</h5>
      <label>
        修订方式
        <select
          disabled={disabled || !!initial}
          value={op}
          onChange={(event) => {
            setOp(event.target.value as Operation);
            setError("");
          }}
        >
          <option value="add">补充遗漏条款</option>
          <option value="replace">替换有效旧条款</option>
          <option value="withdraw">有据撤销旧条款</option>
        </select>
      </label>
      {op !== "add" && (
        <>
          <label>
            确切旧条款
            <select
              disabled={disabled || !!initial}
              value={ruleId}
              onChange={(event) => chooseRule(event.target.value)}
            >
              <option value="">选择原清单条款</option>
              {choices.map((item, index) => (
                <option
                  key={item.rule_id}
                  value={item.rule_id}
                  disabled={used.has(item.rule_id)}
                >
                  条款 {index + 1} ·{" "}
                  {String(item.rule_snapshot.statement).slice(0, 100)}
                  {used.has(item.rule_id) ? "（本次已修订）" : ""}
                </option>
              ))}
            </select>
          </label>
          {old && <RuleSemanticDetails value={old} label="保留的原条款" />}
          {op === "withdraw" && (
            <p className="notice neutral">
              撤销将生成保留原文的历史条款和明确否决记录。请提供支持撤销的冻结原页依据；原记录不会被删除。
            </p>
          )}
        </>
      )}
      {op !== "withdraw" && (
        <>
          <label>
            条款性质
            <select
              value={kind}
              disabled={disabled}
              onChange={(event) =>
                setKind(event.target.value as RuleAddition["kind"])
              }
            >
              {Object.entries(correctionKindNames).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            条款解释
            <textarea
              rows={4}
              maxLength={16000}
              disabled={disabled}
              value={statement}
              onChange={(event) => setStatement(event.target.value)}
            />
          </label>
          <label>
            适用范围
            <input
              maxLength={2000}
              disabled={disabled}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="说明适用标段、对象或工程范围"
            />
          </label>
          <div className="rule-correction-field-pair">
            <Clauses
              name="条件"
              value={conditions}
              disabled={disabled}
              onChange={setConditions}
            />
            <Clauses
              name="例外"
              value={exceptions}
              disabled={disabled}
              onChange={setExceptions}
            />
          </div>
          {kind === "scoring" && (
            <div className="rule-correction-bands">
              <label>
                条款满分（精确十进制）
                <input
                  type="text"
                  inputMode="decimal"
                  maxLength={100}
                  disabled={disabled}
                  value={maximum}
                  onChange={(event) => setMaximum(event.target.value)}
                  placeholder="例如 12.50"
                />
              </label>
              {bands.map((band, index) => (
                <fieldset key={index}>
                  <legend>评分分档 {index + 1}</legend>
                  <div className="rule-correction-field-pair">
                    <label>
                      分档名称
                      <input
                        disabled={disabled}
                        maxLength={8000}
                        value={band.label}
                        onChange={(event) =>
                          setBands((old) =>
                            old.map((item, i) =>
                              i === index
                                ? { ...item, label: event.target.value }
                                : item,
                            ),
                          )
                        }
                      />
                    </label>
                    <label>
                      分档分值（精确十进制）
                      <input
                        disabled={disabled}
                        inputMode="decimal"
                        maxLength={100}
                        value={band.points}
                        onChange={(event) =>
                          setBands((old) =>
                            old.map((item, i) =>
                              i === index
                                ? { ...item, points: event.target.value }
                                : item,
                            ),
                          )
                        }
                      />
                    </label>
                  </div>
                  <label>
                    分档要求（逐字原文）
                    <textarea
                      rows={2}
                      disabled={disabled}
                      maxLength={8000}
                      value={band.description}
                      onChange={(event) =>
                        setBands((old) =>
                          old.map((item, i) =>
                            i === index
                              ? { ...item, description: event.target.value }
                              : item,
                          ),
                        )
                      }
                    />
                  </label>
                  <p className="small-note">选择该分档对应的已采用原页依据：</p>
                  {!quoteIds.length && <p>请先在下方采用原页引用。</p>}
                  {quoteIds.map((id) => {
                    const source = quotes.find(
                      (item) => item.detail.evidence.evidence_id === id,
                    )!.detail.evidence;
                    return (
                      <label className="rule-correction-check" key={id}>
                        <input
                          type="checkbox"
                          disabled={disabled}
                          checked={band.evidence_ids.includes(id)}
                          onChange={(event) =>
                            setBands((old) =>
                              old.map((item, i) =>
                                i === index
                                  ? {
                                      ...item,
                                      evidence_ids: event.target.checked
                                        ? [...item.evidence_ids, id]
                                        : item.evidence_ids.filter(
                                            (value) => value !== id,
                                          ),
                                    }
                                  : item,
                              ),
                            )
                          }
                        />
                        <span>
                          {source.member_id} · 物理页 {source.physical_page}
                        </span>
                      </label>
                    );
                  })}
                  <button
                    type="button"
                    className="text-button"
                    disabled={disabled}
                    onClick={() =>
                      setBands((old) => old.filter((_, i) => i !== index))
                    }
                  >
                    移除分档 {index + 1}
                  </button>
                </fieldset>
              ))}
              <button
                type="button"
                className="secondary"
                disabled={disabled || bands.length >= 100}
                onClick={() =>
                  setBands((old) => [
                    ...old,
                    {
                      label: "",
                      description: "",
                      points: "",
                      evidence_ids: [],
                    },
                  ])
                }
              >
                添加评分分档
              </button>
            </div>
          )}
        </>
      )}
      <h6>本项采用的原页引用（{quotes.length}/50）</h6>
      {!quotes.length && (
        <p className="small-note">
          尚未采用依据。替换条款也需重新明确选择本次引用。
        </p>
      )}
      {quotes.map((item, index) => (
        <div
          className="rule-correction-source"
          key={`${item.detail.evidence.evidence_id}:${index}`}
        >
          <p>
            {item.detail.evidence.member_id} · 物理页{" "}
            {item.detail.evidence.physical_page}
          </p>
          <blockquote>{item.quote}</blockquote>
          <button
            type="button"
            className="text-button"
            disabled={disabled}
            onClick={() => {
              const remaining = quotes.filter((_, i) => i !== index);
              setQuotes(remaining);
              const retained = new Set(
                remaining.map((choice) => choice.detail.evidence.evidence_id),
              );
              setBands((old) =>
                old.map((band) => ({
                  ...band,
                  evidence_ids: band.evidence_ids.filter((id) =>
                    retained.has(id),
                  ),
                })),
              );
            }}
          >
            移除引用 {index + 1}
          </button>
        </div>
      ))}
      <PackageRuleCorrectionEvidence
        scope={scope}
        base={base}
        disabled={disabled}
        selected={quotes}
        onSelect={(value) => {
          setQuotes((old) => [...old, value]);
          setError("");
        }}
      />
      {error && <p role="alert">{error}</p>}
      <div className="rule-correction-toolbar">
        <button type="button" disabled={disabled} onClick={save}>
          加入本次修订
        </button>
        <button
          type="button"
          className="text-button"
          disabled={disabled}
          onClick={onCancel}
        >
          取消本项编辑
        </button>
      </div>
    </section>
  );
}

export type CorrectionDraftChange = {
  change: CorrectionChange;
  quotes: CorrectionQuoteChoice[];
};
export function PackageRuleCorrectionForm({
  scope,
  base,
  inventory,
  value,
  disabled,
  onChange,
  onEditing,
}: {
  scope: CorrectionScope;
  base: CorrectionBase;
  inventory: PackageRequirementInventoryView;
  value: CorrectionDraftChange[];
  disabled: boolean;
  onChange: (value: CorrectionDraftChange[]) => void;
  onEditing: (value: boolean) => void;
}) {
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const used = new Set(
    value.flatMap((item, index) =>
      item.change.op !== "add" && index !== editing
        ? [item.change.rule_id]
        : [],
    ),
  );
  const close = () => {
    setEditing(null);
    onEditing(false);
  };
  return (
    <div className="rule-correction-composer">
      <h4>本次修订（{value.length}/100）</h4>
      {!value.length && <p>先选择补充、替换或撤销，逐项填写解释与原页依据。</p>}
      <ol className="rule-correction-queued">
        {value.map((item, index) => (
          <li key={index}>
            <strong>{correctionOperationNames[item.change.op]}</strong>
            <p>
              {item.change.op === "withdraw"
                ? String(
                    inventory.manifest.requirements.find(
                      (binding) =>
                        binding.rule_id ===
                        (
                          item.change as Extract<
                            CorrectionChange,
                            { op: "withdraw" }
                          >
                        ).rule_id,
                    )?.rule_snapshot.statement ?? "原条款",
                  )
                : item.change.rule.statement}
            </p>
            <small>{item.quotes.length} 段冻结引用</small>
            <div className="rule-correction-toolbar">
              <button
                type="button"
                className="text-button"
                disabled={disabled || editing !== null}
                onClick={() => {
                  setEditing(index);
                  onEditing(true);
                }}
              >
                调整修订 {index + 1}
              </button>
              <button
                type="button"
                className="text-button"
                disabled={disabled || editing !== null}
                onClick={() => onChange(value.filter((_, i) => i !== index))}
              >
                移除修订 {index + 1}
              </button>
            </div>
          </li>
        ))}
      </ol>
      {editing === null ? (
        <button
          type="button"
          className="secondary"
          disabled={disabled || value.length >= 100}
          onClick={() => {
            setEditing("new");
            onEditing(true);
          }}
        >
          增加一项条款修订
        </button>
      ) : (
        <Editor
          key={String(editing)}
          scope={scope}
          base={base}
          inventory={inventory}
          used={used}
          disabled={disabled}
          initial={editing === "new" ? null : value[editing]}
          onCancel={close}
          onSave={(change, quotes) => {
            onChange(
              editing === "new"
                ? [...value, { change, quotes }]
                : value.map((item, index) =>
                    index === editing ? { change, quotes } : item,
                  ),
            );
            close();
          }}
        />
      )}
    </div>
  );
}
