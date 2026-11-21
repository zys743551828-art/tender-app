import { useCallback } from "react";
import {
  captureInventoryDirectory,
  captureInventoryView,
  capturePackageView,
} from "./authoringCaptureDirectoryProtocol";
import type { CapturePackageReference } from "./authoringInputCatalogProtocol";
import { sameLot, type OutlineBasis } from "./technicalBidOutlinePlan";
import {
  useAuthoringCaptureDirectory,
  useAuthoringCaptureRead,
} from "./useAuthoringCaptureRead";

/** Read-only validation of exact choices; a preview/save still has its own server guards. */
export function useTechnicalOutlineSources(
  bidId: string,
  target: CapturePackageReference | null,
  authority: CapturePackageReference | null,
  selection: OutlineBasis["inventory"] | null,
) {
  const verifyTarget = useCallback(
    (v: unknown) => {
      if (!target) throw new Error("请选择明确的目标投标包修订。");
      return capturePackageView(v, bidId, "target", target);
    },
    [bidId, target],
  );
  const verifyAuthority = useCallback(
    (v: unknown) => {
      if (!authority) throw new Error("请选择明确的招标依据包修订。");
      return capturePackageView(v, bidId, "authority", authority);
    },
    [bidId, authority],
  );
  const targetPath = target && `/bids/${bidId}/packages/${target.package_id}`;
  const sourcePath =
    authority && `/bids/${bidId}/packages/${authority.package_id}`;
  const targetView = useAuthoringCaptureRead(targetPath, verifyTarget);
  const authorityView = useAuthoringCaptureRead(sourcePath, verifyAuthority);
  const ready = !!(
    target &&
    authority &&
    targetView.ready &&
    authorityView.ready &&
    targetView.value?.manifest.revision_id === target.revision_id &&
    targetView.value.digest === target.manifest_digest &&
    authorityView.value?.manifest.revision_id === authority.revision_id &&
    authorityView.value.digest === authority.manifest_digest
  );
  const matchingScope = !!(
    targetView.value &&
    authorityView.value &&
    sameLot(targetView.value.manifest.scope, authorityView.value.manifest.scope)
  );
  const directoryPath =
    ready && matchingScope
      ? `/bids/${bidId}/packages/${target!.package_id}/revisions/${target!.revision_id}/requirement-inventories`
      : null;
  const directory = useAuthoringCaptureDirectory(
    directoryPath && directoryPath + "?limit=20",
    captureInventoryDirectory,
  );
  const listed = directory.items.find((row) => row.id === selection?.id);
  const current =
    directory.ready &&
    !!selection &&
    selection.id === directory.page?.current_inventory_id &&
    (!listed || listed.digest === selection.digest);
  const verifyInventory = useCallback(
    (v: unknown) => {
      if (!targetView.value || !authorityView.value || !selection)
        throw new Error("清单没有明确的目标包或依据包。");
      return captureInventoryView(
        v,
        targetView.value,
        authorityView.value,
        selection,
      );
    },
    [targetView.value, authorityView.value, selection],
  );
  const inventoryPath =
    directoryPath && current && selection
      ? `/bids/${bidId}/packages/${target!.package_id}/revisions/${target!.revision_id}/requirement-inventories/${selection.id}`
      : null;
  const inventory = useAuthoringCaptureRead(inventoryPath, verifyInventory);
  const checkedInventory =
    ready &&
    matchingScope &&
    current &&
    selection &&
    inventory.ready &&
    inventory.value?.manifest.id === selection.id &&
    inventory.value.digest === selection.digest
      ? inventory.value
      : null;
  return {
    targetView,
    authorityView,
    ready,
    matchingScope,
    directoryPath,
    directory,
    current,
    inventory,
    checkedInventory,
  };
}
