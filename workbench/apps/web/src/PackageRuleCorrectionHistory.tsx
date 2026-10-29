import { useCallback, useEffect, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import type {
  PackageRequirementInventoryView,
  PackageRuleCorrectionAppliedView,
  PackageRuleCorrectionHistoryPage,
} from "./contracts";
import { ErrorNotice } from "./components";
import { jsonDigest } from "./editorSchema";
import { PackageRuleCorrectionSource } from "./PackageRuleCorrectionEvidence";
import { RuleSemanticDetails } from "./PackageRuleCorrectionDiff";
import {
  correctionInventoryMatches,
  correctionOperationNames,
  correctionProtocolFailure,
  correctionRuleSemantic,
  sameCorrectionValue,
  sameCorrectionInstant,
  validateCorrectionApplied,
  validateCorrectionHistory,
} from "./packageRuleCorrectionProtocol";
import {
  correctionBase,
  correctionInventoryPath,
  correctionPath,
  type CorrectionRecovery,
  type CorrectionScope,
} from "./packageRuleCorrectionRecovery";

type Row = PackageRuleCorrectionHistoryPage["items"][number];
type ReadRecord = {
  result: PackageRuleCorrectionAppliedView;
  original: PackageRequirementInventoryView;
};
function HistoryRecord({
  value,
  scope,
}: {
  value: ReadRecord;
  scope: CorrectionScope;
}) {
  const { correction, inventory } = value.result;
  const m = correction.manifest,
    base = correctionBase(value.original);
  return (
    <section
      className="rule-correction-history-detail"
      aria-label="已保存的规则修订记录"
    >
      <h5>已保存修订 · {new Date(m.created_at).toLocaleString()}</h5>
      <p>{m.request.reason}</p>
      <p>
        基线清单修订 {value.original.manifest.revision} → 新清单修订{" "}
        {inventory.manifest.revision}
      </p>
      <p className="notice neutral">
        这是原操作的历史结果。未改动当前清单，没有启动新评审；后续资料、规则或覆盖变化需另行核验。
      </p>
      {m.request.changes.map((change, index) => {
        const mapping =
          change.op === "add"
            ? m.additions.find((item) => item.change_index === index)
            : m.mappings.find((item) => item.change_index === index);
        const old =
          change.op === "add"
            ? null
            : value.original.manifest.requirements.find(
                (item) => item.rule_id === change.rule_id,
              );
        const next = inventory.manifest.requirements.find(
          (item) => item.rule_id === mapping?.to_rule_id,
        );
        const quotes =
          change.op === "withdraw"
            ? change.evidence_quotes
            : change.rule.evidence_quotes;
        return (
          <article className="rule-correction-change" key={index}>
            <h6>
              修订 {index + 1} · {correctionOperationNames[change.op]}
            </h6>
            <div className="rule-correction-comparison">
              <RuleSemanticDetails
                value={old ? correctionRuleSemantic(old.rule_snapshot) : null}
                label="历史原条款"
              />
              <RuleSemanticDetails
                value={next ? correctionRuleSemantic(next.rule_snapshot) : null}
                label="本次保存的条款"
              />
            </div>
            {quotes.map((quote, quoteIndex) => (
              <PackageRuleCorrectionSource
                key={`${quote.evidence_id}:${quoteIndex}`}
                scope={scope}
                base={base}
                quote={quote}
              />
            ))}
          </article>
        );
      })}
      <details>
        <summary>历史清单和原操作身份</summary>
        <p>原清单 {m.scope.inventory_id}</p>
        <p>结果清单 {m.result.inventory_id}</p>
        <p>
          修订记录 {m.id} · SHA256 {correction.digest}
        </p>
        <p>操作成员 {m.actor_id}</p>
        <p>原操作键 {value.result.command.idempotency_key}</p>
        <p>保留的原抽取质量：尚未测量；整包完整性：未确认。</p>
      </details>
    </section>
  );
}

export function PackageRuleCorrectionHistory({
  scope,
  inventoryId,
  last,
}: {
  scope: CorrectionScope;
  inventoryId: string;
  last: CorrectionRecovery["last"];
}) {
  const [opened, setOpened] = useState(false),
    [items, setItems] = useState<Row[]>([]),
    [next, setNext] = useState<string | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null),
    [loaded, setLoaded] = useState(false),
    [record, setRecord] = useState<ReadRecord | null>(null);
  const active = useRef(false),
    running = useRef(false),
    generation = useRef(0);
  const invalidate = useCallback(() => {
    generation.current++;
  }, []);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      invalidate();
    };
  }, [invalidate]);
  const path = correctionPath(scope, inventoryId);
  async function readPage(cursor: string | null = null) {
    if (running.current) return;
    running.current = true;
    const token = ++generation.current;
    setOpened(true);
    setBusy(true);
    setError(null);
    try {
      const { data } = await api<unknown>(
        `${path}?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
      );
      const page = validateCorrectionHistory(data, scope, inventoryId);
      if (cursor && page.has_more && page.next_cursor === cursor)
        throw new Error("历史游标没有推进，请重读目录。");
      const merged = new Map(
        (cursor ? items : []).map((item) => [item.id, item]),
      );
      for (const item of page.items) {
        const old = merged.get(item.id);
        if (old && !sameCorrectionValue(old, item)) correctionProtocolFailure();
        merged.set(item.id, item);
      }
      if (!active.current || token !== generation.current) return;
      setItems([...merged.values()]);
      setNext(page.has_more ? page.next_cursor : null);
      setLoaded(true);
    } catch (failure) {
      if (active.current && token === generation.current) setError(failure);
    } finally {
      running.current = false;
      if (active.current && token === generation.current) setBusy(false);
    }
  }
  async function read(row: Row) {
    if (running.current) return;
    running.current = true;
    const token = ++generation.current;
    setBusy(true);
    setError(null);
    setRecord(null);
    try {
      const [saved, original] = await Promise.all([
        api<unknown>(`${path}/${row.id}`),
        api<PackageRequirementInventoryView>(
          `${correctionInventoryPath(scope)}/${row.base_inventory_id}`,
        ),
      ]);
      if (
        !correctionInventoryMatches(original.data, scope) ||
        original.data.manifest.id !== row.base_inventory_id ||
        original.data.digest !== (await jsonDigest(original.data.manifest))
      )
        correctionProtocolFailure();
      const checked = await validateCorrectionApplied(
        saved.data,
        scope,
        { base: correctionBase(original.data), id: row.id, digest: row.digest },
        saved.etag,
      );
      const m = checked.correction.manifest;
      if (
        m.result.inventory_id !== row.result_inventory_id ||
        m.actor_id !== row.actor_id ||
        !sameCorrectionInstant(m.created_at, row.created_at) ||
        m.request.changes.filter((item) => item.op === "add").length !==
          row.added ||
        m.request.changes.filter((item) => item.op === "replace").length !==
          row.replaced ||
        m.request.changes.filter((item) => item.op === "withdraw").length !==
          row.withdrawn
      )
        correctionProtocolFailure();
      if (active.current && token === generation.current)
        setRecord({ result: checked, original: original.data });
    } catch (failure) {
      if (active.current && token === generation.current) setError(failure);
    } finally {
      running.current = false;
      if (active.current && token === generation.current) setBusy(false);
    }
  }
  return (
    <section className="rule-correction-history" aria-label="人工规则修订历史">
      <div className="section-heading">
        <h4>规则修订历史</h4>
        <button
          type="button"
          className="text-button"
          disabled={busy || !supportsApi("GET", path)}
          aria-expanded={opened}
          onClick={() => void readPage()}
        >
          读取修订历史
        </button>
      </div>
      {opened && (
        <>
          <p className="small-note">
            同一原抽取依据下的已保存修订；原操作、旧条款和结果清单均可追溯。
          </p>
          {busy && <p role="status">正在核对修订历史…</p>}
          {error != null && <ErrorNotice error={error} />}
          {loaded && !items.length && (
            <p>此抽取依据尚无已保存的人工规则修订。</p>
          )}
          <div className="rule-correction-history-list">
            {items.map((item, index) => (
              <button
                type="button"
                key={item.id}
                disabled={busy}
                aria-pressed={record?.result.correction.manifest.id === item.id}
                onClick={() => void read(item)}
              >
                <strong>
                  读取修订 {index + 1}
                  {last?.correctionId === item.id ? " · 最近确认" : ""}
                </strong>
                <span>
                  {new Date(item.created_at).toLocaleString()} · 补充{" "}
                  {item.added} · 替换 {item.replaced} · 撤销 {item.withdrawn}
                </span>
              </button>
            ))}
          </div>
          {next && (
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => void readPage(next)}
            >
              更多修订历史
            </button>
          )}
          {record && (
            <HistoryRecord
              key={record.result.correction.manifest.id}
              value={record}
              scope={scope}
            />
          )}
        </>
      )}
    </section>
  );
}
