import { workspacePages } from "./workspaceTypes";
import type { WorkspacePage } from "./workspaceTypes";
import { supportsApi } from "./api";
import { taskTemplatesContractReady } from "./contracts";
import type { SettingsView } from "./contracts";
import { useResource } from "./useResource";

export function WorkspaceNavigation({
  bidId,
  page,
  onNavigate,
}: {
  bidId: string;
  page: WorkspacePage;
  onNavigate: (page: WorkspacePage) => void;
}) {
  const pricingAvailable = supportsApi("GET", `/bids/${bidId}/pricing-context`);
  const settings = useResource<SettingsView>(
    pricingAvailable ? `/bids/${bidId}/settings` : null,
  );
  return (
    <>
      <nav className="workspace-navigation" aria-label="项目工作区">
        {workspacePages
          .filter(
            ([key]) =>
              (key !== "tasks" ||
                (taskTemplatesContractReady &&
                  supportsApi("GET", `/bids/${bidId}/task-definitions`))) &&
              (key !== "pricing" ||
                (pricingAvailable &&
                  settings.data?.bid_id === bidId &&
                  settings.data.settings?.pricing === true &&
                  !settings.error)),
          )
          .map(([key, label]) => (
            <a
              key={key}
              href={`/bids/${bidId}/${key}`}
              aria-current={page === key ? "page" : undefined}
              onClick={(event) => {
                if (
                  !event.metaKey &&
                  !event.ctrlKey &&
                  !event.shiftKey &&
                  event.button === 0
                ) {
                  event.preventDefault();
                  onNavigate(key);
                }
              }}
            >
              {label}
            </a>
          ))}
      </nav>
      <p className="workspace-nav-hint">
        左右滑动可查看全部工作面，包括章节编制、实交与成绩。
      </p>
    </>
  );
}
