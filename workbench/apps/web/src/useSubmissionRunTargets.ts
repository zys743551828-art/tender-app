import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { KnowledgePackageReviewTargetPage } from "./contracts";
import { validateSubmissionRunTargets } from "./packageSubmissionProtocol";
import { useResource } from "./useResource";

/** The existing project-wide directory is discovery only; selection reads the exact native run. */
export function useSubmissionRunTargets(bidId: string, enabled: boolean) {
  const path = enabled
    ? `/bids/${bidId}/knowledge-reference-targets?limit=20`
    : null;
  const first = useResource<KnowledgePackageReviewTargetPage>(path);
  const [pages, setPages] = useState<
    {
      root: KnowledgePackageReviewTargetPage;
      page: KnowledgePackageReviewTargetPage;
    }[]
  >([]);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  const active = useRef(true),
    root = useRef(first.data),
    working = useRef(false);
  root.current = first.data;
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  let invalid: unknown = null;
  if (first.data)
    try {
      validateSubmissionRunTargets(first.data, bidId);
    } catch (failure) {
      invalid = failure;
    }
  const matching = invalid
    ? []
    : pages.filter((p) => p.root === first.data).map((p) => p.page);
  const items =
    first.data && !invalid
      ? [
          ...new Map(
            [first.data, ...matching]
              .flatMap((p) => p.items)
              .map((i) => [i.id, i]),
          ).values(),
        ]
      : [];
  const last = matching.at(-1) ?? first.data;
  async function more() {
    const offset = last?.next_offset,
      baseline = first.data;
    if (!path || offset == null || !baseline || invalid || working.current)
      return;
    working.current = true;
    setBusy(true);
    setError(null);
    try {
      const { data } = await api<KnowledgePackageReviewTargetPage>(
        `${path}&offset=${offset}`,
      );
      validateSubmissionRunTargets(data, bidId, offset);
      if (active.current && root.current === baseline)
        setPages((old) => [...old, { root: baseline, page: data }]);
    } catch (failure) {
      if (active.current && root.current === baseline) setError(failure);
    } finally {
      working.current = false;
      if (active.current) setBusy(false);
    }
  }
  return {
    first,
    items,
    ready: !!first.data && !first.loading && !first.error && !invalid,
    invalid,
    error,
    more,
    busy,
    hasMore: !invalid && last?.next_offset != null,
  };
}
