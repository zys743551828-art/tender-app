import { useCallback, useEffect, useRef, useState } from "react";
import { api, commandKey } from "./api";
import { ErrorNotice } from "./components";
import type { Comparison } from "./PartialPageComparison";

type Outcome =
  | "observed_support"
  | "observed_conflict"
  | "not_applicable"
  | "needs_review";
type Observation = {
  id: string;
  item_id: string;
  revision: number;
  actor_id: string;
  created_at: string;
  requirement_evidence_id: string;
  technical_evidence_id: string | null;
  outcome: Outcome;
  reason: string;
};
const names: Record<Outcome, string> = {
  observed_support: "所选依据显示支持",
  observed_conflict: "所选依据显示差异",
  not_applicable: "人工认为不适用",
  needs_review: "需要继续核对",
};

export function PartialScopeObservations({
  path,
  requirement,
  technical,
  comparison,
}: {
  path: string;
  requirement: string;
  technical: string;
  comparison: Comparison | null;
}) {
  const target = `${path}/${requirement}/compare/${technical}/decisions`;
  const [history, setHistory] = useState<Observation[]>([]);
  const [scopeValid, setScopeValid] = useState<boolean | null>(null);
  const [item, setItem] = useState<Observation | null>(null);
  const [req, setReq] = useState("");
  const [tech, setTech] = useState("");
  const [outcome, setOutcome] = useState<Outcome>("needs_review");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const generation = useRef(0);

  const refresh = useCallback(async () => {
    const request = ++generation.current;
    setScopeValid(null);
    const result = (
      await api<{
        items: Observation[];
        scope_revalidated: boolean;
        has_more: boolean;
      }>(target)
    ).data;
    if (
      !Array.isArray(result.items) ||
      typeof result.scope_revalidated !== "boolean" ||
      typeof result.has_more !== "boolean"
    )
      throw new Error("人工记录返回格式异常，请重新读取。");
    if (request !== generation.current) return;
    setHistory(result.items);
    setScopeValid(result.scope_revalidated);
    if (result.has_more)
      setError(new Error("只显示最近 100 条人工记录，较早记录未列出。"));
  }, [target]);
  useEffect(() => {
    let active = true;
    void refresh().catch((value) => {
      if (active) {
        setScopeValid(false);
        setError(value);
      }
    });
    return () => {
      active = false;
      generation.current += 1;
    };
  }, [refresh, comparison]);

  function choose(value: Observation) {
    setItem(value);
    setReq(value.requirement_evidence_id);
    setTech(value.technical_evidence_id ?? "");
    setOutcome(value.outcome);
    setReason(value.reason);
    setConfirmed(false);
  }
  function reset() {
    setItem(null);
    setReq("");
    setTech("");
    setOutcome("needs_review");
    setReason("");
    setConfirmed(false);
  }
  async function save() {
    if (!comparison || !scopeValid || !confirmed || !req || !reason.trim())
      return;
    const body = {
      item_id: item?.item_id ?? null,
      expected_revision: item?.revision ?? 0,
      requirement_evidence_id: req,
      technical_evidence_id: tech || null,
      outcome,
      reason,
      confirmed: true,
    };
    setBusy(true);
    setError(null);
    try {
      await api(target, {
        method: "POST",
        body,
        key: commandKey(
          `partial-observation:${requirement}:${technical}`,
          body,
        ),
      });
      reset();
      await refresh();
    } catch (value) {
      setError(value);
    } finally {
      setBusy(false);
    }
  }
  const needsTech =
    outcome === "observed_support" || outcome === "observed_conflict";
  const latest = new Map<string, number>();
  for (const value of history)
    latest.set(
      value.item_id,
      Math.max(latest.get(value.item_id) ?? 0, value.revision),
    );
  return (
    <section aria-label="人工逐项记录">
      <h4>人工逐项记录 · 整体仍未知</h4>
      <p>
        这些是针对所选依据的人工意见，来源有效性和原件仍须核对；不代表完整评审、模型提取或正式合规。
      </p>
      {scopeValid === null && <p>正在核对范围和读取历史记录。</p>}
      {scopeValid === false && (
        <p>
          范围未通过核验或记录读取失败；已有历史可查看，确认后才能继续记录。
        </p>
      )}
      <ErrorNotice error={error} />
      <button
        type="button"
        disabled={busy}
        onClick={() => {
          setError(null);
          void refresh().catch((value) => {
            setScopeValid(false);
            setError(value);
          });
        }}
      >
        重新核对范围与历史
      </button>
      {history.map((value) => (
        <div key={value.id}>
          <p>
            {names[value.outcome]} · 第 {value.revision} 版 ·{" "}
            {new Date(value.created_at).toLocaleString()} ·{" "}
            {value.actor_id.slice(0, 8)}：{value.reason}
          </p>
          {value.revision === latest.get(value.item_id) && (
            <button
              type="button"
              disabled={!comparison || !scopeValid || busy}
              onClick={() => choose(value)}
            >
              修改此项
            </button>
          )}
        </div>
      ))}
      {comparison && scopeValid && (
        <div>
          <p>{item ? `修改记录 · 第 ${item.revision} 版` : "新增人工意见"}</p>
          <label>
            要求依据
            <select
              value={req}
              disabled={item !== null}
              onChange={(event) => {
                setReq(event.target.value);
                setConfirmed(false);
              }}
            >
              <option value="">请选择</option>
              {comparison.requirement.evidence.items.map((value) => (
                <option key={value.id} value={value.id}>
                  第 {value.physical_page} 页 · {value.quote.slice(0, 70)}
                </option>
              ))}
            </select>
          </label>
          <label>
            技术依据
            <select
              value={tech}
              onChange={(event) => {
                setTech(event.target.value);
                setConfirmed(false);
              }}
            >
              <option value="">未选择</option>
              {comparison.technical.evidence.items.map((value) => (
                <option key={value.id} value={value.id}>
                  第 {value.physical_page} 页 · {value.quote.slice(0, 70)}
                </option>
              ))}
            </select>
          </label>
          <label>
            人工意见
            <select
              value={outcome}
              onChange={(event) => {
                setOutcome(event.target.value as Outcome);
                setConfirmed(false);
              }}
            >
              {Object.entries(names).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            核对理由
            <textarea
              maxLength={1000}
              value={reason}
              onChange={(event) => {
                setReason(event.target.value);
                setConfirmed(false);
              }}
            />
          </label>
          <label className="partial-checkbox">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            我已核对所选原页，理解此意见不代表完整合规。
          </label>
          <button
            type="button"
            disabled={
              busy ||
              !confirmed ||
              !req ||
              !reason.trim() ||
              (needsTech && !tech)
            }
            onClick={() => void save()}
          >
            保存人工意见
          </button>
          {item && (
            <button type="button" disabled={busy} onClick={reset}>
              取消修改
            </button>
          )}
        </div>
      )}
    </section>
  );
}
