import { useEffect, useState } from "react";
import type { PackageWorkContext } from "./contracts";
import { ErrorNotice, LoadingSkeleton } from "./components";
import { PackageNextActions } from "./PackageNextActions";
import type { PackageNavigationTarget } from "./packageNavigation";
import { useResource } from "./useResource";
import { WorkContextChoices } from "./WorkContextChoices";
import {
  workContextPath,
  type WorkContextPosition,
  type WorkContextTarget,
} from "./workContextNavigation";
import { validatePackageWorkContext } from "./workContextProtocol";
import "./ProjectSelectedReviewSummary.css";

type Props = {
  bidId: string;
  memberId: string;
  onOpenRecord: (position: WorkContextPosition) => void;
  onOpenPackage: (target: PackageNavigationTarget) => void;
  onOpenRules: () => void;
};

export function ProjectSelectedReviewSummary(props: Props) {
  return <ProjectReview key={`${props.memberId}:${props.bidId}`} {...props} />;
}

function ProjectReview(props: Props) {
  const [choosing, setChoosing] = useState(false);
  const [selected, setSelected] = useState<WorkContextTarget | null>(null);
  return (
    <section
      className="panel project-review-summary"
      aria-label="所选整包核查概况"
    >
      <div className="section-heading">
        <div>
          <h2>核查风险与下一步</h2>
          <p className="muted">
            选择一轮整包核查，查看对应范围的问题与处理入口。
          </p>
        </div>
        <button
          type="button"
          className="button secondary"
          aria-expanded={choosing}
          onClick={() => setChoosing((value) => !value)}
        >
          {choosing
            ? "收起核查目录"
            : selected
              ? "更换所选核查"
              : "选择一轮核查"}
        </button>
      </div>
      <div className="project-review-summary__content">
        {choosing && (
          <WorkContextChoices
            bidId={props.bidId}
            kind="package_review_run"
            selected={selected}
            onSelect={(target) => {
              if (target.kind !== "package_review_run") return;
              setSelected(target);
              setChoosing(false);
            }}
          />
        )}
        {selected ? (
          <SelectedReview
            key={`${selected.id}:${selected.selectionDigest}`}
            {...props}
            target={selected}
            onClear={() => setSelected(null)}
          />
        ) : (
          <p className="small-note">
            尚未选择核查，风险数量与预测分数保持未知。资料包数量不能代替核查结果。
          </p>
        )}
      </div>
    </section>
  );
}

function SelectedReview({
  target,
  onClear,
  ...props
}: Props & {
  target: WorkContextTarget;
  onClear: () => void;
}) {
  const resource = useResource<unknown>(workContextPath(props.bidId, target));
  const [verified, setVerified] = useState<{
    source: unknown;
    context?: PackageWorkContext;
    error?: unknown;
  } | null>(null);
  useEffect(() => {
    let active = true;
    if (!resource.loading && !resource.error && resource.data !== undefined) {
      const source = resource.data;
      void validatePackageWorkContext(source, props.bidId, target).then(
        (context) => {
          if (active) setVerified({ source, context });
        },
        (error: unknown) => {
          if (active) setVerified({ source, error });
        },
      );
    }
    return () => {
      active = false;
    };
  }, [props.bidId, target, resource.data, resource.loading, resource.error]);
  const current =
    !resource.loading && !resource.error && verified?.source === resource.data
      ? verified
      : null;
  const context = current?.context;
  const error = resource.error ?? current?.error;
  const open = () =>
    props.onOpenRecord({ stage: "package_review_run", selected: target });
  return (
    <div>
      <div className="section-heading project-review-summary__selection-heading">
        <h3>所选核查 {target.id.slice(0, 8)}</h3>
        <button type="button" className="text-button" onClick={onClear}>
          取消选择
        </button>
      </div>
      {resource.unavailable && (
        <p className="notice warning">当前服务尚未提供完整核查记录读取能力。</p>
      )}
      {!resource.unavailable && !context && error == null && (
        <LoadingSkeleton text="正在核对所选核查的完整身份…" rows={2} />
      )}
      <ErrorNotice error={error} onRetry={() => void resource.reload()} />
      {context && (
        <>
          <p className="small-note">
            以下只对应明确选择的这轮核查。依据变化时，原记录保留，当前风险数量重新核对。
          </p>
          <PackageNextActions
            context={context}
            heading="所选核查的主要下一步"
            onOpenOriginal={open}
            onOpenPackage={props.onOpenPackage}
            onOpenRules={props.onOpenRules}
          />
          <button type="button" className="button secondary" onClick={open}>
            查看所选核查与原报告
          </button>
          <p className="small-note">技术预测分数尚未在此摘要中评估。</p>
        </>
      )}
    </div>
  );
}
