import { workspacePages } from "./workspaceTypes";
import type { WorkspacePage } from "./workspaceTypes";

export function WorkspaceNavigation({
  bidId,
  page,
  onNavigate,
}: {
  bidId: string;
  page: WorkspacePage;
  onNavigate: (page: WorkspacePage) => void;
}) {
  return (
    <>
      <nav className="workspace-navigation" aria-label="项目工作区">
        {workspacePages.map(([key, label]) => (
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
