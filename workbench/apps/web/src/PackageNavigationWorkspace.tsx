import { BidPackages } from "./BidPackages";
import {
  parsePackageLocation,
  type PackageNavigationTarget,
} from "./packageNavigation";
import "./PackageNavigation.css";
import { PackageReviewActionNavigation } from "./packageReviewActionNavigation";

export function PackageNavigationWorkspace({
  bidId,
  memberId,
  route,
  disabled,
  onLocation,
  onReset,
  onOpenRules,
}: {
  bidId: string;
  memberId: string;
  route: string;
  disabled: boolean;
  onLocation: (
    target: PackageNavigationTarget | null,
    replace?: boolean,
  ) => void;
  onReset: () => void;
  onOpenRules?: () => void;
}) {
  const location = parsePackageLocation(route);
  return (
    <div className="package-navigation-workspace">
      <section className="panel package-navigation-intro">
        <h2>整包核查</h2>
        <p>
          按明确包修订与清单继续工作，链接固定到所选身份。切换修订时重新选择清单及范围；已有核查与实交记录继续保留。
        </p>
        <p className="small-note">
          这里可进行有据规则更正、范围声明、冻结输入、核查与报告。完整性未知或执行成功都不等于正式评分、合规或标准提交资格。
        </p>
      </section>
      {!location.ok ? (
        <section className="panel">
          <p role="alert" className="notice error">
            {location.message}
          </p>
          <button type="button" className="button secondary" onClick={onReset}>
            明确返回资料包目录重新选择
          </button>
        </section>
      ) : (
        <PackageReviewActionNavigation.Provider
          value={{ bidId, onOpenPackage: onLocation, onOpenRules }}
        >
          <BidPackages
            bidId={bidId}
            memberId={memberId}
            disabled={disabled}
            navigation={{ target: location.target, onLocation }}
          />
        </PackageReviewActionNavigation.Provider>
      )}
    </div>
  );
}
