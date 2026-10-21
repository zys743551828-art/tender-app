import { useState } from "react";
import { api } from "./api";
import type { KnowledgePackageReviewTargetPage } from "./contracts";
import { useResource } from "./useResource";

type Target = KnowledgePackageReviewTargetPage["items"][number];
export type KnowledgeReferenceTargetKind = "project" | "package_review_run";

function validPage(
  value: KnowledgePackageReviewTargetPage | undefined,
  bidId: string,
): value is KnowledgePackageReviewTargetPage {
  return (
    !!value &&
    value.bid_id === bidId &&
    value.reference_only === true &&
    value.changes_frozen_result === false &&
    value.formal_score_allowed === false &&
    Array.isArray(value.items) &&
    value.items.every(
      (item) =>
        !!item &&
        typeof item === "object" &&
        item.target_kind === "package_review_run" &&
        typeof item.id === "string" &&
        typeof item.input_digest === "string" &&
        typeof item.package_id === "string" &&
        typeof item.revision_id === "string" &&
        typeof item.inventory_id === "string" &&
        typeof item.frozen_input_id === "string",
    ) &&
    (value.next_offset === null ||
      (Number.isSafeInteger(value.next_offset) && value.next_offset > 0))
  );
}

export function useKnowledgeReferenceTargets(bidId: string, enabled: boolean) {
  const path = enabled ? `/bids/${bidId}/knowledge-reference-targets` : null;
  const resource = useResource<KnowledgePackageReviewTargetPage>(path);
  const [more, setMore] = useState<
    { path: string; page: KnowledgePackageReviewTargetPage }[]
  >([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const matched = validPage(resource.data, bidId);
  const pages = more
    .filter((item) => item.path === path)
    .map((item) => item.page);
  const items: Target[] = matched
    ? [
        ...new Map(
          [resource.data!, ...pages]
            .flatMap((page) => page.items)
            .map((item) => [item.id, item]),
        ).values(),
      ]
    : [];
  const last = pages.at(-1) ?? (matched ? resource.data : undefined);
  async function next() {
    const offset = last?.next_offset;
    if (!path || offset == null || busy || !matched) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api<KnowledgePackageReviewTargetPage>(
        `${path}?offset=${offset}`,
      );
      if (
        !validPage(result.data, bidId) ||
        (result.data.next_offset !== null && result.data.next_offset <= offset)
      )
        throw new Error("核查目录身份或分页不一致，请重新读取后选择。");
      setMore((old) => [...old, { path, page: result.data }]);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return {
    resource,
    items,
    ready: enabled && matched && !resource.loading && !resource.error,
    mismatch: !!resource.data && !matched,
    next,
    hasMore: last?.next_offset != null,
    busy,
    error,
  };
}
