import { useCallback } from "react";
import type { BidPackageHeadPage } from "./contracts";
import { ErrorNotice } from "./components";
import { ResourceState } from "./ResourceState";
import { useDirectory } from "./useDirectory";
import {
  validPackageDirectory,
  type PackageNavigationTarget,
} from "./packageNavigation";
import "./PackageNavigation.css";

export function PackageOverviewNextStep({
  bidId,
  onOpen,
  onMaterials,
}: {
  bidId: string;
  onOpen: (target: PackageNavigationTarget | null) => void;
  onMaterials: () => void;
}) {
  const validatePage = useCallback(
    (value: unknown) => validPackageDirectory(value, bidId, "bid"),
    [bidId],
  );
  const directory = useDirectory<BidPackageHeadPage>(
    `/bids/${bidId}/packages?kind=bid&limit=20`,
    validatePage,
  );
  const valid =
    directory.data &&
    validPackageDirectory(directory.data, bidId, "bid") &&
    directory.items.every((item) =>
      validPackageDirectory(
        { items: [item], has_more: false, next_cursor: null },
        bidId,
        "bid",
      ),
    );
  const known =
    !!valid && !directory.loading && !directory.error && !directory.moreError;
  const empty = known && !directory.hasMore && directory.items.length === 0;
  return (
    <section
      className="panel package-overview-next"
      aria-label="整包工作下一步"
    >
      <span className="eyebrow">整包工作下一步</span>
      <h2>{empty ? "建立本次投标的确切资料包" : "选择确切投标包继续核查"}</h2>
      <p>
        从资料包修订进入要求清单、范围声明、冻结输入与核查。原件解析、清单完整性、执行结果和实交资格分别核对。
      </p>
      <ResourceState
        {...directory}
        hasData={!!valid}
        onRetry={() => void directory.reload()}
      />
      {directory.data && !valid && (
        <p role="alert" className="notice error">
          资料包目录身份不一致，尚不能判断本项目有哪些资料包。
        </p>
      )}
      {!known && (
        <p className="small-note">
          目录尚未完整核对，资料包数量与可继续位置保持未知。
        </p>
      )}
      {known && !empty && (
        <p className="small-note">
          已读取 {directory.items.length} 个投标包
          {directory.hasMore ? "；还有未读取的目录页。" : "。"}
          以下修订是本次目录读取时记录的版本，点击后按确切身份核对。
        </p>
      )}
      {empty && (
        <p className="small-note">
          此目录已读完，尚未登记投标包。已有原件可以明确选入资料包；未登记不代表没有待处理要求。
        </p>
      )}
      {valid && (
        <ul className="package-overview-choices">
          {directory.items.map((item) => (
            <li key={item.id}>
              <span>
                投标包 {item.id.slice(0, 8)} · 修订 {item.revision}
              </span>
              <details className="small-note">
                <summary>版本与摘要</summary>
                <small className="digest">
                  {item.revision_id} · {item.digest}
                </small>
              </details>
              <button
                type="button"
                className="button secondary"
                disabled={!known}
                onClick={() =>
                  onOpen({
                    packageId: item.id,
                    revisionId: item.revision_id,
                    inventoryId: null,
                  })
                }
              >
                打开此包修订 {item.revision}
              </button>
            </li>
          ))}
        </ul>
      )}
      {directory.hasMore && (
        <button
          type="button"
          className="text-button"
          disabled={directory.moreBusy || !valid}
          onClick={() => void directory.loadMore()}
        >
          读取更多投标包
        </button>
      )}
      <ErrorNotice error={directory.moreError} />
      <div className="review-shortcuts">
        <button
          type="button"
          className="button primary"
          onClick={() => onOpen(null)}
        >
          打开整包核查工作面
        </button>
        <button
          type="button"
          className="button secondary"
          onClick={onMaterials}
        >
          上传与核对原件
        </button>
      </div>
      <p className="small-note">
        读取目录和打开链接不会创建清单、启动核查或产生模型费用。整包正式评分与标准提交资格仍须通过实际门禁。
      </p>
    </section>
  );
}
