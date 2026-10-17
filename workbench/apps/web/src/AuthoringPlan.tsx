import { useState, useEffect } from "react";
import type { ApiResult } from "./api";
import type {
  DraftView,
  AuthoringPlanSave,
  AuthoringPlanSaved,
} from "./contracts";
import { initialPlan, type TreeNode } from "./authoringStructureState";
import { useKnowledgeInput } from "./knowledgeStorage";
import { useRecordedCommand } from "./useRecordedCommand";
import {
  AuthoringRulePicker,
  AuthoringSourcePicker,
} from "./AuthoringReferences";
import { EvidenceLinks } from "./EvidenceLinks";
import { ErrorNotice } from "./components";
export function AuthoringPlan({
  bidId,
  memberId,
  draftId,
  node,
  draftRevision,
  disabled,
  prepare,
  onSaved,
  onBusy,
}: {
  bidId: string;
  memberId: string;
  draftId: string;
  node: TreeNode;
  draftRevision: number;
  disabled: boolean;
  prepare: () => Promise<ApiResult<DraftView> | null>;
  onSaved: () => Promise<void>;
  onBusy?: (busy: boolean) => void;
}) {
  const [form, setForm] = useKnowledgeInput(
    `tender:knowledge:${memberId}:authoring-plan:${draftId}:${node.section_id}:${node.plan?.revision ?? 0}`,
    initialPlan(node, draftRevision),
  );
  const cmd = useRecordedCommand(
    `authoring-plan:${memberId}:${draftId}:${node.section_id}`,
  );
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const [preparing, setPreparing] = useState(false);
  function change(p: Partial<AuthoringPlanSave>) {
    setForm((old) => ({ ...old, ...p }));
    setSaved(false);
  }
  async function save(retry = false) {
    if (disabled || preparing) return;
    setPreparing(true);
    setError(null);
    try {
      let r;
      if (retry) r = await cmd.retry<AuthoringPlanSaved>();
      else {
        const h = await prepare();
        if (!h?.etag) return;
        const body = {
          ...form,
          key_points: form.key_points.map((v) => v.trim()).filter(Boolean),
          pending_facts: form.pending_facts
            .map((v) => v.trim())
            .filter(Boolean),
          base_draft_revision: h.data.revision,
        };
        r = await cmd.run<AuthoringPlanSaved>(
          `/bids/${bidId}/drafts/${draftId}/sections/${node.section_id}/plan`,
          body,
          h.etag,
          "PUT",
        );
      }
      if (r) {
        if (
          r.data.plan.section_id !== node.section_id ||
          r.data.draft_id !== draftId
        )
          throw new Error("计划保存身份不一致，请读取当前计划核对。");
        setForm((old) => ({
          ...old,
          base_plan_revision: r.data.plan.revision,
        }));
        setSaved(true);
        await onSaved();
      }
    } catch (e) {
      setError(e);
    } finally {
      setPreparing(false);
    }
  }
  useEffect(() => {
    onBusy?.(preparing || cmd.busy || !!cmd.pending);
    return () => onBusy?.(false);
  }, [preparing, cmd.busy, cmd.pending, onBusy]);
  const locked = disabled || preparing || cmd.busy || !!cmd.pending;
  return (
    <details className="coverage-details">
      <summary>本章编写计划 · {node.title}</summary>
      <div className="authoring-plan">
        {(cmd.conflict ||
          form.base_plan_revision !== (node.plan?.revision ?? 0)) &&
          node.plan && (
            <details open>
              <summary>
                服务器当前计划 · 修订 {node.plan.revision}（你的输入保留在下方）
              </summary>
              <p>
                当前目标：
                {typeof node.plan.payload.goal === "string"
                  ? node.plan.payload.goal
                  : "未填写"}
              </p>
              <p>
                当前预算：{node.plan.planned_pages ?? "未填写"}{" "}
                页；实际章页仍未测得。
              </p>
              <pre className="structure-json">
                {JSON.stringify(node.plan.payload, null, 2)}
              </pre>
            </details>
          )}

        <p className="small-note">
          计划修订 {node.plan?.revision ?? 0} ·
          页数为人工预算，不是实际排版页数。
          {node.plan_content_basis_state === "section_changed"
            ? "正文已变化，原计划基准需重新核对。"
            : ""}
        </p>
        <label>
          编写状态
          <select
            value={form.state}
            disabled={locked}
            onChange={(e) =>
              change({ state: e.target.value as AuthoringPlanSave["state"] })
            }
          >
            {Object.entries({
              not_started: "未开始",
              drafting: "编写中",
              needs_basis: "待补依据",
              ready: "编写就绪（不等于评审通过）",
            }).map(([v, t]) => (
              <option value={v} key={v}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label>
          本章目标
          <textarea
            value={form.goal}
            disabled={locked}
            maxLength={8000}
            onChange={(e) => change({ goal: e.target.value })}
          />
        </label>
        <label>
          关键点（每行一项）
          <textarea
            disabled={locked}
            value={form.key_points.join("\n")}
            onChange={(e) => change({ key_points: e.target.value.split("\n") })}
          />
        </label>
        <label>
          待核工程事实（每行一项）
          <textarea
            disabled={locked}
            value={form.pending_facts.join("\n")}
            onChange={(e) =>
              change({ pending_facts: e.target.value.split("\n") })
            }
          />
        </label>
        <label>
          人工计划页数
          <input
            type="number"
            min={1}
            max={10000}
            value={form.planned_pages ?? ""}
            disabled={locked}
            onChange={(e) =>
              change({
                planned_pages: e.target.value ? Number(e.target.value) : null,
                budget_basis: "manual",
                budget_rule_id: null,
              })
            }
          />
        </label>
        <label>
          页数预算说明
          <textarea
            value={form.budget_note}
            disabled={locked}
            maxLength={2000}
            onChange={(e) => change({ budget_note: e.target.value })}
          />
        </label>
        <p className="small-note">
          当前依据：
          {form.budget_basis === "manual"
            ? "人工预算"
            : form.budget_basis === "template"
              ? "原目录模板明确预算"
              : "原要求依据预算"}
          。修改页数时改为人工预算，不能称为官方页数要求。
        </p>
        <AuthoringRulePicker
          bidId={bidId}
          selected={form.rule_ids}
          disabled={locked}
          onToggle={(id, check) =>
            change({
              rule_ids: check
                ? [...new Set([...form.rule_ids, id])]
                : form.rule_ids.filter((v) => v !== id),
            })
          }
        />
        {form.source_refs.map((ref) => (
          <div className="review-shortcuts" key={ref.evidence_id}>
            <EvidenceLinks ids={[ref.evidence_id]} label="查看计划来源原页" />
            <button
              type="button"
              className="text-button"
              disabled={locked}
              onClick={() =>
                change({
                  source_refs: form.source_refs.filter(
                    (v) => v.evidence_id !== ref.evidence_id,
                  ),
                })
              }
            >
              移除此计划关联
            </button>
          </div>
        ))}
        <AuthoringSourcePicker
          bidId={bidId}
          disabled={locked}
          onAdd={(ref) =>
            change({
              source_refs: [
                ...form.source_refs.filter(
                  (v) => v.evidence_id !== ref.evidence_id,
                ),
                ref,
              ],
            })
          }
        />
        <ErrorNotice error={error ?? cmd.error} />
        {cmd.conflict && (
          <p className="notice warning">
            计划或正文已有新版本，输入已保留。读取最新计划后对照并重新保存，不覆盖他人修改。
          </p>
        )}
        {saved && <p role="status">计划已保存；页数仍为预算。</p>}
        <button
          className="button secondary"
          disabled={
            locked || form.base_plan_revision !== (node.plan?.revision ?? 0)
          }
          onClick={() => void save()}
        >
          保存编写计划
        </button>
        {cmd.conflict && (
          <button className="text-button" onClick={() => void onSaved()}>
            读取当前正文与计划，保留输入
          </button>
        )}
        {form.base_plan_revision !== (node.plan?.revision ?? 0) && (
          <button
            className="text-button"
            onClick={() =>
              change({ base_plan_revision: node.plan?.revision ?? 0 })
            }
          >
            已对照当前计划修订 {node.plan?.revision ?? 0}，保留输入重新保存
          </button>
        )}
        {cmd.pending && (
          <button
            type="button"
            className="button secondary"
            disabled={cmd.busy || disabled}
            onClick={() => void save(true)}
          >
            恢复原计划保存结果
          </button>
        )}
      </div>
    </details>
  );
}
