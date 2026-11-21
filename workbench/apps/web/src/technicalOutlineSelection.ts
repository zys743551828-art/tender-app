import type { CapturePackageReference } from "./authoringInputCatalogProtocol";
import {
  exactKeys,
  executionId,
  executionSha,
  recordObject,
} from "./executionInputValidation";
import { knowledgeStorageKey } from "./knowledgeStorage";
import type { OutlineBasis } from "./technicalBidOutlinePlan";

export type OutlineSelectionScope = {
  memberId: string;
  bidId: string;
  draftId: string;
};
export const outlineSelectionKey = (s: OutlineSelectionScope) =>
  knowledgeStorageKey(
    s.memberId,
    "technical-outline:" + JSON.stringify([s.bidId, s.draftId]),
  );

function pack(v: unknown): v is CapturePackageReference {
  return (
    recordObject(v) &&
    exactKeys(v, ["package_id", "revision_id", "manifest_digest"]) &&
    executionId(v.package_id) &&
    executionId(v.revision_id) &&
    executionSha(v.manifest_digest)
  );
}
function validBasis(value: unknown): value is OutlineBasis {
  if (
    !recordObject(value) ||
    !exactKeys(value, ["target", "authority", "inventory"])
  )
    return false;
  const { target, authority, inventory } = value;
  return (
    pack(target) &&
    pack(authority) &&
    target.package_id !== authority.package_id &&
    recordObject(inventory) &&
    exactKeys(inventory, ["id", "digest"]) &&
    executionId(inventory.id) &&
    executionSha(inventory.digest)
  );
}
export function recoverOutlineSelection(
  s: OutlineSelectionScope,
): OutlineBasis | null {
  try {
    const raw = sessionStorage.getItem(outlineSelectionKey(s));
    if (!raw || raw.length > 4096) return null;
    const v: unknown = JSON.parse(raw);
    return recordObject(v) &&
      exactKeys(v, ["version", "member_id", "bid_id", "draft_id", "basis"]) &&
      v.version === 1 &&
      v.member_id === s.memberId &&
      v.bid_id === s.bidId &&
      v.draft_id === s.draftId &&
      validBasis(v.basis)
      ? v.basis
      : null;
  } catch {
    return null;
  }
}

/** Remember display choices only. The API and checked web reads remain authoritative. */
export function storeOutlineSelection(
  s: OutlineSelectionScope,
  basis: OutlineBasis | null,
) {
  try {
    const key = outlineSelectionKey(s);
    if (basis === null) {
      sessionStorage.removeItem(key);
    } else if (validBasis(basis)) {
      sessionStorage.setItem(
        key,
        JSON.stringify({
          version: 1,
          member_id: s.memberId,
          bid_id: s.bidId,
          draft_id: s.draftId,
          basis,
        }),
      );
    }
  } catch {
    // A disabled session cache does not prevent working with checked server data.
  }
}
