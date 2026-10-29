import { lazy, Suspense, useState } from "react";
import type { PackageReviewRunView } from "./contracts";
import { PackageNextActions } from "./PackageNextActions";
import { nextActionSelection } from "./packageNextActionsProtocol";
import type { WorkContextRunSelection } from "./workContextProtocol";

const ReviewDetails = lazy(() =>
  import("./WorkContextReviewDetails").then((module) => ({
    default: module.WorkContextReviewDetails,
  })),
);
type Props = {
  run: PackageReviewRunView;
  memberId: string;
  packageDigest: string;
  inventoryDigest: string;
  disabled: boolean;
};
/** Selected packets are checked by the registration selector; no registration is sent here. */
export function PackageSubmissionSelectedReviewActions(p: Props) {
  return (
    <SelectedReviewActions
      key={`${p.run.id}:${p.run.input_digest}:${p.run.result?.digest ?? "pending"}`}
      {...p}
    />
  );
}
function SelectedReviewActions({
  run,
  memberId,
  packageDigest,
  inventoryDigest,
  disabled,
}: Props) {
  const [original, setOriginal] = useState(false);
  if (!run.result)
    return (
      <p className="small-note">
        所选运行尚无完整报告；当前关键问题与建议数量未知。
      </p>
    );
  const selection: WorkContextRunSelection = {
    ...nextActionSelection(run)!,
    kind: "package_review_run",
    package_digest: packageDigest,
    inventory_digest: inventoryDigest,
  };
  return (
    <>
      <p className="small-note">
        仅核对本次明确选择的报告，不替代提交检查。需要前往规则或资料包时，请先收起登记表单。
      </p>
      <PackageNextActions
        run={run}
        heading="本次登记所选核查的下一步"
        disabled={disabled}
        onOpenOriginal={() => setOriginal(true)}
      />
      {original && (
        <Suspense fallback={<p role="status">正在打开所选核查原记录…</p>}>
          <ReviewDetails
            selection={selection}
            memberId={memberId}
            onClose={() => setOriginal(false)}
          />
        </Suspense>
      )}
    </>
  );
}
