import { useRef, useState } from "react";
import type {
  PackageNextActions as NextActions,
  PackageWorkContext,
  PackageReviewRunView,
} from "./contracts";
import { ErrorNotice } from "./components";
import type { PackageNavigationTarget } from "./packageNavigation";
import {
  checkedPackageNextActions,
  nextActionSelection,
} from "./packageNextActionsProtocol";
import { useResource } from "./useResource";
import "./PackageNextActions.css";

export function PackageNextActions({
  context,
  run,
  onOpenOriginal,
  onOpenPackage,
  onOpenRules,
  heading = "本轮主要下一步",
  disabled = false,
}: {
  onOpenOriginal: () => void;
  onOpenPackage: (target: PackageNavigationTarget) => void;
  onOpenRules?: () => void;
  heading?: string;
  disabled?: boolean;
} & (
  | { context: PackageWorkContext; run?: never }
  | { run: PackageReviewRunView; context?: never }
)) {
  const source = context ?? run;
  const selected = nextActionSelection(source);
  const path = selected
    ? `/bids/${selected.bid_id}/package-next-actions/${selected.run_id}?expected_input_digest=${selected.input_digest}`
    : null;
  const resource = useResource<unknown>(path);
  const [basisOpen, setBasisOpen] = useState(false);
  const basis = useRef<HTMLDetailsElement>(null);
  if (!selected) return null;
  let value: NextActions | undefined, invalid: unknown;
  if (!resource.error && !resource.loading && resource.data !== undefined) {
    try {
      value = checkedPackageNextActions(resource.data, source);
    } catch (error) {
      invalid = error;
    }
  }
  function open(key: string) {
    if (!selected) return;
    if (key === "inspect_changed_basis" || key === "inspect_unknown_basis") {
      setBasisOpen(true);
      queueMicrotask(() => basis.current?.querySelector("summary")?.focus());
    } else if (key === "confirm_critical_rules") onOpenRules?.();
    else if (key === "inspect_package_limitations")
      onOpenPackage({
        packageId: selected.package_id,
        revisionId: selected.revision_id,
        inventoryId: selected.inventory_id,
      });
    else onOpenOriginal();
  }
  return (
    <section className="panel package-next-actions" aria-label={heading}>
      <div className="section-heading">
        <h2>{heading}</h2>
        <button
          className="text-button"
          disabled={resource.loading}
          onClick={() => void resource.reload()}
        >
          重新核对下一步
        </button>
      </div>
      <ErrorNotice error={resource.error ?? invalid} />
      {!value && (
        <p className="small-note">
          {resource.loading
            ? "正在核对本轮输入与下一步…"
            : "下一步与剩余数量尚不能完整核验。"}
        </p>
      )}
      {value && (
        <>
          <button
            className="button primary"
            disabled={
              disabled ||
              (value.primary.key === "confirm_critical_rules" && !onOpenRules)
            }
            onClick={() => open(value.primary.key)}
          >
            {value.primary.title}
            {value.primary.item_count !== null &&
              `（${value.primary.item_count}项）`}
          </button>
          {value.basis_issues.length > 0 && (
            <details
              ref={basis}
              open={basisOpen}
              onToggle={(event) => setBasisOpen(event.currentTarget.open)}
            >
              <summary>本次下一步所依据的变化与缺口</summary>
              <ul>
                {value.basis_issues.map((issue) => (
                  <li key={issue.dimension}>{issue.message}</li>
                ))}
              </ul>
            </details>
          )}
          <details>
            <summary>
              剩余关键问题{" "}
              {value.remaining_critical_count === null
                ? "未知"
                : `${value.remaining_critical_count}项`}{" "}
              · 其他建议{" "}
              {value.remaining_suggestion_count === null
                ? "未知"
                : `${value.remaining_suggestion_count}项`}
            </summary>
            <p className="small-note">
              只统计已选核查范围，按要求去重；已由主要下一步定位的要求不重复计入。
            </p>
            {value.other_actions.length > 0 ? (
              <ul>
                {value.other_actions.map((action) => (
                  <li key={action.key}>
                    <button
                      className="button secondary"
                      disabled={
                        disabled ||
                        (action.key === "confirm_critical_rules" &&
                          !onOpenRules)
                      }
                      onClick={() => open(action.key)}
                    >
                      {action.title}（{action.item_count}项）
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="small-note">
                本次没有其他可定位的动作；不代表整包已经通过。
              </p>
            )}
          </details>
          {value.current_scope_counts === null &&
            value.historical_scope_counts !== null && (
              <p className="small-note">
                所选原报告的历史计数：关键问题{" "}
                {value.historical_scope_counts.critical}项，其他建议{" "}
                {value.historical_scope_counts.suggestions}
                项；当前数量保持未知。
              </p>
            )}
          <p className="small-note">
            这些操作仅定位记录与待核对内容，不会自动重试、确认或提交；整包完整性和正式技术分另行核验。
          </p>
        </>
      )}
    </section>
  );
}
