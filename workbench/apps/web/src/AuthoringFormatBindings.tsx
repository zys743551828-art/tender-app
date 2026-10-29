import { useState } from "react";
import { api } from "./api";
import type {
  AuthoringStyleApplyPreview,
  EvidenceAuthoringReferenceView,
  RuleSetView,
} from "./contracts";
import { useResource } from "./useResource";
import { ResourceState } from "./ResourceState";
import { ErrorNotice } from "./components";
import { EvidenceLinks } from "./EvidenceLinks";
type Binding = AuthoringStyleApplyPreview["format_bindings"][number];
const fields = {
  font: "字体",
  font_size_halfpoints: "字号（半磅）",
  margin_top_twips: "上边距（twip）",
  margin_right_twips: "右边距（twip）",
  margin_bottom_twips: "下边距（twip）",
  margin_left_twips: "左边距（twip）",
  paragraph_after_twips: "段后间距（twip）",
  cover_enabled: "使用封面",
  cover_title: "封面标题",
  header_text: "页眉文字",
  footer_text: "页脚文字",
  page_number: "显示页脚页码",
  chapter_numbering: "章节编号",
  toc_enabled: "使用目录",
} as const;
export function AuthoringFormatBindings({
  bidId,
  bindings,
  disabled,
  onChange,
}: {
  bidId: string;
  bindings: Binding[];
  disabled: boolean;
  onChange: (value: Binding[]) => void;
}) {
  const rules = useResource<RuleSetView>(`/bids/${bidId}/rules`);
  const [ruleId, setRuleId] = useState("");
  const [field, setField] = useState<Binding["field"]>("font");
  const [value, setValue] = useState("");
  const [evidenceIds, setEvidenceIds] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const rule = rules.data?.rules.find(
    (r) =>
      r.id === ruleId &&
      r.confirmation === "confirmed" &&
      r.provenance_status === "effective",
  );
  async function add() {
    if (!rule || !evidenceIds.length || !reason.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const refs = [];
      for (const id of evidenceIds) {
        const r = await api<EvidenceAuthoringReferenceView>(
          `/evidence/${id}/authoring-reference`,
        );
        if (
          r.data.bid_id !== bidId ||
          r.data.evidence_id !== id ||
          !r.data.authoring_reference ||
          r.data.authoring_reference.evidence_id !== id ||
          r.data.authoring_reference.document_version_id !==
            r.data.document_version_id
        )
          throw new Error("格式依据当前不可用于编写，请核对原页与来源状态。");
        refs.push(r.data.authoring_reference);
      }
      const base = {
        rule_id: rule.id,
        source_refs: refs,
        reason: reason.trim(),
      };
      let binding: Binding;
      switch (field) {
        case "font":
          if (value !== "Noto Sans CJK SC" && value !== "Noto Serif CJK SC")
            throw new Error("请选择受支持字体；不能自行声称与未支持字体等价。");
          binding = { ...base, field, value };
          break;
        case "chapter_numbering":
          if (value !== "decimal" && value !== "none")
            throw new Error("请选择编号方式。");
          binding = { ...base, field, value };
          break;
        case "cover_enabled":
        case "page_number":
        case "toc_enabled":
          if (value !== "true" && value !== "false")
            throw new Error("请选择是或否。");
          binding = { ...base, field, value: value === "true" };
          break;
        case "cover_title":
        case "header_text":
        case "footer_text":
          binding = { ...base, field, value };
          break;
        default:
          if (!Number.isSafeInteger(Number(value)) || !value.trim())
            throw new Error("请输入明确整数；单位以字段标注为准。");
          binding = { ...base, field, value: Number(value) };
      }
      onChange([...bindings.filter((b) => b.field !== field), binding]);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details>
      <summary>项目格式要求优先绑定 · {bindings.length}个字段</summary>
      <p className="small-note">
        只把已确认要求的真实原页明确绑定到字段。人工解释不代表系统已核完全部格式或暗标要求；模板不能覆盖这些项目要求。1磅=2半磅，1厘米约567twip。
      </p>
      {bindings.map((b) => (
        <div className="format-binding-row" key={b.field}>
          <strong>
            {fields[b.field]}：{String(b.value)}
          </strong>
          <EvidenceLinks
            ids={b.source_refs.map((r) => r.evidence_id)}
            label="查看格式依据原页"
          />
          <button
            type="button"
            className="text-button"
            disabled={disabled || busy}
            onClick={() =>
              onChange(bindings.filter((v) => v.field !== b.field))
            }
          >
            移除此字段绑定
          </button>
        </div>
      ))}
      <ResourceState
        {...rules}
        hasData={!!rules.data}
        onRetry={() => void rules.reload()}
      />
      <fieldset disabled={disabled || busy}>
        <legend>新增或替换一个格式字段</legend>
        <label>
          已确认的项目要求
          <select
            value={ruleId}
            onChange={(e) => {
              setRuleId(e.target.value);
              setEvidenceIds([]);
            }}
          >
            <option value="">请选择已确认且生效的要求</option>
            {rules.data?.rules
              .filter(
                (r) =>
                  r.confirmation === "confirmed" &&
                  r.provenance_status === "effective",
              )
              .map((r) => (
                <option key={r.id} value={r.id}>
                  {r.statement}
                </option>
              ))}
          </select>
        </label>
        {rule?.evidence_ids.map((id) => (
          <label className="checkbox-label" key={id}>
            <input
              type="checkbox"
              checked={evidenceIds.includes(id)}
              onChange={(e) =>
                setEvidenceIds((old) =>
                  e.target.checked ? [...old, id] : old.filter((v) => v !== id),
                )
              }
            />
            <EvidenceLinks ids={[id]} label="核对此要求原页并选择为依据" />
          </label>
        ))}
        <label>
          格式字段
          <select
            value={field}
            onChange={(e) => {
              setField(e.target.value as Binding["field"]);
              setValue("");
            }}
          >
            {Object.entries(fields).map(([k, t]) => (
              <option key={k} value={k}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label>
          字段值
          {field === "font" ? (
            <select value={value} onChange={(e) => setValue(e.target.value)}>
              <option value="">选择受支持字体</option>
              <option>Noto Sans CJK SC</option>
              <option>Noto Serif CJK SC</option>
            </select>
          ) : field === "chapter_numbering" ? (
            <select value={value} onChange={(e) => setValue(e.target.value)}>
              <option value="">请选择</option>
              <option value="decimal">分级数字编号</option>
              <option value="none">不生成编号</option>
            </select>
          ) : ["cover_enabled", "page_number", "toc_enabled"].includes(
              field,
            ) ? (
            <select value={value} onChange={(e) => setValue(e.target.value)}>
              <option value="">请选择</option>
              <option value="true">是</option>
              <option value="false">否</option>
            </select>
          ) : (
            <input
              value={value}
              maxLength={200}
              onChange={(e) => setValue(e.target.value)}
            />
          )}
        </label>
        <label>
          原文如何支持此字段
          <textarea
            value={reason}
            maxLength={2000}
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
        <p className="small-note">
          {!rule
            ? "先选择已确认要求。"
            : !evidenceIds.length
              ? "还需明确选择原页依据。"
              : !reason.trim()
                ? "还需填写字段解释。"
                : "字段仅加入本次版式预览，尚未保存到草稿。"}
        </p>
        <button
          type="button"
          className="button secondary"
          disabled={!rule || !evidenceIds.length || !reason.trim()}
          onClick={() => void add()}
        >
          加入格式预览
        </button>
      </fieldset>
      <ErrorNotice error={error} />
    </details>
  );
}
