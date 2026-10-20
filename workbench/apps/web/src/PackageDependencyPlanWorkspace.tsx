import { useEffect, useRef, useState } from "react";
import { api, ApiError, supportsApi } from "./api";
import { ErrorNotice } from "./components";
import type {
  CheckPackageInputDependencies,
  PackageDependencyPlanPage,
  PackageDependencyPlanView,
  PackageInputDependencyAssessment,
} from "./contracts";
import type { DependencyProps } from "./inputDependencyProtocol";
import {
  dependencyPlanPath,
  dependencyPlanScope,
  validPlanBody,
  validPlanPage,
  validatePlan,
} from "./dependencyPlanProtocol";
import type { PendingDependencyPlan } from "./dependencyPlanProtocol";
import {
  loadDependencyPlanRecord,
  storeDependencyPlanRecord,
} from "./dependencyPlanRecovery";
import type { DependencyPlanRecord } from "./dependencyPlanRecovery";
import "./packageDependencyPlans.css";

export type DependencyPlanCandidate = {
  request: CheckPackageInputDependencies;
  assessment: PackageInputDependencyAssessment;
};
type Props = DependencyProps & {
  candidate: DependencyPlanCandidate | null;
  onRecheck: () => void;
};
const states = {
  unknown: "事实需求尚未核定",
  missing: "缺少所需事实或尚未选用",
  selected_unvalidated: "已选事实，当前资格仍须核验",
  not_used: "已声明本次不依赖事实",
};
const rejected = new Set([
  "PACKAGE_INPUT_DEPENDENCIES_CHANGED",
  "PACKAGE_EXECUTION_INPUT_CHANGED",
  "PACKAGE_DEPENDENCY_PLAN_INVALID",
  "PACKAGE_DEPENDENCY_PLAN_REJECTED",
  "INVALID_REQUEST",
  "PROJECT_WORK_CLOSED",
]);
export default function PackageDependencyPlanWorkspace(props: Props) {
  return (
    <Workspace key={JSON.stringify(dependencyPlanScope(props))} {...props} />
  );
}
function Workspace(props: Props) {
  const [loaded] = useState(() => {
    try {
      return { record: loadDependencyPlanRecord(props), error: null };
    } catch (error) {
      return { record: null, error };
    }
  });
  const [record, setRecord] = useState<DependencyPlanRecord | null>(
      loaded.record,
    ),
    recordRef = useRef(record);
  const [open, setOpen] = useState(!!loaded.record?.pending);
  const [reason, setReason] = useState(
    loaded.record?.pending?.body.reason ?? "",
  );
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState<unknown>(loaded.error);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [historyVisible, setHistoryVisible] = useState(20);
  const [page, setPage] = useState<PackageDependencyPlanPage | null>(null);
  const [history, setHistory] = useState<PackageDependencyPlanView | null>(
    null,
  );
  const active = useRef(false),
    writing = useRef(false),
    ticket = useRef(0);
  const path = dependencyPlanPath(props),
    scope = dependencyPlanScope(props);
  const saveAvailable = supportsApi("POST", path),
    readAvailable = supportsApi("GET", path);
  useEffect(() => {
    const requests = ticket;
    active.current = true;
    return () => {
      active.current = false;
      requests.current++;
    };
  }, []);
  useEffect(() => {
    setConfirmed(false);
  }, [props.candidate?.assessment.digest]);
  function persist(next: DependencyPlanRecord) {
    storeDependencyPlanRecord(next);
    recordRef.current = next;
    setRecord(next);
    if (next.pending) setOpen(true);
  }
  async function save(recover: boolean) {
    const current = recordRef.current;
    if (
      !active.current ||
      writing.current ||
      busy ||
      !saveAvailable ||
      !current
    )
      return;
    const pending: PendingDependencyPlan | null = recover
      ? current.pending
      : !current.pending && props.candidate && confirmed
        ? {
            key: crypto.randomUUID(),
            body: {
              ...props.candidate.request,
              assessment_digest: props.candidate.assessment.digest,
              reason: reason.trim(),
            },
          }
        : null;
    if (!pending || !validPlanBody(pending.body, props)) return;
    writing.current = true;
    const request = ++ticket.current;
    setBusy(true);
    setSaving(true);
    setError(null);
    setHistory(null);
    try {
      persist({ ...current, pending });
      let data: PackageDependencyPlanView;
      try {
        ({ data } = await api<PackageDependencyPlanView>(path, {
          method: "POST",
          key: pending.key,
          body: pending.body,
        }));
      } catch (failure) {
        if (
          active.current &&
          failure instanceof ApiError &&
          (recover
            ? [
                "PACKAGE_INPUT_DEPENDENCIES_CHANGED",
                "PACKAGE_EXECUTION_INPUT_CHANGED",
                "PROJECT_WORK_CLOSED",
              ].includes(failure.code)
            : rejected.has(failure.code))
        ) {
          persist({ ...current, pending: null });
          props.onRecheck();
        }
        throw failure;
      }
      await validatePlan(data, props, pending);
      if (!active.current || ticket.current !== request) return;
      persist({ ...current, pending: null, lastId: data.manifest.id });
      setConfirmed(false);
      setHistory(data);
      setHistoryVisible(20);
      setPage(null);
    } catch (failure) {
      if (active.current && ticket.current === request) setError(failure);
    } finally {
      writing.current = false;
      if (active.current && ticket.current === request) {
        setBusy(false);
        setSaving(false);
      }
    }
  }
  async function list(next = false) {
    if (
      busy ||
      writing.current ||
      !readAvailable ||
      (next && !page?.next_cursor)
    )
      return;
    const request = ++ticket.current;
    setBusy(true);
    setError(null);
    try {
      const { data } = await api<PackageDependencyPlanPage>(
        `${path}?limit=10${next ? `&cursor=${encodeURIComponent(page!.next_cursor!)}` : ""}`,
      );
      if (!validPlanPage(data, scope))
        throw new Error("计划目录与原准备输入不符，未采用其他历史。");
      if (next && page?.items.length && data.items.length) {
        const last = page.items[page.items.length - 1],
          first = data.items[0];
        if (`${first.saved_at}/${first.id}` <= `${last.saved_at}/${last.id}`)
          throw new Error("计划目录未按原游标向后读取，未重复采用旧页。");
      }
      if (!active.current || ticket.current !== request) return;
      setPage(data);
    } catch (failure) {
      if (active.current && ticket.current === request) setError(failure);
    } finally {
      if (active.current && ticket.current === request) setBusy(false);
    }
  }
  async function read(id: string, digest?: string) {
    if (busy || writing.current || !readAvailable) return;
    const request = ++ticket.current;
    setBusy(true);
    setError(null);
    setHistory(null);
    try {
      const { data } = await api<PackageDependencyPlanView>(`${path}/${id}`);
      await validatePlan(data, props);
      if (data.manifest.id !== id || (digest && data.digest !== digest))
        throw new Error("指定计划历史身份或摘要不符，未采用其他记录。");
      if (active.current && ticket.current === request) {
        setHistory(data);
        setHistoryVisible(20);
      }
    } catch (failure) {
      if (active.current && ticket.current === request) setError(failure);
    } finally {
      if (active.current && ticket.current === request) setBusy(false);
    }
  }
  const pending = record?.pending;
  return (
    <details
      className="package-dependency-plans"
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary>保存与查阅依赖计划</summary>
      <div className="package-dependency-plans__body">
        <p>
          保存本轮明确选择与逐条标注，保留当时的核对结果。保存不等于事实已核验、清单已完整或评审已启动。
        </p>
        {!saveAvailable && <p>当前服务尚未提供计划保存接口。</p>}
        {!record && (
          <p>本机恢复记录无法核验，已禁止新保存；可只读查阅服务器历史。</p>
        )}
        {pending ? (
          <section
            className="package-dependency-plans__pending"
            aria-label="待恢复的原计划请求"
          >
            <p>
              此准备输入有一笔尚未核清回执的保存。恢复只重放同一请求和幂等键，不替换为当前页面的新标注。
            </p>
            <p>原保存理由：{pending.body.reason}</p>
            <button
              type="button"
              className="button secondary"
              disabled={busy || !saveAvailable}
              onClick={() => void save(true)}
            >
              恢复原计划保存回执
            </button>
          </section>
        ) : (
          <fieldset disabled={busy || !record || !saveAvailable}>
            <legend>明确保存本轮计划</legend>
            {props.candidate ? (
              <p>
                本轮已核对要求{" "}
                {props.candidate.assessment.manifest.requirement_count}{" "}
                条，实际选用事实 {props.candidate.request.fact_ids.length} 条：
                {
                  states[
                    props.candidate.assessment.manifest
                      .required_facts_assessment
                  ]
                }
                。
              </p>
            ) : (
              <p>请先计算本轮依赖缺口；页面改动后须重新核对才能保存。</p>
            )}
            <label>
              计划保存理由
              <textarea
                maxLength={2000}
                value={reason}
                onChange={(e) => {
                  setReason(e.target.value);
                  setConfirmed(false);
                }}
              />
            </label>
            <label className="package-dependency-plans__choice">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              我确认保存以上核对结果与本轮明确选择，缺口仍按原状态保留
            </label>
            <button
              type="button"
              className="button primary"
              disabled={
                !props.candidate ||
                !reason.trim() ||
                !confirmed ||
                !record ||
                !saveAvailable ||
                busy
              }
              onClick={() => void save(false)}
            >
              {saving ? "正在保存计划…" : "明确保存本轮计划"}
            </button>
          </fieldset>
        )}
        {error != null && <ErrorNotice error={error} />}
        <div className="package-dependency-plans__actions">
          <button
            type="button"
            className="button secondary"
            disabled={busy || !readAvailable}
            onClick={() => void list()}
          >
            查看已保存计划
          </button>
          {record?.lastId && (
            <button
              type="button"
              className="text-button"
              disabled={busy || !readAvailable}
              onClick={() => void read(record.lastId!)}
            >
              重读上次保存的原计划
            </button>
          )}
        </div>
        {page && (
          <section aria-label="已保存计划目录">
            <p>这里是原保存记录；不会把某份历史自动设为本轮计划。</p>
            {!page.items.length && <p>此准备输入还没有已保存的依赖计划。</p>}
            <ol>
              {page.items.map((item) => (
                <li key={item.id}>
                  <time>{new Date(item.saved_at).toLocaleString("zh-CN")}</time>
                  <p>{item.reason}</p>
                  <p>
                    {states[item.required_facts_assessment]} · 要求{" "}
                    {item.requirement_count} 条 · 选用事实{" "}
                    {item.selected_fact_count} 条
                  </p>
                  <button
                    type="button"
                    className="text-button"
                    disabled={busy}
                    onClick={() => void read(item.id, item.digest)}
                  >
                    查看这份原计划
                  </button>
                </li>
              ))}
            </ol>
            {page.has_more && (
              <button
                type="button"
                className="button secondary"
                disabled={busy}
                onClick={() => void list(true)}
              >
                查看下一页计划
              </button>
            )}
          </section>
        )}
        {history && (
          <section
            className="package-dependency-plans__history"
            aria-label="原计划保存回执"
          >
            <div role="status">
              <p>已取得原计划保存回执。</p>
              <p>保存理由：{history.manifest.reason}</p>
              <p>
                {
                  states[
                    history.manifest.assessment.manifest
                      .required_facts_assessment
                  ]
                }
                。这是保存时的记录，当前事实资格和执行条件须另行核验。
              </p>
            </div>
            <p>
              保存时间：
              <time>
                {new Date(history.manifest.saved_at).toLocaleString("zh-CN")}
              </time>
              ；原要求 {history.manifest.assessment.manifest.requirement_count}{" "}
              条，选用事实{" "}
              {history.manifest.assessment.manifest.selected_fact_count} 条。
            </p>
            <details>
              <summary>查看原计划的标注与身份</summary>
              <ol>
                {history.manifest.assessment.manifest.requirements
                  .slice(0, historyVisible)
                  .map((row, n) => (
                    <li key={row.requirement_id}>
                      <strong>原要求 {n + 1}</strong>
                      <p>
                        {row.declaration?.reason ?? "此条未标注，保持未知。"}
                      </p>
                      <p>{states[row.fact_status]}</p>
                    </li>
                  ))}
              </ol>
              {history.manifest.assessment.manifest.requirement_count >
                historyVisible && (
                <button
                  type="button"
                  className="text-button"
                  onClick={() => setHistoryVisible((n) => n + 20)}
                >
                  继续查看原标注
                </button>
              )}
              <p>
                计划身份：<code>{history.manifest.id}</code>
              </p>
              <p>
                原计划摘要：<code>{history.digest}</code>
              </p>
              <p>
                原评估摘要：<code>{history.manifest.assessment.digest}</code>
              </p>
              <p>
                原政策摘要：
                <code>
                  {history.manifest.assessment.manifest.policy_digest}
                </code>
              </p>
            </details>
          </section>
        )}
      </div>
    </details>
  );
}
