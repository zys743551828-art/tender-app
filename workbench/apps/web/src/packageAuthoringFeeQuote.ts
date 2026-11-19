import {
  exactKeys,
  executionId,
  recordObject,
} from "./executionInputValidation";
import { authoringTimestamp } from "./packageAuthoringInputProtocol";

export type AuthoringFeeCap = {
  price_version_id: string;
  max_reserved_minor: number;
};
export type ExactAuthoringFeeQuote = {
  protocol: "exact-authoring-fee-quote/1";
  bid_id: string;
  definition_id: string;
  definition_version_id: string;
  template_etag: string;
  price_version_id: string;
  currency: "USD" | "CNY";
  amount_scale: 1000000000;
  reserved_minor: number;
  valid_until: string;
  estimate_not_provider_spend_cap: true;
};
const keys = [
  "protocol",
  "bid_id",
  "definition_id",
  "definition_version_id",
  "template_etag",
  "price_version_id",
  "currency",
  "amount_scale",
  "reserved_minor",
  "valid_until",
  "estimate_not_provider_spend_cap",
];
function amount(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}
export function validAuthoringFeeCap(value: unknown): value is AuthoringFeeCap {
  return (
    recordObject(value) &&
    exactKeys(value, ["price_version_id", "max_reserved_minor"]) &&
    executionId(value.price_version_id) &&
    amount(value.max_reserved_minor)
  );
}
export function exactAuthoringFeeQuote(
  value: unknown,
  scope: {
    bidId: string;
    definitionId: string;
    versionId: string;
    etag: string;
  },
): ExactAuthoringFeeQuote | null {
  if (
    !recordObject(value) ||
    !exactKeys(value, keys) ||
    value.protocol !== "exact-authoring-fee-quote/1" ||
    value.bid_id !== scope.bidId ||
    value.definition_id !== scope.definitionId ||
    value.definition_version_id !== scope.versionId ||
    value.template_etag !== scope.etag ||
    !executionId(value.price_version_id) ||
    !["USD", "CNY"].includes(value.currency as string) ||
    value.amount_scale !== 1000000000 ||
    !amount(value.reserved_minor) ||
    !authoringTimestamp(value.valid_until) ||
    value.estimate_not_provider_spend_cap !== true
  )
    return null;
  return value as unknown as ExactAuthoringFeeQuote;
}
