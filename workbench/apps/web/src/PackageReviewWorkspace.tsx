import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { ApiError, api, supportsApi } from "./api";
import type {
  PackageDependencyPlanView,
  PackageReviewRunPage,
  PackageReviewRunView,
} from "./contracts";
import { ErrorNotice } from "./components";
import { dependencyPlanScope } from "./dependencyPlanProtocol";
import { executionId, recordObject } from "./executionInputValidation";
import type { DependencyProps } from "./inputDependencyProtocol";
import PackageInputDependencyWorkspace from "./PackageInputDependencyWorkspace";
import PackageReviewProgress from "./PackageReviewProgress";
import {
  packageReviewPath,
  validatePackageReviewPage,
  validatePackageReviewRun,
} from "./packageReviewProtocol";
import type { PendingPackageReviewRun } from "./packageReviewProtocol";
import {
  loadPackageReviewRecord,
  storePackageReviewRecord,
  definitelyRejectedPackageReview,
} from "./packageReviewRecovery";
import type { PackageReviewRecord } from "./packageReviewRecovery";
import { packageReviewHistoricalSummary } from "./packageReviewHistoricalRun";
import type { PackageReviewHistoricalReference } from "./packageReviewHistoricalRun";
import "./packageReview.css";
import { usePackageScopeGuard } from "./packageScopeGuard";
import PackageTaskTemplate from "./PackageTaskTemplate";

const PackageReviewOriginalRunDetails = lazy(
  () => import("./PackageReviewOriginalRunDetails"),
);

type Props = DependencyProps & { onRequestRerun?: () => void };
// package-review/1 is bounded to four batches of 100 requirements.
const reviewRequirementLimit = 400;
export default function PackageReviewWorkspace(props: Props) {
  return (
    <Workspace key={JSON.stringify(dependencyPlanScope(props))} {...props} />
  );
}
function Workspace(props: Props) {
  const [loaded] = useState(() => {
    try {
      return { record: loadPackageReviewRecord(props), error: null };
    } catch (error) {
      return { record: null, error };
    }
  });
  const [record, setRecord] = useState<PackageReviewRecord | null>(
    loaded.record,
  );
  const recordRef = useRef(record),
    active = useRef(false),
    writing = useRef(false),
    ticket = useRef(0);
  const [selected, setSelected] = useState<PackageDependencyPlanView | null>(
    null,
  );
  const [run, setRun] = useState<PackageReviewRunView | null>(null);
  const [existing, setExisting] =
      useState<PackageReviewHistoricalReference | null>(null),
    [showExisting, setShowExisting] = useState(false);
  const [page, setPage] = useState<PackageReviewRunPage | null>(null);
  const [historyId, setHistoryId] = useState(loaded.record?.lastId ?? "");
  const [busy, setBusy] = useState(false),
    [launching, setLaunching] = useState(false);
  const [error, setError] = useState<unknown>(loaded.error);
  const path = packageReviewPath(props),
    available = supportsApi("POST", path),
    readable = supportsApi("GET", path);
  usePackageScopeGuard(`review:${JSON.stringify(dependencyPlanScope(props))}`, {
    busy: launching,
    pending: !!record?.pending || !!loaded.error,
  });
  const seenCursors = useRef(new Set<string>());
  useEffect(() => {
    active.current = true;
    const requests = ticket;
    return () => {
      active.current = false;
      requests.current++;
    };
  }, []);
  function persist(next: PackageReviewRecord) {
    storePackageReviewRecord(next);
    recordRef.current = next;
    setRecord(next);
  }
  async function launch(recover: boolean) {
    const current = recordRef.current;
    if (!active.current || writing.current || busy || !available || !current)
      return;
    const pending: PendingPackageReviewRun | null = recover
      ? current.pending
      : !current.pending &&
          selected &&
          selected.manifest.assessment.manifest.requirement_count <=
            reviewRequirementLimit &&
          run?.dependency_plan_id !== selected.manifest.id
        ? {
            key: crypto.randomUUID(),
            body: {
              execution_input_digest: props.prepared.digest,
              dependency_plan_id: selected.manifest.id,
              dependency_plan_digest: selected.digest,
            },
          }
        : null;
    if (!pending) return;
    writing.current = true;
    const request = ++ticket.current;
    setBusy(true);
    setLaunching(true);
    setError(null);
    setExisting(null);
    setShowExisting(false);
    try {
      persist({ ...current, pending });
      let response: unknown;
      try {
        ({ data: response } = await api<unknown>(path, {
          method: "POST",
          body: pending.body,
          key: pending.key,
        }));
      } catch (failure) {
        if (
          active.current &&
          ticket.current === request &&
          definitelyRejectedPackageReview(failure)
        ) {
          if (
            failure instanceof ApiError &&
            failure.code === "PACKAGE_REVIEW_ALREADY_EXISTS" &&
            recordObject(failure.details)
          )
            setExisting(
              packageReviewHistoricalSummary(
                failure.details.existing_run,
                props.scope.bidId,
              ),
            );
          persist({ ...current, pending: null });
          setSelected(null);
        }
        throw failure;
      }
      const received = await validatePackageReviewRun(response, props, pending);
      if (!active.current || ticket.current !== request) return;
      persist({ ...current, pending: null, lastId: received.id });
      setHistoryId(received.id);
      setRun(received);
      setPage(null);
    } catch (failure) {
      if (active.current && ticket.current === request) setError(failure);
    } finally {
      writing.current = false;
      if (active.current && ticket.current === request) {
        setBusy(false);
        setLaunching(false);
      }
    }
  }
  async function list(next = false) {
    if (
      !active.current ||
      busy ||
      writing.current ||
      !readable ||
      (next && !page?.next_cursor)
    )
      return;
    const request = ++ticket.current;
    const cursor = next ? page!.next_cursor! : null;
    setBusy(true);
    setError(null);
    try {
      if (cursor && seenCursors.current.has(cursor))
        throw new Error("核查目录返回了已读取的游标，未重复采用旧页。");
      const { data } = await api<unknown>(
        `${path}?limit=10${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
      );
      const received = await validatePackageReviewPage(data, props, 10);
      if (
        cursor &&
        (received.next_cursor === cursor ||
          received.items.some((item) =>
            page?.items.some((old) => old.id === item.id),
          ))
      )
        throw new Error("核查目录未沿原游标读取下一页，未采用重复历史。");
      if (!active.current || ticket.current !== request) return;
      if (!next) seenCursors.current.clear();
      else seenCursors.current.add(cursor!);
      setPage(received);
    } catch (failure) {
      if (active.current && ticket.current === request) setError(failure);
    } finally {
      if (active.current && ticket.current === request) setBusy(false);
    }
  }
  async function read(id: string) {
    if (
      !active.current ||
      busy ||
      writing.current ||
      !executionId(id) ||
      !readable
    )
      return;
    const request = ++ticket.current;
    setBusy(true);
    setError(null);
    try {
      const { data } = await api<unknown>(`${path}/${id}`);
      const received = await validatePackageReviewRun(data, props, id);
      if (!active.current || ticket.current !== request) return;
      const current = recordRef.current;
      if (current) persist({ ...current, lastId: id });
      setHistoryId(id);
      setRun(received);
    } catch (failure) {
      if (active.current && ticket.current === request) setError(failure);
    } finally {
      if (active.current && ticket.current === request) setBusy(false);
    }
  }
  const pending = record?.pending;
  const alreadyAccepted =
    !!selected && run?.dependency_plan_id === selected.manifest.id;
  const overLimit =
    !!selected &&
    selected.manifest.assessment.manifest.requirement_count >
      reviewRequirementLimit;
  return (
    <section className="package-review" aria-label="整包范围核查工作区">
      <PackageInputDependencyWorkspace
        {...props}
        onSelectPlan={setSelected}
        selectedPlanId={selected?.manifest.id ?? null}
      />
      <section className="package-review__launch" aria-label="启动整包范围核查">
        <div className="package-review__heading">
          <div>
            <p className="package-review__eyebrow">依赖计划 → 整包范围核查</p>
            <h4>选用计划后，开始核查</h4>
          </div>
          <span className="package-review__boundary-tag">仅核查已声明范围</span>
        </div>
        <p>
          核查绑定当前准备输入和所选计划。结果逐条列出已核查内容、引用与无法判定项；要求清单的语义完整性和真实效果尚未测定，不形成正式评分或投递资格。
        </p>
        {!available && (
          <p className="package-review__notice">
            当前服务尚未提供整包范围核查启动接口。
          </p>
        )}
        {!record && (
          <p className="package-review__notice">
            本机恢复记录无法核验，新启动已暂停；仍可查看此准备输入的服务器历史。
          </p>
        )}
        {selected ? (
          <div className="package-review__selected">
            <strong>已选用计划</strong>
            <p>{selected.manifest.reason}</p>
            <p className="muted">
              {new Date(selected.manifest.saved_at).toLocaleString()} ·{" "}
              {selected.manifest.assessment.manifest.requirement_count} 条要求 ·{" "}
              {selected.manifest.assessment.manifest.selected_fact_count}{" "}
              项选用事实
            </p>
            <details>
              <summary>核对所选计划身份</summary>
              <p>
                计划编号：<code>{selected.manifest.id}</code>
              </p>
              <p>
                计划摘要：<code>{selected.digest}</code>
              </p>
            </details>
          </div>
        ) : (
          <p className="package-review__empty">
            先在上方“保存与查阅依赖计划”中打开一份计划，再点击“选择这份计划继续核查”。读取历史不会自动启动。
          </p>
        )}
        {selected && <PackageTaskTemplate {...props} plan={selected} />}
        {overLimit && (
          <p className="package-review__notice">
            本轮核查最多 {reviewRequirementLimit} 条要求；当前{" "}
            {selected!.manifest.assessment.manifest.requirement_count}{" "}
            条，尚未启动。计划和草稿保留。
          </p>
        )}
        {pending ? (
          <div className="package-review__notice" role="status">
            <strong>原核查请求的回执尚未确认</strong>
            <p>
              恢复将使用原计划、原准备输入和同一幂等键。当前页面的新选择不会替换该请求。
            </p>
            <details>
              <summary>待恢复的计划身份</summary>
              <p>
                原计划编号：<code>{pending.body.dependency_plan_id}</code>
              </p>
              <p>
                原计划摘要：<code>{pending.body.dependency_plan_digest}</code>
              </p>
            </details>
            <button
              type="button"
              className="button primary"
              disabled={busy || !available}
              onClick={() => void launch(true)}
            >
              {launching ? "正在核对原回执…" : "恢复原核查请求"}
            </button>
          </div>
        ) : (
          <button
            type="button"
            className="button primary"
            disabled={
              busy ||
              !available ||
              !record ||
              !selected ||
              overLimit ||
              alreadyAccepted
            }
            onClick={() => void launch(false)}
          >
            {launching ? "正在确认核查受理…" : "开始整包范围核查"}
          </button>
        )}
        {alreadyAccepted && !pending && (
          <p className="muted">
            这份计划的核查已受理。同一输入会读回原记录；再次执行需要明确准备复检。
          </p>
        )}
        {error != null && <ErrorNotice error={error} />}
        {existing && (
          <div className="package-review__notice">
            <p>
              相同内容已有核查记录，本次未启动新任务。可按原冻结输入和执行准备查看原核查；再次执行需明确准备复检并填写原因。
            </p>
            <button
              type="button"
              className="button secondary"
              onClick={() => setShowExisting(true)}
            >
              查看已存在的原核查
            </button>
          </div>
        )}
      </section>
      {existing && showExisting && (
        <Suspense fallback={<p role="status">正在打开原核查详情…</p>}>
          <PackageReviewOriginalRunDetails
            memberId={props.scope.memberId}
            reference={existing}
            label="已存在的原核查详情"
            onClose={() => setShowExisting(false)}
          />
        </Suspense>
      )}
      {run && (
        <PackageReviewProgress
          key={`${run.id}:${run.input_digest}`}
          {...props}
          run={run}
          onChange={setRun}
        />
      )}
      <details className="package-review__history">
        <summary>此准备输入的核查历史与恢复</summary>
        <p>
          历史只读，不会自动选用其计划或创建任务。已受理任务可在关闭页面后继续运行。
        </p>
        <div className="package-review__actions">
          <button
            type="button"
            className="button secondary"
            disabled={busy || !readable}
            onClick={() => void list()}
          >
            读取核查历史
          </button>
          {page?.has_more && (
            <button
              type="button"
              className="button secondary"
              disabled={busy}
              onClick={() => void list(true)}
            >
              下一页核查历史
            </button>
          )}
        </div>
        {page && !page.items.length && <p>此准备输入尚无已受理的核查记录。</p>}
        {page && page.items.length > 0 && (
          <ul className="package-review__history-list">
            {page.items.map((item) => (
              <li key={item.id}>
                <div>
                  <strong>{new Date(item.created_at).toLocaleString()}</strong>
                  <p className="muted">
                    核查编号：<code>{item.id}</code>
                  </p>
                </div>
                <button
                  type="button"
                  className="button secondary"
                  disabled={busy}
                  onClick={() => void read(item.id)}
                >
                  查看这次核查
                </button>
              </li>
            ))}
          </ul>
        )}
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void read(historyId.trim());
          }}
          className="package-review__lookup"
        >
          <label>
            原核查编号
            <input
              value={historyId}
              onChange={(event) => setHistoryId(event.target.value)}
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          <button
            className="button secondary"
            disabled={busy || !readable || !executionId(historyId.trim())}
          >
            重读原核查
          </button>
        </form>
        {busy && !launching && <p role="status">正在核对核查历史…</p>}
      </details>
    </section>
  );
}
