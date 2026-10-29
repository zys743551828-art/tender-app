import { executionId, executionSha } from "./executionInputValidation";

export const workContextStages = [
  ["draft_snapshot", "已保存草稿"],
  ["build", "生成记录"],
  ["package_review_run", "整包核查"],
  ["package_submission", "实交记录"],
] as const;
export type WorkContextKind = (typeof workContextStages)[number][0];
export type WorkContextTarget = {
  kind: WorkContextKind;
  id: string;
  selectionDigest: string;
};
export type WorkContextPosition = {
  stage: WorkContextKind;
  selected: WorkContextTarget | null;
};
export type WorkContextLocation =
  | { ok: true; position: WorkContextPosition }
  | { ok: false; message: string };

export function parseWorkContextLocation(
  bidId: string,
  route: string,
): WorkContextLocation {
  const invalid: WorkContextLocation = {
    ok: false,
    message: "阶段链接的身份不完整或存在重复参数，请核对原链接后重新选择。",
  };
  const [path, ...search] = route.split("?");
  if (
    !executionId(bidId) ||
    path !== `/bids/${bidId}/work-context` ||
    search.length > 1 ||
    route.includes("#")
  )
    return invalid;
  const query = new URLSearchParams(search[0] ?? "");
  if (
    [...query.keys()].some(
      (key) =>
        !["stage", "id", "selection"].includes(key) ||
        query.getAll(key).length !== 1,
    )
  )
    return invalid;
  if (!query.size)
    return { ok: true, position: { stage: "draft_snapshot", selected: null } };
  const stage = workContextStages.find(
    ([kind]) => kind === query.get("stage"),
  )?.[0];
  if (!stage) return invalid;
  const id = query.get("id"),
    digest = query.get("selection");
  if (id === null && digest === null)
    return { ok: true, position: { stage, selected: null } };
  if (!executionId(id) || !executionSha(digest)) return invalid;
  return {
    ok: true,
    position: { stage, selected: { kind: stage, id, selectionDigest: digest } },
  };
}

export function workContextLocation(
  bidId: string,
  position: WorkContextPosition,
) {
  const query = new URLSearchParams({ stage: position.stage });
  if (position.selected) {
    if (position.selected.kind !== position.stage)
      throw new Error("所选记录不属于当前阶段。");
    query.set("id", position.selected.id);
    query.set("selection", position.selected.selectionDigest);
  }
  const route = `/bids/${bidId}/work-context?${query}`;
  if (!parseWorkContextLocation(bidId, route).ok)
    throw new Error("不能创建身份无效的阶段链接。");
  return route;
}

export function workContextPath(bidId: string, target: WorkContextTarget) {
  if (
    !executionId(bidId) ||
    !executionId(target.id) ||
    !executionSha(target.selectionDigest) ||
    !workContextStages.some(([kind]) => kind === target.kind)
  )
    throw new Error("请选择完整、明确的阶段记录。");
  return `/bids/${bidId}/work-contexts/${target.kind}/${target.id}?expected_selection_digest=${target.selectionDigest}`;
}
