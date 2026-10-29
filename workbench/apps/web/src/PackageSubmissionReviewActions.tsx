import { lazy, Suspense, useState } from "react";
import type { PackageSubmissionView } from "./contracts";
import { ErrorNotice } from "./components";
import type { PackageNavigationTarget } from "./packageNavigation";
import { PackageNextActions } from "./PackageNextActions";
import { packageReviewHistoricalOriginal } from "./packageReviewHistoricalRun";

const OriginalRunDetails = lazy(
  () => import("./PackageReviewOriginalRunDetails"),
);

type Props = {
  record: PackageSubmissionView;
  memberId: string;
  onOpenPackage?: (target: PackageNavigationTarget) => void;
  onOpenRules?: () => void;
  disabled?: boolean;
};
/** The host has verified the complete immutable submission binding before mounting. */
export function PackageSubmissionReviewActions(p: Props) {
  return (
    <SubmissionReviewActions
      key={`${p.record.id}:${p.record.package_binding.digest}`}
      {...p}
    />
  );
}
function SubmissionReviewActions({
  record,
  memberId,
  onOpenPackage,
  onOpenRules,
  disabled = false,
}: Props) {
  const [original, setOriginal] = useState(false);
  const m = record.package_binding.manifest,
    run = m.review_run,
    chosen = m.selection_request.review_run;
  if (!run || !chosen)
    return (
      <p className="small-note">
        本次实交未关联核查报告；关联核查的关键问题与建议数量未知。
      </p>
    );
  if (!run.result || chosen.result_digest === null)
    return (
      <p className="small-note">
        本次实交登记时未关联已完成报告；关联核查的关键问题与建议数量未知。
      </p>
    );
  if (
    !m.selection_request.inventory ||
    run.id !== chosen.id ||
    run.input_digest !== chosen.input_digest ||
    run.result.digest !== chosen.result_digest ||
    run.scope.bid_id !== record.bid_id ||
    run.scope.package_id !== m.subject.package_id ||
    run.scope.revision_id !== m.subject.revision_id ||
    run.scope.inventory_id !== m.selection_request.inventory.id
  )
    return (
      <ErrorNotice
        error={new Error("实交关联核查与固定选择不一致，未采用其他报告。")}
      />
    );
  if (!onOpenPackage) return null;
  return (
    <>
      <p className="small-note">
        仅核对这次实交明确关联的核查；登记时的检查与风险另列。
      </p>
      {disabled && (
        <p className="small-note">请先完成或收起当前登记，再定位关联核查。</p>
      )}
      <PackageNextActions
        run={run}
        heading="实交关联核查的当前下一步"
        disabled={disabled}
        onOpenOriginal={() => setOriginal(true)}
        onOpenPackage={onOpenPackage}
        onOpenRules={onOpenRules}
      />
      {original && (
        <Suspense fallback={<p role="status">正在打开实交关联的原核查…</p>}>
          <OriginalRunDetails
            memberId={memberId}
            reference={packageReviewHistoricalOriginal(run)}
            label="本次实交关联的原核查"
            onClose={() => setOriginal(false)}
          />
        </Suspense>
      )}
    </>
  );
}
