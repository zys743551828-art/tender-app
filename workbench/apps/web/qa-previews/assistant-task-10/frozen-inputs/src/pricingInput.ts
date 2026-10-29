import type { PricingRequest } from "./contracts";

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object")
    return `{${Object.entries(value)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`)
      .join(",")}}`;
  return JSON.stringify(value);
}
export async function pricingInputDigest(
  request: PricingRequest,
  formulaDigest: string,
) {
  const bytes = new TextEncoder().encode(
    canonical({ formula_digest: formulaDigest, request }),
  );
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}
export function pricingRequestSignature(request: PricingRequest) {
  return canonical(request);
}
