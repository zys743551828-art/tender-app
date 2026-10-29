import { executionId, recordObject } from "./executionInputValidation";
import {
  packageLocation,
  parsePackageLocation,
  type PackageNavigationTarget,
} from "./packageNavigation";
import { workspacePages, type WorkspacePage } from "./workspaceTypes";
import {
  parseWorkContextLocation,
  workContextLocation,
  type WorkContextPosition,
} from "./workContextNavigation";

export type WorkspacePosition = {
  version: "workspace-position/1";
  memberId: string;
  bidId: string;
  page: WorkspacePage;
  reviewId: string | null;
  draftId: string | null;
  packageTarget: PackageNavigationTarget | null;
  workContext: WorkContextPosition | null;
};

const positionKey = (memberId: string, bidId: string) =>
  `tender:workspace-position:${memberId}:${bidId}`;

export function workspacePositionFromRoute(
  memberId: string,
  bidId: string,
  route: string,
): WorkspacePosition | null {
  if (!executionId(memberId) || !executionId(bidId) || route.includes("#"))
    return null;
  const [pathname, ...search] = route.split("?");
  if (search.length > 1) return null;
  const page = workspacePages.find(
    ([value]) => pathname === `/bids/${bidId}/${value}`,
  )?.[0];
  if (!page) return null;
  const position: WorkspacePosition = {
    version: "workspace-position/1",
    memberId,
    bidId,
    page,
    reviewId: null,
    draftId: null,
    packageTarget: null,
    workContext: null,
  };
  if (page === "work-context") {
    const parsed = parseWorkContextLocation(bidId, route);
    return parsed.ok ? { ...position, workContext: parsed.position } : null;
  }
  if (page === "packages") {
    const parsed = parsePackageLocation(route);
    return parsed.ok ? { ...position, packageTarget: parsed.target } : null;
  }
  const query = new URLSearchParams(search[0] ?? "");
  const allowed =
    page === "authoring"
      ? ["draft"]
      : page === "review" || page === "matrix"
        ? ["review"]
        : [];
  if (
    [...query.keys()].some(
      (key) => !allowed.includes(key) || query.getAll(key).length !== 1,
    )
  )
    return null;
  for (const key of ["review", "draft"] as const) {
    const value = query.get(key);
    if (value !== null && !executionId(value)) return null;
    position[key === "review" ? "reviewId" : "draftId"] = value;
  }
  return position;
}

export function saveWorkspacePosition(
  memberId: string,
  bidId: string,
  route: string,
) {
  const position = workspacePositionFromRoute(memberId, bidId, route);
  if (!position) return;
  try {
    localStorage.setItem(
      positionKey(memberId, bidId),
      JSON.stringify(position),
    );
  } catch {
    /* Browser preferences cannot block navigation or establish business state. */
  }
}

export function loadWorkspacePosition(
  memberId: string,
  bidId: string,
): WorkspacePosition | null {
  if (!executionId(memberId) || !executionId(bidId)) return null;
  try {
    const text = localStorage.getItem(positionKey(memberId, bidId));
    if (!text) return null;
    const value: unknown = JSON.parse(text);
    if (
      !recordObject(value) ||
      Object.keys(value).sort().join(",") !==
        "bidId,draftId,memberId,packageTarget,page,reviewId,version,workContext" ||
      value.version !== "workspace-position/1" ||
      value.memberId !== memberId ||
      value.bidId !== bidId ||
      !workspacePages.some(([page]) => page === value.page)
    )
      return null;
    let route = `/bids/${bidId}/${String(value.page)}`;
    if (value.page === "work-context") {
      if (
        value.reviewId !== null ||
        value.draftId !== null ||
        value.packageTarget !== null ||
        !recordObject(value.workContext) ||
        Object.keys(value.workContext).sort().join(",") !== "selected,stage" ||
        (value.workContext.selected !== null &&
          (!recordObject(value.workContext.selected) ||
            Object.keys(value.workContext.selected).sort().join(",") !==
              "id,kind,selectionDigest"))
      )
        return null;
      route = workContextLocation(
        bidId,
        value.workContext as WorkContextPosition,
      );
      return workspacePositionFromRoute(memberId, bidId, route);
    }
    if (value.workContext !== null) return null;
    if (value.page === "packages") {
      if (value.reviewId !== null || value.draftId !== null) return null;
      if (
        value.packageTarget !== null &&
        (!recordObject(value.packageTarget) ||
          Object.keys(value.packageTarget).sort().join(",") !==
            "inventoryId,packageId,revisionId")
      )
        return null;
      route = packageLocation(
        bidId,
        value.packageTarget as PackageNavigationTarget | null,
      );
    } else {
      if (value.packageTarget !== null) return null;
      const query = new URLSearchParams();
      if (value.reviewId !== null) {
        if (!executionId(value.reviewId)) return null;
        query.set("review", value.reviewId);
      }
      if (value.draftId !== null) {
        if (!executionId(value.draftId)) return null;
        query.set("draft", value.draftId);
      }
      if (query.size) route += `?${query}`;
    }
    return workspacePositionFromRoute(memberId, bidId, route);
  } catch {
    /* Unscoped legacy preferences and damaged records are never restored. */
    return null;
  }
}
