import type { PackageAuthoringFactCatalog } from "./contracts";
import type { CaptureDraft } from "./authoringCaptureForm";
import {
  captureIdentityLabels,
  captureIdentityNames,
  captureSubjectLabels,
  type CaptureFact,
} from "./authoringInputCatalogProtocol";

const reasonLabels: Record<string, string> = {
  AUTHORING_PACKAGE_DRAFT_CHANGED:
    "稿件已有新修订，当前选择保留，需要重新选择可保存的快照。",
  AUTHORING_PACKAGE_SECTION_CHANGED:
    "快照中有章节已更新，不能把旧节点作为当前编写基准。",
  AUTHORING_PACKAGE_RICH_TARGET_UNSUPPORTED:
    "这份完整快照含表格或图片；当前整包编写输入只支持纯文字快照。",
  AUTHORING_PACKAGE_STRUCTURE_BASIS_UNSUPPORTED:
    "这份快照的编写计划、格式绑定或 Word 导入依据尚不支持整包编写输入。",
  AUTHORING_PACKAGE_TEXT_NODE_REQUIRED: "该章节没有可选择的稳定段落或标题。",
  AUTHORING_PACKAGE_FACT_HEAD_CHANGED:
    "当前事实集已变化，原选择保留；新保存需要重新选择并核对。",
  AUTHORING_PACKAGE_IDENTITY_CHANGED: "当前项目身份与所选两包的冻结身份不同。",
  AUTHORING_PACKAGE_FACT_HEAD_MISSING: "尚无可保存的当前事实集。",
  FACT_SET_EMPTY: "所选事实集没有事实。",
  PROJECT_WORK_CLOSED: "项目已结束或归档，当前只能查看；新保存需要先恢复工作。",
  FACT_DECISION_UNCONFIRMED: "事实尚未获得确认，或已被否决。",
  FACT_DECISION_BINDING_UNPROVEN: "原确认与这条事实或其沿用链不能一致核验。",
  FACT_DECISION_BASIS_UNPROVEN: "原确认缺少可核验的原页依据。",
  FACT_EVIDENCE_OUTSIDE_FROZEN_INPUT: "事实依据不在本次明确选择的两包解析内。",
  FACT_EVIDENCE_QUALITY_UNPROVEN: "事实依据的页或解析尚不能完整核验。",
  FACT_SOURCE_BINDING_UNPROVEN: "原确认所用来源与当前来源观察不一致。",
  FACT_SOURCE_NOT_EFFECTIVE: "来源或祖先已失效，或不属于可用于投前编写的资料。",
  FACT_SCOPE_MAPPING_REQUIRED: "需要为本次用途明确选择作用对象并填写理由。",
};
export function AuthoringCaptureBlockers({ reasons }: { reasons: string[] }) {
  return reasons.length ? (
    <ul className="capture-blockers" aria-label="仍需核对的依据">
      {reasons.map((reason) => (
        <li key={reason}>
          {reasonLabels[reason] ?? `该项尚待核对：${reason}`}
        </li>
      ))}
    </ul>
  ) : null;
}
function factValue(item: CaptureFact) {
  try {
    const value: unknown = JSON.parse(item.value_jsonb_text);
    return typeof value === "string" ? value : item.value_jsonb_text;
  } catch {
    return item.value_jsonb_text;
  }
}
export function AuthoringCaptureFacts({
  page,
  items,
  draft,
  disabled,
  onChange,
}: {
  page: PackageAuthoringFactCatalog;
  items: CaptureFact[];
  draft: CaptureDraft;
  disabled: boolean;
  onChange: (draft: CaptureDraft) => void;
}) {
  const byId = new Map(items.map((f) => [f.fact_id, f]));
  return (
    <div className="capture-facts">
      <AuthoringCaptureBlockers reasons={page.blocking_reasons} />
      <fieldset disabled={disabled}>
        <legend>逐项选择五个已确认的业务编号</legend>
        <p className="small-note">
          下列编号均需您选择。相同名称可能有不同事实，系统不会按第一项、文字相似或当前排序推定。
        </p>
        <div className="capture-identities">
          {captureIdentityNames.map((name) => {
            const options = items.filter(
              (item) =>
                item.identity_name === name &&
                item.identity_value_usable &&
                item.provenance_status === "verified",
            );
            const chosen = draft.identities[name];
            return (
              <label key={name}>
                {captureIdentityLabels[name]}
                <select
                  value={chosen}
                  onChange={(e) =>
                    onChange({
                      ...draft,
                      identities: {
                        ...draft.identities,
                        [name]: e.target.value,
                      },
                    })
                  }
                >
                  <option value="">
                    明确选择{captureIdentityLabels[name]}
                  </option>
                  {chosen && !options.some((f) => f.fact_id === chosen) && (
                    <option value={chosen}>
                      已选 {chosen.slice(0, 8)}（本次尚未核验通过）
                    </option>
                  )}
                  {options.map((f) => (
                    <option key={f.fact_id} value={f.fact_id}>
                      {factValue(f).slice(0, 80)} · {f.fact_id.slice(0, 8)}
                    </option>
                  ))}
                </select>
              </label>
            );
          })}
        </div>
      </fieldset>
      <fieldset disabled={disabled}>
        <legend>选择编写需要使用的事实，并说明用途</legend>
        <p className="small-note">
          事实来源通过核对后，仍需为每个用途明确作用对象和理由。不勾选的事实不会被自动加入用途声明。
        </p>
        {items.map((item) => {
          const chosen = draft.uses.find((u) => u.fact_id === item.fact_id),
            usable = item.provenance_status === "verified";
          return (
            <article key={item.fact_id} className="capture-fact">
              <label className="capture-check">
                <input
                  type="checkbox"
                  checked={!!chosen}
                  disabled={!usable && !chosen}
                  onChange={(e) =>
                    onChange({
                      ...draft,
                      uses: e.target.checked
                        ? [
                            ...draft.uses,
                            {
                              fact_id: item.fact_id,
                              subject_kind: "",
                              reason: "",
                            },
                          ]
                        : draft.uses.filter((u) => u.fact_id !== item.fact_id),
                    })
                  }
                />
                将“
                {item.identity_name
                  ? captureIdentityLabels[item.identity_name]
                  : item.name || "未命名事实"}
                ”用于本次编写 · {item.fact_id.slice(0, 8)}
              </label>
              <p className="preserve-text capture-fact-value">
                {factValue(item)}
              </p>
              <p className="small-note">
                {usable
                  ? "原页、确认与来源已在本次读取中核对。保存时将再次核验。"
                  : "这项事实依据尚未通过本次核对，不能用于新保存。"}
              </p>
              {!usable && (
                <AuthoringCaptureBlockers
                  reasons={item.blocking_reasons.filter(
                    (r) => r !== "FACT_SCOPE_MAPPING_REQUIRED",
                  )}
                />
              )}
              <details>
                <summary>查看这条事实的确认与原页位置</summary>
                <dl>
                  <dt>原事实主体／范围</dt>
                  <dd>
                    {item.subject_text} ／ {item.scope_text}
                  </dd>
                  <dt>人工确认</dt>
                  <dd>
                    {item.decision
                      ? `${item.decision.decision === "confirmed" ? "已确认" : "已否决"} · ${new Date(item.decision.created_at).toLocaleString("zh-CN")} · 沿用 ${item.decision.carryover_steps} 步`
                      : "没有确认记录"}
                  </dd>
                  <dt>完整原值（数据库 JSON）</dt>
                  <dd className="preserve-text">{item.value_jsonb_text}</dd>
                </dl>
                <ul>
                  {item.evidence.map((e) => (
                    <li key={e.id}>
                      物理第 {e.physical_page} 页 · 文件 {e.document_version_id}{" "}
                      · 解析 {e.parse_id} · 证据 {e.id}
                    </li>
                  ))}
                </ul>
                <p className="digest">事实观察摘要：{item.fact_item_digest}</p>
              </details>
            </article>
          );
        })}
        {draft.uses.map((use) => {
          const item = byId.get(use.fact_id);
          return (
            <section
              key={use.fact_id}
              className="capture-use"
              aria-label={`用途声明 ${use.fact_id.slice(0, 8)}`}
            >
              <h4>
                {item?.identity_name
                  ? captureIdentityLabels[item.identity_name]
                  : item?.name || "保留的已选事实"}{" "}
                · {use.fact_id.slice(0, 8)}
              </h4>
              {!item && (
                <p className="notice warning">
                  原用途和理由保留；这条事实尚未在本次目录中核对，不能新保存。
                </p>
              )}
              <label>
                作用对象
                <select
                  value={use.subject_kind}
                  onChange={(e) =>
                    onChange({
                      ...draft,
                      uses: draft.uses.map((u) =>
                        u.fact_id === use.fact_id
                          ? {
                              ...u,
                              subject_kind: e.target
                                .value as typeof use.subject_kind,
                            }
                          : u,
                      ),
                    })
                  }
                >
                  <option value="">明确选择作用对象</option>
                  {page.subject_choices.map((s) => (
                    <option key={s.kind} value={s.kind}>
                      {captureSubjectLabels[s.kind]} · {s.id.slice(0, 8)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                本次用途与理由
                <textarea
                  rows={3}
                  maxLength={2000}
                  value={use.reason}
                  onChange={(e) =>
                    onChange({
                      ...draft,
                      uses: draft.uses.map((u) =>
                        u.fact_id === use.fact_id
                          ? { ...u, reason: e.target.value }
                          : u,
                      ),
                    })
                  }
                  placeholder="说明这项事实将用于哪段编写、为什么适用于所选对象"
                />
              </label>
              <button
                type="button"
                className="text-button"
                onClick={() =>
                  onChange({
                    ...draft,
                    uses: draft.uses.filter((u) => u.fact_id !== use.fact_id),
                  })
                }
              >
                移除这项用途声明
              </button>
            </section>
          );
        })}
      </fieldset>
    </div>
  );
}
