import {
  exactKeys,
  executionId,
  recordObject,
} from "./executionInputValidation";
import { recordedCommandStorageKey } from "./recordedCommandStorage";
export type PackageReviewComparisonSelection = {
  version: 1;
  memberId: string;
  bidId: string;
  leftId: string;
  rightId: string;
};
export const packageReviewComparisonSelectionKey = (
  memberId: string,
  bidId: string,
) =>
  recordedCommandStorageKey(
    "package-review-run",
    memberId,
    bidId,
    "comparison-selection",
  );
export function loadPackageReviewComparisonSelection(
  memberId: string,
  bidId: string,
  currentRunId: string,
): PackageReviewComparisonSelection {
  const raw = sessionStorage.getItem(
    packageReviewComparisonSelectionKey(memberId, bidId),
  );
  if (raw === null)
    return { version: 1, memberId, bidId, leftId: "", rightId: currentRunId };
  const fail = () => {
    throw new Error(
      "此前的对比选择无法读取，请重新选择两条运行。尚未读取任何对比。",
    );
  };
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return fail();
  }
  if (
    !recordObject(value) ||
    !exactKeys(value, ["version", "memberId", "bidId", "leftId", "rightId"]) ||
    value.version !== 1 ||
    value.memberId !== memberId ||
    value.bidId !== bidId ||
    typeof value.leftId !== "string" ||
    value.leftId.length > 36 ||
    typeof value.rightId !== "string" ||
    value.rightId.length > 36
  )
    return fail();
  return value as PackageReviewComparisonSelection;
}
export function storePackageReviewComparisonSelection(
  value: PackageReviewComparisonSelection,
) {
  sessionStorage.setItem(
    packageReviewComparisonSelectionKey(value.memberId, value.bidId),
    JSON.stringify(value),
  );
}
export const validPackageReviewComparisonSelection = (
  value: PackageReviewComparisonSelection,
) =>
  executionId(value.bidId) &&
  executionId(value.leftId) &&
  executionId(value.rightId) &&
  value.leftId !== value.rightId;
