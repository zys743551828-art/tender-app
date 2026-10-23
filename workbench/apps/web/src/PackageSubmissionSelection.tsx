import { useEffect, useMemo, useState } from "react";
import type {
  BidPackageHeadPage,
  BidPackageRevisionSummaryPage,
  BidPackageStoredView,
  PackageCoverageAttemptView,
  PackageRequirementHistoryPage,
  PackageRequirementInventoryPage,
  PackageRequirementInventoryView,
  PackageReviewRunView,
  PackageSubmissionSelection as Selection,
  PackageSubmissionView,
} from "./contracts";
import { ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { ArtifactActions } from "./ArtifactActions";
import { useDirectory } from "./useDirectory";
import { useResource } from "./useResource";
import { useSubmissionRunTargets } from "./useSubmissionRunTargets";
import { PackageSubmissionSelectedReviewActions } from "./PackageSubmissionSelectedReviewActions";
import {
  packageSubmissionBase,
  submissionPackageMatches,
  submissionRunPath,
  validateSubmissionRun,
  type SubmissionRunTarget,
} from "./packageSubmissionProtocol";

export function PackageSubmissionSelection({
  bidId,
  memberId,
  disabled,
  initial,
  restoredSelection,
  onChange,
}: {
  bidId: string;
  memberId: string;
  disabled: boolean;
  initial: PackageSubmissionView | null;
  restoredSelection?: Selection;
  onChange: (value: Selection | null) => void;
}) {
  const seed =
    restoredSelection ?? initial?.package_binding.manifest.selection_request;
  const [packageId, setPackageId] = useState(seed?.package_id ?? "");
  const [revisionId, setRevisionId] = useState(seed?.revision_id ?? "");
  const [inventoryId, setInventoryId] = useState(seed?.inventory?.id ?? "");
  const [coverageId, setCoverageId] = useState(seed?.coverage?.id ?? "");
  const [runId, setRunId] = useState(seed?.review_run?.id ?? "");
  const [checkedRun, setCheckedRun] = useState<{
    target: SubmissionRunTarget;
    value: PackageReviewRunView;
  } | null>(null);
  const [runError, setRunError] = useState<unknown>(null);
  const packages = useDirectory<BidPackageHeadPage>(
    `/bids/${bidId}/packages?kind=bid&limit=20`,
  );
  const revisions = useDirectory<BidPackageRevisionSummaryPage>(
    packageId
      ? `/bids/${bidId}/packages/${packageId}/revisions?limit=20`
      : null,
  );
  const base =
    packageId && revisionId
      ? packageSubmissionBase(bidId, {
          package_id: packageId,
          revision_id: revisionId,
          package_digest: "",
          inventory: null,
          coverage: null,
          review_run: null,
        })
      : null;
  const target = useResource<BidPackageStoredView>(base);
  const targetReady =
    !!target.data &&
    !target.loading &&
    !target.error &&
    submissionPackageMatches(target.data, bidId, packageId, revisionId);
  const inventoryPath = base ? `${base}/requirement-inventories` : null;
  const inventories =
    useDirectory<PackageRequirementInventoryPage>(inventoryPath);
  const inventory = useResource<PackageRequirementInventoryView>(
    inventoryId && inventoryPath ? `${inventoryPath}/${inventoryId}` : null,
  );
  const coveragePath =
    inventoryId && inventoryPath
      ? `${inventoryPath}/${inventoryId}/coverage-attempts`
      : null;
  const attempts = useDirectory<PackageRequirementHistoryPage>(coveragePath);
  const coverage = useResource<PackageCoverageAttemptView>(
    coverageId && coveragePath ? `${coveragePath}/${coverageId}` : null,
  );
  const runs = useSubmissionRunTargets(bidId, !!inventoryId);
  const matchingRuns = runs.items.filter(
    (r) =>
      r.package_id === packageId &&
      r.revision_id === revisionId &&
      r.inventory_id === inventoryId,
  );
  const originalRun = initial?.package_binding.manifest.review_run;
  const initialRun = useMemo<SubmissionRunTarget | null>(
    () =>
      originalRun
        ? {
            id: originalRun.id,
            target_kind: "package_review_run",
            created_at: originalRun.created_at,
            input_digest: originalRun.input_digest,
            execution_input_id: originalRun.execution_input_id,
            state: originalRun.operation.state,
            package_id: originalRun.scope.package_id,
            revision_id: originalRun.scope.revision_id,
            inventory_id: originalRun.scope.inventory_id,
            frozen_input_id: originalRun.frozen_input_id,
            result_digest: originalRun.result?.digest ?? null,
          }
        : null,
    [originalRun],
  );
  const chosenRun =
    matchingRuns.find((r) => r.id === runId) ??
    (initialRun?.id === runId &&
    initialRun.package_id === packageId &&
    initialRun.revision_id === revisionId &&
    initialRun.inventory_id === inventoryId
      ? initialRun
      : null);
  const run = useResource<PackageReviewRunView>(
    chosenRun ? submissionRunPath(bidId, chosenRun) : null,
  );
  useEffect(() => {
    let live = true;
    setCheckedRun(null);
    setRunError(null);
    if (chosenRun && run.data && !run.loading && !run.error)
      void validateSubmissionRun(run.data, chosenRun, bidId)
        .then((value) => {
          if (live) setCheckedRun({ target: chosenRun, value });
        })
        .catch((failure) => {
          if (live) setRunError(failure);
        });
    return () => {
      live = false;
    };
  }, [chosenRun, run.data, run.loading, run.error, bidId]);
  const i = inventory.data,
    c = coverage.data;
  const inventoryReady =
    !inventoryId ||
    (!!i &&
      !inventory.loading &&
      !inventory.error &&
      i.manifest.id === inventoryId &&
      i.manifest.bid_id === bidId &&
      i.manifest.package_id === packageId &&
      i.manifest.target_revision_id === revisionId &&
      i.manifest.package_digest === target.data?.digest);
  const coverageReady =
    !coverageId ||
    (!!c &&
      !coverage.loading &&
      !coverage.error &&
      c.manifest.id === coverageId &&
      c.manifest.bid_id === bidId &&
      c.manifest.inventory_id === inventoryId &&
      c.manifest.inventory_digest === i?.digest &&
      c.manifest.package_digest === target.data?.digest);
  const runReady =
    !runId ||
    (!!chosenRun &&
      checkedRun?.target === chosenRun &&
      !run.loading &&
      !run.error &&
      !runError);
  const chosen = useMemo<Selection | null>(
    () =>
      targetReady && inventoryReady && coverageReady && runReady
        ? {
            package_id: packageId,
            revision_id: revisionId,
            package_digest: target.data!.digest,
            inventory:
              inventoryId && i ? { id: inventoryId, digest: i.digest } : null,
            coverage:
              coverageId && c ? { id: coverageId, digest: c.digest } : null,
            review_run:
              runId && checkedRun
                ? {
                    id: runId,
                    input_digest: checkedRun.value.input_digest,
                    result_digest: checkedRun.value.result?.digest ?? null,
                  }
                : null,
          }
        : null,
    [
      targetReady,
      inventoryReady,
      coverageReady,
      runReady,
      packageId,
      revisionId,
      target.data,
      inventoryId,
      i,
      coverageId,
      c,
      runId,
      checkedRun,
    ],
  );
  useEffect(() => {
    onChange(chosen);
  }, [chosen, onChange]);
  function clear() {
    onChange(null);
  }
  const seedsMatch =
    seed?.package_id === packageId && seed.revision_id === revisionId;
  return (
    <div className="package-submission-selection">
      <h3>1. 明确选择实际提交的整包修订</h3>
      <p className="small-note">
        以下选择互相独立。清单、范围声明和核查可以明确不关联；不会自动选择最新版本或用其他包替代。
      </p>
      <fieldset disabled={disabled}>
        <div className="package-submission-fields">
          <label>
            投标资料包
            <select
              value={packageId}
              onChange={(e) => {
                clear();
                setPackageId(e.target.value);
                setRevisionId("");
                setInventoryId("");
                setCoverageId("");
                setRunId("");
              }}
            >
              <option value="">选择确切投标包</option>
              {packageId && !packages.items.some((p) => p.id === packageId) && (
                <option value={packageId}>原记录投标包 {packageId}</option>
              )}
              {packages.items
                .filter((p) => p.bid_id === bidId && p.kind === "bid")
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    投标包 {p.id.slice(0, 8)} · 当前修订 {p.revision}
                  </option>
                ))}
            </select>
          </label>
          <label>
            固定包修订
            <select
              value={revisionId}
              disabled={!packageId}
              onChange={(e) => {
                clear();
                setRevisionId(e.target.value);
                setInventoryId("");
                setCoverageId("");
                setRunId("");
              }}
            >
              <option value="">明确选择一版修订</option>
              {revisionId &&
                !revisions.items.some((p) => p.id === revisionId) && (
                  <option value={revisionId}>原记录修订 {revisionId}</option>
                )}
              {revisions.items
                .filter((r) => r.package_id === packageId)
                .map((r) => (
                  <option key={r.id} value={r.id}>
                    修订 {r.revision} · {r.id.slice(0, 8)} ·{" "}
                    {r.digest.slice(0, 12)}
                  </option>
                ))}
            </select>
          </label>
        </div>
        <ResourceState
          {...packages}
          hasData={!!packages.data}
          onRetry={() => void packages.reload()}
        />
        <ErrorNotice error={packages.moreError} />
        {packages.hasMore && (
          <button
            type="button"
            className="text-button"
            disabled={packages.moreBusy}
            onClick={() => void packages.loadMore()}
          >
            加载更多投标包
          </button>
        )}
        {packageId && (
          <>
            <ResourceState
              {...revisions}
              hasData={!!revisions.data}
              onRetry={() => void revisions.reload()}
            />
            <ErrorNotice error={revisions.moreError} />
            {revisions.hasMore && (
              <button
                type="button"
                className="text-button"
                disabled={revisions.moreBusy}
                onClick={() => void revisions.loadMore()}
              >
                加载更多包修订
              </button>
            )}
          </>
        )}
        {base && (
          <ResourceState
            {...target}
            hasData={!!target.data}
            onRetry={() => void target.reload()}
          />
        )}
        {target.data && !target.loading && !targetReady && (
          <p className="notice error" role="alert">
            所选包修订身份无法核对，请重新读取；未采用其他项目或当前最新版。
          </p>
        )}
        {targetReady && (
          <div className="package-submission-selected">
            <p>
              <strong>已选修订 {target.data!.manifest.revision}</strong> ·{" "}
              {target.data!.manifest.members.length} 份原件 ·{" "}
              {target.data!.identity.bidder_name} ·{" "}
              {target.data!.identity.engineering_title}
            </p>
            <p className="digest">包摘要 {target.data!.digest}</p>
            <details>
              <summary>核对整包成员与逻辑范围</summary>
              <ul>
                {target.data!.manifest.members.map((m) => (
                  <li key={m.member_id}>
                    <strong>{m.member_id}</strong> · 用途{" "}
                    {m.purposes.join("、")} · 原件{" "}
                    <span className="digest">{m.document_version_id}</span>
                    <p className="digest">SHA256 {m.file_digest}</p>
                    <p>
                      {m.parse.status === "frozen"
                        ? "已固定解析版本"
                        : "解析身份未冻结"}
                      ；
                      {m.parts.length
                        ? m.parts
                            .map(
                              (p) =>
                                `${p.category}：物理页 ${p.first_page}—${p.last_page}`,
                            )
                            .join("；")
                        : "未声明逻辑范围"}
                    </p>
                    <ArtifactActions
                      bidId={bidId}
                      documentId={m.document_version_id}
                      isPdf={false}
                      downloadLabel={`下载原件 ${m.member_id} 核对`}
                    />
                  </li>
                ))}
              </ul>
            </details>
          </div>
        )}
        {targetReady && (
          <>
            <label>
              关联需求清单
              <select
                value={inventoryId}
                onChange={(e) => {
                  clear();
                  setInventoryId(e.target.value);
                  setCoverageId("");
                  setRunId("");
                }}
              >
                <option value="">不关联清单 · 完整性仍未证明</option>
                {inventoryId &&
                  !inventories.items.some((v) => v.id === inventoryId) &&
                  seedsMatch && (
                    <option value={inventoryId}>
                      原记录清单 {inventoryId}
                    </option>
                  )}
                {inventories.items.map((v) => (
                  <option key={v.id} value={v.id}>
                    清单 {v.id.slice(0, 8)} · {v.digest.slice(0, 12)}
                  </option>
                ))}
              </select>
            </label>
            <ResourceState
              {...inventories}
              hasData={!!inventories.data}
              onRetry={() => void inventories.reload()}
            />
            <ErrorNotice error={inventories.moreError} />
            {inventories.hasMore && (
              <button
                type="button"
                className="text-button"
                disabled={inventories.moreBusy}
                onClick={() => void inventories.loadMore()}
              >
                加载更多清单
              </button>
            )}
            {inventoryId && (
              <>
                <ResourceState
                  {...inventory}
                  hasData={!!inventory.data}
                  onRetry={() => void inventory.reload()}
                />
                {!inventory.loading && inventory.data && !inventoryReady && (
                  <p role="alert" className="notice error">
                    需求清单与所选包修订不一致。
                  </p>
                )}
                <label>
                  关联人工范围声明
                  <select
                    value={coverageId}
                    disabled={!inventoryReady}
                    onChange={(e) => {
                      clear();
                      setCoverageId(e.target.value);
                    }}
                  >
                    <option value="">不关联范围声明</option>
                    {coverageId &&
                      !attempts.items.some((v) => v.id === coverageId) &&
                      seedsMatch && (
                        <option value={coverageId}>
                          原记录范围声明 {coverageId}
                        </option>
                      )}
                    {attempts.items.map((v) => (
                      <option key={v.id} value={v.id}>
                        范围声明 {v.id.slice(0, 8)} · {v.digest.slice(0, 12)}
                      </option>
                    ))}
                  </select>
                </label>
                <ResourceState
                  {...attempts}
                  hasData={!!attempts.data}
                  onRetry={() => void attempts.reload()}
                />
                <ErrorNotice error={attempts.moreError} />
                {attempts.hasMore && (
                  <button
                    type="button"
                    className="text-button"
                    disabled={attempts.moreBusy}
                    onClick={() => void attempts.loadMore()}
                  >
                    加载更多范围声明
                  </button>
                )}
                {coverageId && (
                  <>
                    <ResourceState
                      {...coverage}
                      hasData={!!coverage.data}
                      onRetry={() => void coverage.reload()}
                    />
                    {!coverage.loading && coverage.data && !coverageReady && (
                      <p role="alert" className="notice error">
                        范围声明不属于所选清单或包修订。
                      </p>
                    )}
                  </>
                )}
                <label>
                  关联整包核查
                  <select
                    value={runId}
                    disabled={!inventoryReady}
                    onChange={(e) => {
                      clear();
                      setRunId(e.target.value);
                    }}
                  >
                    <option value="">不关联任何核查运行</option>
                    {initialRun &&
                      chosenRun === initialRun &&
                      !matchingRuns.some((v) => v.id === runId) && (
                        <option value={runId}>
                          原记录核查 {runId.slice(0, 8)}
                        </option>
                      )}
                    {matchingRuns.map((v) => (
                      <option key={v.id} value={v.id}>
                        核查 {v.id.slice(0, 8)} · {v.state} ·{" "}
                        {v.result_digest ? "已有结果" : "尚无结果"}
                      </option>
                    ))}
                  </select>
                </label>
                <ResourceState
                  {...runs.first}
                  hasData={runs.ready}
                  onRetry={() => void runs.first.reload()}
                />
                <ErrorNotice error={runs.invalid ?? runs.error} />
                {runs.hasMore && (
                  <button
                    type="button"
                    className="text-button"
                    disabled={runs.busy}
                    onClick={() => void runs.more()}
                  >
                    加载更多核查运行
                  </button>
                )}
                {runs.ready && !matchingRuns.length && (
                  <p className="small-note">
                    {runs.hasMore
                      ? "已读取页面中尚无匹配运行，可继续加载；也可明确不关联。"
                      : "已读取的完整目录中没有属于本清单的核查运行。"}
                  </p>
                )}
                {runId && (
                  <>
                    <ResourceState
                      {...run}
                      hasData={!!run.data}
                      onRetry={() => void run.reload()}
                    />
                    <ErrorNotice error={runError} />
                    {checkedRun && chosenRun === checkedRun.target && (
                      <details>
                        <summary>核对核查的固定输入链</summary>
                        <dl>
                          <dt>核查运行</dt>
                          <dd className="digest">{runId}</dd>
                          <dt>冻结输入</dt>
                          <dd className="digest">
                            {checkedRun.value.frozen_input_id}
                          </dd>
                          <dt>执行准备</dt>
                          <dd className="digest">
                            {checkedRun.value.execution_input_id}
                          </dd>
                          <dt>输入摘要</dt>
                          <dd className="digest">
                            {checkedRun.value.input_digest}
                          </dd>
                          <dt>结果摘要</dt>
                          <dd className="digest">
                            {checkedRun.value.result?.digest ??
                              "尚无结果，不推断已完成"}
                          </dd>
                        </dl>
                      </details>
                    )}
                  </>
                )}
                <p className="small-note">
                  运行目录用于发现已有核查，不授予提交资格。范围声明必须与该次核查的冻结选择一致，读取提交检查时会再核对。
                </p>
              </>
            )}
          </>
        )}
      </fieldset>
      {chosen?.review_run &&
        chosen.inventory &&
        checkedRun &&
        chosenRun === checkedRun.target && (
          <PackageSubmissionSelectedReviewActions
            run={checkedRun.value}
            memberId={memberId}
            packageDigest={chosen.package_digest}
            inventoryDigest={chosen.inventory.digest}
            disabled={disabled}
          />
        )}
      {chosen && (
        <p className="small-note" role="status">
          本次固定选择：{chosen.inventory ? "已关联需求清单" : "不关联需求清单"}
          ；{chosen.coverage ? "已关联范围声明" : "不关联范围声明"}；
          {chosen.review_run ? "已关联确切核查" : "不关联核查运行"}。
        </p>
      )}
    </div>
  );
}
