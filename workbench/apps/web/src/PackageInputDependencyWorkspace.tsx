import { useEffect, useRef, useState } from "react";
import { api, supportsApi } from "./api";
import { ErrorNotice } from "./components";
import { EvidenceLinks } from "./EvidenceLinks";
import PackagePreparedFactPicker from "./PackagePreparedFactPicker";
import type {
  CheckPackageInputDependencies,
  PackageInputDependencyAssessment,
  PackageInputDependencies_Dependency,
  PackagePreparedFactSummary,
  PackageRequirementInventoryView,
} from "./contracts";
import {
  dependencyInventoryPath,
  dependencyPath,
  ruleEvidenceIds,
  validDependencyRequest,
  validateDependencyAssessment,
  validateDependencyInventory,
} from "./inputDependencyProtocol";
import type {
  DependencyProps,
  DependencyRequirement,
} from "./inputDependencyProtocol";
import "./packageInputDependencies.css";

type Draft = {
  row: DependencyRequirement;
  state: PackageInputDependencies_Dependency["state"];
  factIds: string[];
  reason: string;
  checked: boolean;
};
const statusNames = {
  unknown: "事实需求尚未核定",
  missing: "缺少所需事实或尚未选用",
  selected_unvalidated: "已选事实，当前资格仍须核验",
  not_used: "已声明本次不依赖事实",
};
export default function PackageInputDependencyWorkspace(
  props: DependencyProps,
) {
  return (
    <Workspace
      key={JSON.stringify([
        props.scope,
        props.frozen.digest,
        props.prepared.manifest.id,
        props.prepared.digest,
      ])}
      {...props}
    />
  );
}
function Workspace(props: DependencyProps) {
  const [inventory, setInventory] =
      useState<PackageRequirementInventoryView | null>(null),
    [drafts, setDrafts] = useState<
      Record<string, PackageInputDependencies_Dependency>
    >({}),
    [editing, setEditing] = useState<Draft | null>(null),
    [labels, setLabels] = useState<Record<string, PackagePreparedFactSummary>>(
      {},
    ),
    [selected, setSelected] = useState<string[]>([]),
    [visible, setVisible] = useState(20),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null),
    [result, setResult] = useState<PackageInputDependencyAssessment | null>(
      null,
    );
  const active = useRef(false),
    ticket = useRef(0);
  const path = dependencyPath(props),
    available = supportsApi("POST", path);
  useEffect(() => {
    const requests = ticket;
    active.current = true;
    requests.current++;
    return () => {
      active.current = false;
      requests.current++;
    };
  }, []);
  function invalidate() {
    ticket.current++;
    setResult(null);
    setError(null);
  }
  async function load() {
    if (busy || !available) return;
    const current = ++ticket.current;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const { data } = await api<PackageRequirementInventoryView>(
        dependencyInventoryPath(props.scope),
      );
      await validateDependencyInventory(data, props);
      if (active.current && ticket.current === current) setInventory(data);
    } catch (failure) {
      if (active.current && ticket.current === current) setError(failure);
    } finally {
      if (active.current && ticket.current === current) setBusy(false);
    }
  }
  function edit(row: DependencyRequirement) {
    invalidate();
    const old = drafts[row.rule_id];
    setEditing({
      row,
      state: old?.state ?? "unknown",
      factIds: old?.fact_ids ?? [],
      reason: old?.reason ?? "",
      checked: false,
    });
  }
  function apply() {
    if (
      !editing ||
      !editing.checked ||
      !editing.reason.trim() ||
      !ruleEvidenceIds(editing.row).length
    )
      return;
    const declaration: PackageInputDependencies_Dependency = {
      requirement_id: editing.row.rule_id,
      requirement_digest: editing.row.requirement_digest,
      state: editing.state,
      fact_ids: editing.state === "required" ? editing.factIds : [],
      evidence_ids: ruleEvidenceIds(editing.row),
      reason: editing.reason.trim(),
    };
    const body: CheckPackageInputDependencies = {
      execution_input_digest: props.prepared.digest,
      purpose: "prebid_compliance",
      fact_ids: selected,
      dependencies: [declaration],
    };
    if (!validDependencyRequest(body, props)) {
      setError(
        new Error("本轮依赖草稿字段不符合协议，请核对原页、事实与理由。"),
      );
      return;
    }
    invalidate();
    setDrafts((old) => ({ ...old, [declaration.requirement_id]: declaration }));
    setEditing(null);
  }
  async function calculate() {
    if (!inventory || busy || editing || !available) return;
    const body: CheckPackageInputDependencies = {
      execution_input_digest: props.prepared.digest,
      purpose: "prebid_compliance",
      fact_ids: [...selected].sort(),
      dependencies: Object.values(drafts).sort((a, b) =>
        a.requirement_id < b.requirement_id ? -1 : 1,
      ),
    };
    if (!validDependencyRequest(body, props)) {
      setError(new Error("本轮事实选择或依赖草稿不符合协议，未发送核对请求。"));
      return;
    }
    const current = ++ticket.current;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const { data } = await api<PackageInputDependencyAssessment>(path, {
        method: "POST",
        body,
      });
      await validateDependencyAssessment(data, props, inventory, body);
      if (active.current && ticket.current === current) setResult(data);
    } catch (failure) {
      if (active.current && ticket.current === current) setError(failure);
    } finally {
      if (active.current && ticket.current === current) setBusy(false);
    }
  }
  return (
    <details className="package-input-dependencies">
      <summary>逐条核对事实需求</summary>
      <div className="package-input-dependencies__body">
        <p>
          以此准备输入的原要求及原事实为依据，明确哪些事实是本次核对所需。空选择不表示无需事实。
        </p>
        <p>
          草稿只保留在当前页面；计算不会保存声明或启动评审，抽取完整性与当前事实资格仍须分别核验。
        </p>
        {!available && <p>当前服务尚未提供逐条事实依赖评估。</p>}
        <div className="package-input-dependencies__actions">
          <button
            type="button"
            className="button secondary"
            disabled={busy || !available}
            onClick={() => void load()}
          >
            {busy && !inventory ? "正在读取原要求…" : "读取原要求清单"}
          </button>
          <button
            type="button"
            className="button secondary"
            disabled={busy || !inventory || !!editing || !available}
            onClick={() => void calculate()}
          >
            {busy && inventory ? "正在核对依赖…" : "计算本轮依赖缺口（不保存）"}
          </button>
        </div>
        {error != null && <ErrorNotice error={error} />}
        {inventory && (
          <>
            <p>
              原要求 {inventory.manifest.requirements.length} 条；本页草稿已标注{" "}
              {Object.keys(drafts).length} 条，本轮明确选用事实{" "}
              {selected.length} 条。
            </p>
            {!inventory.manifest.requirements.length && (
              <p>原清单为空，不能默认没有要求或必要事实。</p>
            )}
            {selected.length > 0 && (
              <section aria-label="本轮实际选用事实">
                <h6>本轮实际选用事实</h6>
                <ul>
                  {selected.map((id) => (
                    <li key={id}>
                      <span>
                        {labels[id]?.name ?? "已选原事实"} ·{" "}
                        {labels[id]?.value_preview ?? ""}
                      </span>
                      <button
                        type="button"
                        className="text-button"
                        disabled={busy}
                        onClick={() => {
                          invalidate();
                          setSelected((old) => old.filter((x) => x !== id));
                        }}
                      >
                        取消本轮选用
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            )}
            <ol className="package-input-dependencies__requirements">
              {inventory.manifest.requirements
                .slice(0, visible)
                .map((row, index) => (
                  <li key={row.rule_id}>
                    <div>
                      <strong>要求 {index + 1}</strong>
                      <p>
                        {typeof row.rule_snapshot.statement === "string"
                          ? Array.from(row.rule_snapshot.statement)
                              .slice(0, 240)
                              .join("")
                          : "请核对原规则内容"}
                      </p>
                      {typeof row.rule_snapshot.statement === "string" &&
                        Array.from(row.rule_snapshot.statement).length >
                          240 && (
                          <small>
                            原文摘要已截断，请打开此要求的原页核对全文。
                          </small>
                        )}
                      <small>
                        {drafts[row.rule_id]
                          ? `本轮已标注：${drafts[row.rule_id].state === "required" ? "需要事实" : drafts[row.rule_id].state === "not_needed" ? "本次不依赖事实" : "仍待核定"}`
                          : "尚未核定事实需求"}
                      </small>
                      {result && (
                        <p>
                          {
                            statusNames[
                              result.manifest.requirements.find(
                                (r) => r.requirement_id === row.rule_id,
                              )!.fact_status
                            ]
                          }
                        </p>
                      )}
                    </div>
                    <button
                      type="button"
                      className="button secondary"
                      disabled={busy}
                      onClick={() => edit(row)}
                    >
                      核对第 {index + 1} 条要求
                    </button>
                  </li>
                ))}
            </ol>
            {visible < inventory.manifest.requirements.length && (
              <button
                type="button"
                className="button secondary"
                onClick={() => setVisible((n) => n + 20)}
              >
                展开更多原要求
              </button>
            )}
          </>
        )}
        {editing && (
          <fieldset
            disabled={busy}
            className="package-input-dependencies__editor"
          >
            <legend>本轮依赖草稿</legend>
            <details>
              <summary>查看原要求全文</summary>
              <p>
                {typeof editing.row.rule_snapshot.statement === "string"
                  ? editing.row.rule_snapshot.statement
                  : "核对原要求及其证据"}
              </p>
            </details>
            <EvidenceLinks
              ids={ruleEvidenceIds(editing.row)}
              label="查看此要求原页"
            />
            {!ruleEvidenceIds(editing.row).length && (
              <p>原规则没有可核对依据，暂不能应用依赖草稿。</p>
            )}
            <label>
              本次事实需求
              <select
                value={editing.state}
                onChange={(e) => {
                  invalidate();
                  setEditing((old) =>
                    old
                      ? {
                          ...old,
                          state: e.target.value as Draft["state"],
                          factIds:
                            e.target.value === "required" ? old.factIds : [],
                          checked: false,
                        }
                      : old,
                  );
                }}
              >
                <option value="unknown">仍待核定</option>
                <option value="required">需要项目或公司事实</option>
                <option value="not_needed">本次不依赖事实</option>
              </select>
            </label>
            {editing.state === "required" && (
              <>
                <PackagePreparedFactPicker
                  description="读取此准备输入保存时的事实摘要。选择为所需事实后，仍须明确本轮是否实际选用。"
                  scope={props.scope}
                  frozenId={props.frozen.manifest.id}
                  prepared={props.prepared}
                  disabled={busy}
                  onSelect={(item) => {
                    invalidate();
                    setLabels((old) => ({ ...old, [item.fact_id]: item }));
                    setEditing((old) =>
                      old
                        ? {
                            ...old,
                            factIds: [
                              ...new Set([...old.factIds, item.fact_id]),
                            ],
                            checked: false,
                          }
                        : old,
                    );
                  }}
                />
                {!editing.factIds.length && (
                  <p>尚无对应事实时也可计算已知缺口，不会自动从事实池补齐。</p>
                )}
                <ul>
                  {editing.factIds.map((id) => (
                    <li key={id}>
                      <label className="package-input-dependencies__choice">
                        <input
                          type="checkbox"
                          checked={selected.includes(id)}
                          onChange={(e) => {
                            invalidate();
                            setSelected((old) =>
                              e.target.checked
                                ? [...new Set([...old, id])]
                                : old.filter((x) => x !== id),
                            );
                            setEditing((old) =>
                              old ? { ...old, checked: false } : old,
                            );
                          }}
                        />
                        本轮实际选用：{labels[id]?.name ?? "原事实"} ·{" "}
                        {labels[id]?.value_preview ?? ""}
                      </label>
                      <button
                        type="button"
                        className="text-button"
                        onClick={() => {
                          invalidate();
                          setEditing((old) =>
                            old
                              ? {
                                  ...old,
                                  factIds: old.factIds.filter((x) => x !== id),
                                  checked: false,
                                }
                              : old,
                          );
                        }}
                      >
                        移除此依赖
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            )}
            <label>
              依赖核对理由
              <textarea
                rows={3}
                maxLength={2000}
                value={editing.reason}
                onChange={(e) => {
                  invalidate();
                  setEditing((old) =>
                    old
                      ? { ...old, reason: e.target.value, checked: false }
                      : old,
                  );
                }}
              />
            </label>
            <label className="package-input-dependencies__choice">
              <input
                type="checkbox"
                checked={editing.checked}
                onChange={(e) =>
                  setEditing((old) =>
                    old ? { ...old, checked: e.target.checked } : old,
                  )
                }
              />
              我已核对以上要求原页，并确认本次事实依赖标注
            </label>
            <div className="package-input-dependencies__actions">
              <button
                type="button"
                className="button secondary"
                disabled={
                  !editing.checked ||
                  !editing.reason.trim() ||
                  !ruleEvidenceIds(editing.row).length
                }
                onClick={apply}
              >
                应用到本轮核对（不保存）
              </button>
              <button
                type="button"
                className="button secondary"
                onClick={() => setEditing(null)}
              >
                放弃此条编辑
              </button>
            </div>
          </fieldset>
        )}
        {result && (
          <div role="status" className="package-input-dependencies__result">
            <p>{statusNames[result.manifest.required_facts_assessment]}</p>
            <p>
              本次只核对依赖标注与原事实选择；要求抽取完整性、原件字节和当前事实资格未由此证明，尚未启动评审。
            </p>
            <details>
              <summary>核对输入与边界</summary>
              <p>
                评估摘要：<code>{result.digest}</code>
              </p>
              <p>
                政策摘要：<code>{result.manifest.policy_digest}</code>
              </p>
            </details>
          </div>
        )}
      </div>
    </details>
  );
}
