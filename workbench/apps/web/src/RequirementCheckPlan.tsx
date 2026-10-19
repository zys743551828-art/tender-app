import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type {
  BidPackageStoredView,
  CreatePackageRequirementInventory,
  EvidenceView,
  RuleSetView,
} from "./contracts";
import "./RequirementCheckPlan.css";

export type CheckPlanValue = {
  mappings: CreatePackageRequirementInventory["mappings"];
  valid: boolean;
  dirty: boolean;
};
type Props = {
  bidId: string;
  packageView: BidPackageStoredView;
  authorityView: BidPackageStoredView;
  rules: RuleSetView;
  disabled: boolean;
  onChange: (value: CheckPlanValue) => void;
  initialMappings?: CreatePackageRequirementInventory["mappings"];
};
type Draft = {
  enabled: boolean;
  parts: string[];
  quantityUnknown: boolean;
  quantity: string;
  applicability: "unknown" | "applicable" | "not_applicable";
  at: string;
  checks: string[];
  reason: string;
  basis: string[];
  applicabilityBasis: string[];
};
type Evidence = { value?: EvidenceView; issue?: string; loading?: boolean };
const fresh = (): Draft => ({
  enabled: false,
  parts: [],
  quantityUnknown: true,
  quantity: "",
  applicability: "unknown",
  at: "",
  checks: [],
  reason: "",
  basis: [],
  applicabilityBasis: [],
});
const checkNames = {
  quantity: "数量逐项核对",
  expiry: "有效期",
  signature: "签字盖章",
  format: "格式要求",
  scope: "适用范围",
};
const categoryNames: Record<string, string> = {
  qualification: "资格",
  business: "商务",
  technical: "技术",
  price: "报价",
  commercial: "商务",
  attachment: "附件",
  annex: "附件",
};
const validText = (value: string) =>
  value.trim().length > 0 &&
  Array.from(value).length <= 200 &&
  !value.includes("\0") &&
  !/[\uD800-\uDFFF]/u.test(value);
function validAt(value: string) {
  if (!value) return true;
  const found =
    /^(\d{4})-(\d{2})-(\d{2})T([01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.exec(
      value,
    );
  if (!found) return false;
  const year = Number(found[1]),
    month = Number(found[2]),
    day = Number(found[3]);
  const days = [
    31,
    year % 400 === 0 || (year % 4 === 0 && year % 100 !== 0) ? 29 : 28,
    31,
    30,
    31,
    30,
    31,
    31,
    30,
    31,
    30,
    31,
  ];
  return (
    year > 0 &&
    month >= 1 &&
    month <= 12 &&
    day >= 1 &&
    day <= days[month - 1] &&
    Number.isFinite(Date.parse(value))
  );
}
function toggle(list: string[], id: string) {
  return list.includes(id) ? list.filter((v) => v !== id) : [...list, id];
}
function frozenEvidence(
  value: EvidenceView,
  id: string,
  authority: BidPackageStoredView,
): string | null {
  if (value.id !== id) return "证据身份不一致";
  if (value.source_status !== "published")
    return value.source_status === "withdrawn"
      ? "引用已撤回，不可选用"
      : "引用尚未发布，不可选用";
  if (!Number.isSafeInteger(value.physical_page) || value.physical_page < 1)
    return "物理页无效";
  const member = authority.manifest.members.find(
    (m) =>
      m.document_version_id === value.document_version_id &&
      m.parse.status === "frozen" &&
      m.parse.parse_run_id === value.parse_run_id,
  );
  if (!member) return "证据不属于所选依据包的精确冻结文件与解析";
  if (
    !member.parts.some(
      (p) =>
        p.first_page <= value.physical_page &&
        value.physical_page <= p.last_page,
    )
  )
    return "证据物理页不在冻结逻辑范围内";
  return null;
}

export function RequirementCheckPlan({
  bidId,
  packageView,
  authorityView,
  rules,
  disabled,
  onChange,
  initialMappings,
}: Props) {
  const context = JSON.stringify({
    bidId,
    package: packageView.manifest,
    digest: packageView.digest,
    authority: authorityView.manifest,
    authorityDigest: authorityView.digest,
    rules,
    initialMappings,
  });
  const initial = useRef(context);
  const changed = initial.current !== context;
  const [drafts, setDrafts] = useState<Record<string, Draft>>(() =>
    Object.fromEntries(
      (initialMappings ?? []).map((m) => [
        m.rule_id,
        {
          enabled: true,
          parts: [...m.target_part_ids],
          quantityUnknown: m.minimum_count === null,
          quantity: m.minimum_count === null ? "" : String(m.minimum_count),
          applicability: m.applicability,
          at: m.valid_at ?? "",
          checks: [...m.checks],
          reason: m.reason,
          basis: [...m.basis_evidence_ids],
          applicabilityBasis: [...m.applicability_evidence_ids],
        },
      ]),
    ),
  );
  const [dirty, setDirty] = useState(!!initialMappings?.length);
  const [evidence, setEvidence] = useState<Record<string, Evidence>>({});
  const [retry, setRetry] = useState(0);
  const own = packageView.manifest;
  const contextValid =
    own.kind === "bid" &&
    own.scope.bid_id === bidId &&
    authorityView.manifest.kind === "authority" &&
    rules.bid_id === bidId &&
    Object.keys(own.scope).every(
      (key) =>
        own.scope[key as keyof typeof own.scope] ===
        authorityView.manifest.scope[key as keyof typeof own.scope],
    ) &&
    rules.rules.every(
      (r) => r.rule_set_id === rules.id && r.scope.bid_id === bidId,
    ) &&
    !!rules.id &&
    new Set(rules.rules.map((r) => r.id)).size === rules.rules.length &&
    new Set((initialMappings ?? []).map((m) => m.rule_id)).size ===
      (initialMappings ?? []).length &&
    (initialMappings ?? []).every(
      (m) =>
        rules.rules.some((r) => r.id === m.rule_id) &&
        m.target_part_ids.length > 0 &&
        m.target_part_ids.every((id) =>
          own.members.some((member) =>
            member.parts.some((p) => p.part_id === id),
          ),
        ) &&
        [
          ...new Set(
            own.members
              .flatMap((member) => member.parts)
              .filter((p) => m.target_part_ids.includes(p.part_id))
              .map((p) => p.category),
          ),
        ]
          .sort()
          .join("\0") === [...m.categories].sort().join("\0"),
    );
  const locked = disabled || changed || !contextValid;
  const ids = JSON.stringify(
    [
      ...new Set(
        rules.rules
          .filter((r) => drafts[r.id]?.enabled)
          .flatMap((r) => r.evidence_ids),
      ),
    ].sort(),
  );
  useEffect(() => {
    if (changed || !contextValid) return;
    let active = true;
    const selected = JSON.parse(ids) as string[];
    setEvidence((old) =>
      Object.fromEntries(
        selected.map((id) => [id, { ...old[id], loading: true }]),
      ),
    );
    void Promise.all(
      selected.map(async (id) => {
        try {
          const result = await api<EvidenceView>(`/evidence/${id}`);
          const issue = frozenEvidence(result.data, id, authorityView);
          return [
            id,
            { value: result.data, ...(issue ? { issue } : {}), loading: false },
          ] as const;
        } catch {
          return [
            id,
            { issue: "引用读取失败，请重读后选择", loading: false },
          ] as const;
        }
      }),
    ).then((items) => {
      if (active) setEvidence(Object.fromEntries(items));
    });
    return () => {
      active = false;
    };
  }, [ids, context, changed, contextValid, retry, authorityView]);
  const parts = own.members.flatMap((m, mi) =>
    m.parts.map((part, pi) => ({
      part,
      member: m,
      fileIndex: mi + 1,
      partIndex: pi + 1,
    })),
  );
  const value = useMemo<CheckPlanValue>(() => {
    const mappings: CheckPlanValue["mappings"] = [];
    let valid = contextValid && !changed;
    for (const rule of rules.rules) {
      const draft = drafts[rule.id];
      if (!draft?.enabled) continue;
      const targets = parts.filter((p) => draft.parts.includes(p.part.part_id));
      const count = draft.quantityUnknown
        ? null
        : /^\d+$/.test(draft.quantity)
          ? Number(draft.quantity)
          : NaN;
      const usable = (id: string) =>
        rule.evidence_ids.includes(id) &&
        !!evidence[id]?.value &&
        !evidence[id].issue &&
        !evidence[id].loading;
      const good =
        targets.length > 0 &&
        targets.length === draft.parts.length &&
        validText(draft.reason) &&
        validAt(draft.at) &&
        (count === null || (Number.isSafeInteger(count) && count >= 0)) &&
        draft.basis.length > 0 &&
        new Set(draft.basis).size === draft.basis.length &&
        new Set(draft.applicabilityBasis).size ===
          draft.applicabilityBasis.length &&
        new Set(draft.checks).size === draft.checks.length &&
        draft.checks.every(validText) &&
        draft.basis.every(usable) &&
        (draft.applicability !== "not_applicable" ||
          (draft.applicabilityBasis.length > 0 &&
            draft.applicabilityBasis.every(usable)));
      if (!good) {
        valid = false;
        continue;
      }
      mappings.push({
        rule_id: rule.id,
        categories: [...new Set(targets.map((p) => p.part.category))],
        target_part_ids: targets.map((p) => p.part.part_id),
        minimum_count: count,
        applicability: draft.applicability,
        applicability_evidence_ids:
          draft.applicability === "not_applicable"
            ? [...draft.applicabilityBasis]
            : [],
        valid_at: draft.at || null,
        checks:
          count === null
            ? [...draft.checks]
            : [...new Set([...draft.checks, "quantity"])],
        reason: draft.reason.trim(),
        basis_evidence_ids: [...draft.basis],
      });
    }
    return {
      mappings: changed ? [] : mappings,
      valid,
      dirty: dirty || changed,
    };
  }, [drafts, evidence, contextValid, changed, rules, parts, dirty]);
  const signature = JSON.stringify(value);
  const callback = useRef(onChange);
  callback.current = onChange;
  useEffect(() => {
    callback.current(JSON.parse(signature) as CheckPlanValue);
  }, [signature]);
  function patch(id: string, update: Partial<Draft>) {
    if (locked) return;
    setDirty(true);
    setDrafts((old) => ({
      ...old,
      [id]: { ...(old[id] ?? fresh()), ...update },
    }));
  }
  return (
    <section className="requirement-check-plan" aria-label="人工检查计划">
      <h4>人工检查计划</h4>
      <p>
        这里只注释检查范围与依据，不编辑原规则，也不生成已核验或正式审查结论。默认不映射任何条款。
      </p>
      <p>
        取消勾选会从本次计划中移除此条映射，原历史不会改写。引用显示已发布仍须由服务端核对当前来源效力。
      </p>
      {(!contextValid || changed) && (
        <p role="alert">
          包、规则或条件快照已变化或范围不符。原草稿已锁定，请保留内容并重新开启当前检查计划。
        </p>
      )}
      {rules.rules.length === 0 && (
        <p>所选规则集中暂无条款，不能据此认定要求完整。</p>
      )}
      {rules.rules.map((rule, index) => {
        const draft = drafts[rule.id] ?? fresh();
        return (
          <article key={rule.id}>
            <label>
              <input
                type="checkbox"
                checked={draft.enabled}
                disabled={locked}
                onChange={() => patch(rule.id, { enabled: !draft.enabled })}
              />
              映射要求 {index + 1}
            </label>
            <p>{rule.statement}</p>
            <details>
              <summary>原规则条件与例外（只读）</summary>
              <pre>
                {JSON.stringify(
                  { conditions: rule.conditions, exceptions: rule.exceptions },
                  null,
                  2,
                )}
              </pre>
            </details>
            {draft.enabled && (
              <fieldset disabled={locked}>
                <legend>要求 {index + 1} 的明确检查计划</legend>
                <p>本方目标范围（勾选明确物理页段，分类由所选范围自动取得）</p>
                {parts.map(({ part, member, fileIndex, partIndex }) => (
                  <label key={part.part_id}>
                    <input
                      type="checkbox"
                      checked={draft.parts.includes(part.part_id)}
                      onChange={() =>
                        patch(rule.id, {
                          parts: toggle(draft.parts, part.part_id),
                        })
                      }
                    />
                    文件 {fileIndex} · 分册 {partIndex} ·{" "}
                    {[
                      ...new Set(
                        [...member.purposes, part.category].map(
                          (v) => categoryNames[v] ?? v,
                        ),
                      ),
                    ].join("、")}{" "}
                    · 物理页 {part.first_page}—{part.last_page}
                    {part.shared_attachment ? "（共享附件）" : ""}
                  </label>
                ))}
                {!!parts.length && (
                  <details>
                    <summary>目标范围冻结身份</summary>
                    {parts.map(({ part, member, fileIndex, partIndex }) => (
                      <p key={part.part_id}>
                        文件 {fileIndex} · 分册 {partIndex}：{part.part_id} ·
                        文件版本 {member.document_version_id} · 解析{" "}
                        {member.parse.parse_run_id ?? "尚未冻结"}
                        {part.heading_path.length
                          ? ` · 原标题路径 ${part.heading_path.join(" / ")}`
                          : ""}
                      </p>
                    ))}
                  </details>
                )}
                {!parts.length && (
                  <p role="alert">本方包没有明确逻辑范围，无法映射。</p>
                )}
                <label>
                  <input
                    type="checkbox"
                    checked={draft.quantityUnknown}
                    onChange={() =>
                      patch(rule.id, {
                        quantityUnknown: !draft.quantityUnknown,
                      })
                    }
                  />
                  要求 {index + 1} 数量未知
                </label>
                {!draft.quantityUnknown && (
                  <label>
                    要求 {index + 1} 最小数量
                    <input
                      inputMode="numeric"
                      value={draft.quantity}
                      onChange={(e) =>
                        patch(rule.id, { quantity: e.target.value })
                      }
                    />
                  </label>
                )}
                {!draft.quantityUnknown && (
                  <p>
                    明确数量（包括
                    0）会同时声明“数量逐项核对”；这不是已完成核验。
                  </p>
                )}
                <label>
                  要求 {index + 1} 适用性
                  <select
                    value={draft.applicability}
                    onChange={(e) =>
                      patch(rule.id, {
                        applicability: e.target.value as Draft["applicability"],
                      })
                    }
                  >
                    <option value="unknown">未知</option>
                    <option value="applicable">适用</option>
                    <option value="not_applicable">有据不适用</option>
                  </select>
                </label>
                <label>
                  要求 {index + 1} 有效时点（可留空，填写须有时区）
                  <input
                    value={draft.at}
                    placeholder="2026-10-19T08:00:00+08:00"
                    onChange={(e) => patch(rule.id, { at: e.target.value })}
                  />
                </label>
                <p>计划检查项</p>
                {Object.entries(checkNames).map(([key, label]) => (
                  <label key={key}>
                    <input
                      type="checkbox"
                      checked={
                        draft.checks.includes(key) ||
                        (key === "quantity" && !draft.quantityUnknown)
                      }
                      disabled={key === "quantity" && !draft.quantityUnknown}
                      onChange={() =>
                        patch(rule.id, { checks: toggle(draft.checks, key) })
                      }
                    />
                    {label}
                  </label>
                ))}
                <label>
                  要求 {index + 1} 人工映射理由（最多200字）
                  <textarea
                    value={draft.reason}
                    onChange={(e) => patch(rule.id, { reason: e.target.value })}
                  />
                </label>
                <p>请明确勾选原规则的冻结原页依据，不会自动选用。</p>
                {!rule.evidence_ids.length && (
                  <p role="alert">原规则没有可定位依据，无法保存此项映射。</p>
                )}
                {rule.evidence_ids.map((id, n) => {
                  const record = evidence[id];
                  const usable =
                    !!record?.value && !record.issue && !record.loading;
                  return (
                    <div className="requirement-check-plan-evidence" key={id}>
                      <p>
                        依据 {n + 1}
                        {record?.value
                          ? ` · 物理页 ${record.value.physical_page}${record.value.printed_label ? ` · 印刷页 ${record.value.printed_label}` : ""}`
                          : ""}
                      </p>
                      {record?.loading && <p>正在读取精确引用…</p>}
                      {record?.issue && <p role="alert">{record.issue}</p>}
                      {record?.value && !record.issue && !record.loading && (
                        <blockquote>{record.value.quote}</blockquote>
                      )}
                      <label>
                        <input
                          type="checkbox"
                          disabled={!usable}
                          checked={draft.basis.includes(id)}
                          onChange={() =>
                            patch(rule.id, { basis: toggle(draft.basis, id) })
                          }
                        />
                        要求 {index + 1} 采用依据 {n + 1}
                      </label>
                      {draft.applicability === "not_applicable" && (
                        <label>
                          <input
                            type="checkbox"
                            disabled={!usable}
                            checked={draft.applicabilityBasis.includes(id)}
                            onChange={() =>
                              patch(rule.id, {
                                applicabilityBasis: toggle(
                                  draft.applicabilityBasis,
                                  id,
                                ),
                              })
                            }
                          />
                          要求 {index + 1} 不适用依据 {n + 1}
                        </label>
                      )}
                    </div>
                  );
                })}
                <button type="button" onClick={() => setRetry((v) => v + 1)}>
                  重新读取要求 {index + 1} 的引用
                </button>
                <p>
                  已选分类：
                  {[
                    ...new Set(
                      parts
                        .filter((p) => draft.parts.includes(p.part.part_id))
                        .map((p) => p.part.category),
                    ),
                  ]
                    .map((v) => categoryNames[v] ?? v)
                    .join("、") || "尚未选择范围"}
                </p>
              </fieldset>
            )}
          </article>
        );
      })}
      <p role="status">
        {value.valid
          ? `${value.mappings.length} 条检查计划可提交核对（未形成核验结论）`
          : "检查计划尚不完整或依据不可用，请核对范围、数量、时点、理由及显式证据。"}
      </p>
    </section>
  );
}
