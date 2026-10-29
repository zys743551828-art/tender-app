import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { BidPackageStoredView, PackageEvidencePage } from "./contracts";
import { validateDirectory } from "./packageEvidenceDirectory";
import type { EvidenceEntry as Entry } from "./packageEvidenceDirectory";
import "./CoverageEditor.css";
type EvidencePage = PackageEvidencePage;
function EvidenceDirectory({
  bidId,
  view,
  disabled,
  renderEntry,
}: {
  bidId: string;
  view: BidPackageStoredView;
  disabled: boolean;
  renderEntry: (entry: Entry, index: number) => React.ReactNode;
}) {
  const path = `/bids/${bidId}/packages/${view.manifest.package_id}/revisions/${view.manifest.revision_id}/evidence?limit=20`;
  const generation = useRef(0);
  const invalidate = useCallback(() => {
    generation.current++;
  }, []);
  const [snapshot, setSnapshot] = useState<{
    path: string;
    items: Entry[];
    next: string | null;
    hasMore: boolean;
    loading: boolean;
    error?: unknown;
  }>({ path, items: [], next: null, hasMore: false, loading: true });
  async function load(cursor: string | null = null) {
    const token = ++generation.current;
    setSnapshot((old) => ({ ...old, path, loading: true, error: undefined }));
    try {
      const { data } = await api<EvidencePage>(
        path + (cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""),
      );
      validateDirectory(data, view);
      if (data.has_more && cursor === data.next_cursor)
        throw new Error("证据目录游标没有推进，请重读后继续。");
      if (generation.current !== token) return;
      setSnapshot((old) => {
        const merged = new Map(
          (cursor && old.path === path ? old.items : []).map((item) => [
            item.id,
            item,
          ]),
        );
        for (const item of data.items) merged.set(item.id, item);
        return {
          path,
          items: [...merged.values()],
          next: data.next_cursor,
          hasMore: data.has_more,
          loading: false,
        };
      });
    } catch (error) {
      if (generation.current === token)
        setSnapshot((old) => ({ ...old, path, loading: false, error }));
    }
  }
  useEffect(() => {
    void load();
    return invalidate;
    // One immutable directory instance per captured package revision.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, view.digest, invalidate]);
  const current = snapshot.path === path ? snapshot : null;
  return (
    <div className="coverage-editor-directory">
      {current?.loading && <p>正在读取冻结解析的证据目录…</p>}
      {!!current?.error && (
        <p role="alert">
          {current.error instanceof Error
            ? current.error.message
            : "目录读取失败"}
          <button
            type="button"
            disabled={disabled || current.loading}
            onClick={() => void load(current.next)}
          >
            重读证据目录
          </button>
        </p>
      )}
      {current?.items.map(renderEntry)}
      {current &&
        !current.loading &&
        !current.items.length &&
        !current.error && <p>此冻结包暂无可定位证据，不会改取最新解析。</p>}
      {current?.hasMore && (
        <button
          type="button"
          disabled={disabled || current.loading}
          onClick={() => void load(current.next)}
        >
          更多冻结证据
        </button>
      )}
    </div>
  );
}

export default function PackageEvidencePicker({
  label,
  bidId,
  view,
  disabled,
  renderEntry,
  buttonClassName,
}: {
  label: string;
  bidId: string;
  view: BidPackageStoredView;
  disabled: boolean;
  renderEntry: (entry: Entry, index: number) => React.ReactNode;
  buttonClassName?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        type="button"
        className={buttonClassName}
        disabled={disabled}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {label}
      </button>
      {open && (
        <EvidenceDirectory
          key={`${view.manifest.revision_id}:${view.digest}`}
          bidId={bidId}
          view={view}
          disabled={disabled}
          renderEntry={renderEntry}
        />
      )}
    </div>
  );
}
