import { useState } from "react";
import { ErrorNotice } from "./components";
import { historicalSame } from "./historicalImportProtocol";
import type { OutlineBasis } from "./technicalBidOutlinePlan";
import {
  recoverOutlineSelection,
  type OutlineSelectionScope,
} from "./technicalOutlineSelection";
import { useTechnicalOutlineSources } from "./useTechnicalOutlineSources";

export function TechnicalOutlineSourceShortcut({
  scope,
  disabled,
  onSelect,
}: {
  scope: OutlineSelectionScope;
  disabled: boolean;
  onSelect: (basis: OutlineBasis) => void;
}) {
  const [available] = useState(() => recoverOutlineSelection(scope) !== null);
  const [basis, setBasis] = useState<OutlineBasis | null>(null);
  const [forgotten, setForgotten] = useState(false);
  const {
    targetView,
    authorityView,
    ready,
    matchingScope,
    directory,
    current,
    inventory,
    checkedInventory,
  } = useTechnicalOutlineSources(
    scope.bidId,
    basis?.target ?? null,
    basis?.authority ?? null,
    basis?.inventory ?? null,
  );
  if (!available) return null;

  const error =
    targetView.error ??
    authorityView.error ??
    directory.error ??
    inventory.error;
  const stale =
    error != null || (ready && !matchingScope) || (directory.ready && !current);
  const checking = basis !== null && !stale && !checkedInventory;
  return (
    <section className="notice" aria-label="带入大纲的资料选择">
      <p>
        可重新核对这份草稿的大纲资料。只带入两包和要求清单，不选择正文节点、事实或用途，不保存和不运行。
      </p>
      {basis === null && (
        <button
          type="button"
          className="button secondary"
          disabled={disabled}
          onClick={() => {
            const saved = recoverOutlineSelection(scope);
            setBasis(saved);
            setForgotten(!saved);
          }}
        >
          核对大纲的资料选择
        </button>
      )}
      {forgotten && (
        <p role="status">
          原会话选择已清除或更改，此次未带入。请重新核对或在下方明确选择资料。
        </p>
      )}
      {checking && <p role="status">正在核对包当前修订和要求清单…</p>}
      {stale && (
        <>
          <p role="status">
            未带入：原选择已变化或无法核对，请在下方明确选择。
          </p>
          <ErrorNotice error={error} />
        </>
      )}
      {basis && checkedInventory && (
        <>
          <p role="status">
            本次已核对投标包修订 {basis.target.revision_id.slice(0, 8)} ·
            依据包修订 {basis.authority.revision_id.slice(0, 8)} · 清单{" "}
            {basis.inventory.id.slice(0, 8)}
          </p>
          <button
            type="button"
            className="button secondary"
            disabled={disabled}
            onClick={() => {
              if (!historicalSame(basis, recoverOutlineSelection(scope))) {
                setBasis(null);
                setForgotten(true);
                return;
              }
              onSelect(basis);
            }}
          >
            将这组资料填入采集表单
          </button>
        </>
      )}
    </section>
  );
}
