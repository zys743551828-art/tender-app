import { useCallback, useState } from "react";
import { ErrorNotice } from "./components";
import {
  capturePackageDirectory,
  captureRevisionDirectory,
} from "./authoringCaptureDirectoryProtocol";
import type { CapturePackageReference } from "./authoringInputCatalogProtocol";
import { useAuthoringCaptureDirectory } from "./useAuthoringCaptureRead";

export function AuthoringCapturePackagePicker({
  bidId,
  kind,
  selected,
  disabled,
  onSelect,
}: {
  bidId: string;
  kind: "bid" | "authority";
  selected: CapturePackageReference | null;
  disabled: boolean;
  onSelect: (value: CapturePackageReference) => void;
}) {
  const name = kind === "bid" ? "目标投标包" : "招标与补遗依据包";
  const [browsing, setBrowsing] = useState(selected?.package_id ?? "");
  const verifyHeads = useCallback(
    (v: unknown) => capturePackageDirectory(v, bidId, kind),
    [bidId, kind],
  );
  const heads = useAuthoringCaptureDirectory(
    `/bids/${bidId}/packages?kind=${kind}&limit=20`,
    verifyHeads,
  );
  const verifyRevisions = useCallback(
    (v: unknown) => captureRevisionDirectory(v, browsing),
    [browsing],
  );
  const revisions = useAuthoringCaptureDirectory(
    browsing ? `/bids/${bidId}/packages/${browsing}/revisions?limit=20` : null,
    verifyRevisions,
  );
  return (
    <fieldset disabled={disabled} className="capture-package-picker">
      <legend>{name}</legend>
      <label>
        {name}目录
        <select value={browsing} onChange={(e) => setBrowsing(e.target.value)}>
          <option value="">先选择一个包查看修订</option>
          {heads.items.map((p) => (
            <option key={p.id} value={p.id}>
              {name} · {p.id.slice(0, 8)}
            </option>
          ))}
        </select>
      </label>
      <ErrorNotice error={heads.error ?? revisions.error} />
      {(heads.busy || revisions.busy) && (
        <p role="status">正在核对{name}目录…</p>
      )}
      <button
        className="text-button"
        type="button"
        disabled={heads.busy}
        onClick={() => void heads.load()}
      >
        刷新{name}目录
      </button>
      {heads.page?.has_more && (
        <button
          className="text-button"
          type="button"
          disabled={heads.busy || !heads.ready}
          onClick={() => void heads.load(true)}
        >
          加载更多{name}
        </button>
      )}
      {heads.ready && !heads.items.length && (
        <p className="small-empty">尚无{name}，请先在项目资料中建立资料包。</p>
      )}
      {browsing && (
        <div aria-label={`${name}可选修订`} className="capture-revisions">
          {revisions.items.map((r) => (
            <button
              type="button"
              className="button secondary"
              key={r.id}
              disabled={!revisions.ready || revisions.busy}
              aria-pressed={
                selected?.package_id === browsing &&
                selected.revision_id === r.id &&
                selected.manifest_digest === r.digest
              }
              onClick={() =>
                onSelect({
                  package_id: browsing,
                  revision_id: r.id,
                  manifest_digest: r.digest,
                })
              }
            >
              选择第 {r.revision} 版 · {r.id.slice(0, 8)}
            </button>
          ))}
          {revisions.page?.has_more && (
            <button
              type="button"
              className="text-button"
              disabled={!revisions.ready || revisions.busy}
              onClick={() => void revisions.load(true)}
            >
              更多{name}修订
            </button>
          )}
        </div>
      )}
      {selected && (
        <p className="small-note">
          已固定包 {selected.package_id.slice(0, 8)} 的修订{" "}
          {selected.revision_id.slice(0, 8)}；刷新目录不会替换。
        </p>
      )}
    </fieldset>
  );
}
