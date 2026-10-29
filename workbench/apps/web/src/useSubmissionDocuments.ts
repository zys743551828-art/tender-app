import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { SubmissionDocumentPage } from "./contracts";
import { useResource } from "./useResource";
export function useSubmissionDocuments(bidId: string) {
  const path = `/bids/${bidId}/submission-documents?limit=100`;
  const first = useResource<SubmissionDocumentPage>(path);
  const [pages, setPages] = useState<SubmissionDocumentPage[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const items = [
    ...new Map(
      [
        ...(first.data?.items ?? []),
        ...pages.flatMap((page) => page.items),
      ].map((item) => [item.document_version_id, item]),
    ).values(),
  ];
  const last = pages.at(-1) ?? first.data;
  async function more() {
    if (busy || !last?.next_cursor) return;
    setBusy(true);
    setError(null);
    try {
      const { data } = await api<SubmissionDocumentPage>(
        `${path}&cursor=${encodeURIComponent(last.next_cursor)}`,
      );
      if (active.current) setPages((old) => [...old, data]);
    } catch (failure) {
      if (active.current) setError(failure);
    } finally {
      if (active.current) setBusy(false);
    }
  }
  return {
    ...first,
    items,
    more,
    moreBusy: busy,
    moreError: error,
    hasMore: !!last?.has_more,
  };
}
