import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { useResource } from "./useResource";

type CursorPage = {
  items: { id: string }[];
  has_more: boolean;
  next_cursor: string | null;
};
/** Consumes generated page types; cursors stay bound to their exact source/filter. */
export function useDirectory<T extends CursorPage>(
  path: string | null,
  validatePage?: (value: unknown) => boolean,
) {
  const first = useResource<T>(path);
  const firstValid = !first.data || !validatePage || validatePage(first.data);
  const firstData = firstValid ? first.data : undefined;
  const [pages, setPages] = useState<
    { path: string; root: T | undefined; page: T }[]
  >([]);
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, unknown>>({});
  const pending = useRef(new Set<string>());
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const matching = pages
    .filter((page) => page.path === path && page.root === firstData)
    .map((page) => page.page);
  const last = matching.at(-1) ?? firstData;
  const items = [
    ...new Map(
      [
        ...(firstData?.items ?? []),
        ...matching.flatMap((page) => page.items),
      ].map((item) => [item.id, item as T["items"][number]]),
    ).values(),
  ];
  async function loadMore() {
    if (
      !path ||
      !last?.has_more ||
      !last.next_cursor ||
      pending.current.has(path)
    )
      return;
    pending.current.add(path);
    setLoading((old) => ({ ...old, [path]: true }));
    setErrors((old) => ({ ...old, [path]: null }));
    try {
      const { data } = await api<T>(
        `${path}${path.includes("?") ? "&" : "?"}cursor=${encodeURIComponent(last.next_cursor)}`,
      );
      if (validatePage && !validatePage(data))
        throw new Error(
          "目录页身份或分页状态不一致，未把未读取内容当作空目录。",
        );
      if (data.has_more && data.next_cursor === last.next_cursor)
        throw new Error("目录分页游标没有推进，请重读当前目录后继续。");
      if (active.current)
        setPages((old) => [...old, { path, root: firstData, page: data }]);
    } catch (failure) {
      if (active.current) setErrors((old) => ({ ...old, [path]: failure }));
    } finally {
      pending.current.delete(path);
      if (active.current) setLoading((old) => ({ ...old, [path]: false }));
    }
  }
  return {
    ...first,
    data: firstData,
    error:
      first.error ??
      (firstValid
        ? undefined
        : new Error("目录页身份或分页状态不一致，尚不能判断目录内容。")),
    items,
    hasMore: !!last?.has_more,
    loadMore,
    moreBusy: !!path && !!loading[path],
    moreError: path ? errors[path] : undefined,
  };
}
