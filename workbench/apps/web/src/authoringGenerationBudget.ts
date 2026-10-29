/** Batch contracts use integer nano-units; never round a typed decimal through IEEE-754. */
export const generationAmountScale = 1_000_000_000 as const;
export function parseGenerationAmount(value: string): number | null {
  const match = /^(0|[1-9]\d{0,15})(?:\.(\d{1,9}))?$/.exec(value.trim());
  if (!match) return null;
  const minor =
    BigInt(match[1]) * BigInt(generationAmountScale) +
    BigInt((match[2] ?? "").padEnd(9, "0"));
  return minor <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(minor) : null;
}
export function generationAmountText(minor: number): string {
  if (!Number.isSafeInteger(minor) || minor < 0)
    throw new Error("费用不是可核对的整数单位。");
  const value = BigInt(minor),
    scale = BigInt(generationAmountScale);
  const fraction = (value % scale)
    .toString()
    .padStart(9, "0")
    .replace(/0+$/, "");
  return `${value / scale}${fraction ? `.${fraction}` : ""}`;
}
export function sumGenerationLimits(values: number[]): number | null {
  if (values.some((value) => !Number.isSafeInteger(value) || value < 0))
    return null;
  const total = values.reduce((sum, value) => sum + BigInt(value), 0n);
  return total <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(total) : null;
}
