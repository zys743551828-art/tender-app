import { workspacePages } from "./workspaceTypes";
import type { WorkspacePage } from "./workspaceTypes";
import { supportsApi } from "./api";
import { taskTemplatesContractReady } from "./contracts";
import type { SettingsView } from "./contracts";
import { useResource } from "./useResource";
import "./WorkspaceNavigation.css";

const primaryPages = new Set<WorkspacePage>([
  "overview",
  "materials",
  "packages",
  "authoring",
  "outcomes",
]);

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
  const pages = workspacePages.filter(
    ([key]) =>
      (key !== "work-context" ||
        supportsApi("GET", `/bids/${bidId}/work-contexts/choices`)) &&
      (key !== "tasks" ||
        (taskTemplatesContractReady &&
          supportsApi("GET", `/bids/${bidId}/task-definitions`))) &&
      (key !== "pricing" ||
        (pricingAvailable &&
          settings.data?.bid_id === bidId &&
          settings.data.settings?.pricing === true &&
          !settings.error)),
  );
  const secondaryPages = pages.filter(([key]) => !primaryPages.has(key));
  const currentSecondary = secondaryPages.find(([key]) => key === page);
  const [moreOpen, setMoreOpen] = useState(false);
  const moreRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  useEffect(() => {
    if (!moreOpen) return;
    const closeOutside = (event: PointerEvent) => {
      if (
        event.target instanceof Node &&
        !moreRef.current?.contains(event.target)
      )
        setMoreOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [moreOpen]);
  const navigate = (
    event: MouseEvent<HTMLAnchorElement>,
    target: WorkspacePage,
  ) => {
    if (
      !event.metaKey &&
      !event.ctrlKey &&
      !event.shiftKey &&
      !event.altKey &&
      event.button === 0
    ) {
      event.preventDefault();
      setMoreOpen(false);
      onNavigate(target);
    }
  };
  return (
    <nav
      className="workspace-navigation workspace-navigation--grouped"
      aria-label="项目工作区"
    >
      <label className="workspace-navigation__picker">
        <span>当前工作区</span>
        <select
          value={page}
          onChange={(event) => {
            const target = pages.find(([key]) => key === event.target.value);
            if (target) {
              setMoreOpen(false);
              onNavigate(target[0]);
            }
          }}
        >
          {!pages.some(([key]) => key === page) && (
            <option value={page} disabled>
              {workspacePages.find(([key]) => key === page)?.[1]}（暂不可用）
            </option>
          )}
          <optgroup label="主要工作">
            {pages
              .filter(([key]) => primaryPages.has(key))
              .map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
          </optgroup>
          <optgroup label="更多工作区">
            {secondaryPages.map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </optgroup>
        </select>
      </label>
      {pages
        .filter(([key]) => primaryPages.has(key))
        .map(([key, label]) => (
          <a
            key={key}
            className="workspace-navigation__primary"
            href={`/bids/${bidId}/${key}`}
            aria-current={page === key ? "page" : undefined}
            onClick={(event) => navigate(event, key)}
          >
            {label}
          </a>
        ))}
      <div
        className="workspace-navigation__more"
        ref={moreRef}
        onKeyDown={(event) => {
          if (event.key === "Escape" && moreOpen) {
            event.preventDefault();
            event.stopPropagation();
            setMoreOpen(false);
            buttonRef.current?.focus();
          }
        }}
      >
        <button
          type="button"
          ref={buttonRef}
          aria-expanded={moreOpen}
          aria-controls={panelId}
          className="workspace-navigation__more-button"
          data-current={!!currentSecondary}
          onClick={() => setMoreOpen(!moreOpen)}
        >
          {currentSecondary ? `更多 · ${currentSecondary[1]}` : "更多工作区"}
          <span aria-hidden="true">⌄</span>
        </button>
        <div
          id={panelId}
          hidden={!moreOpen}
          className="workspace-navigation__secondary"
        >
          {secondaryPages.map(([key, label]) => (
            <a
              key={key}
              href={`/bids/${bidId}/${key}`}
              aria-current={page === key ? "page" : undefined}
              onClick={(event) => navigate(event, key)}
            >
              {label}
            </a>
          ))}
        </div>
      </div>
    </nav>
  );
}
import { useEffect, useId, useRef, useState } from "react";
import type { MouseEvent } from "react";
