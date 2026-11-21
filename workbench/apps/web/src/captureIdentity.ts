export const captureIdentityNames = [
  "procurement_issuer_identifier",
  "procurement_project_identifier",
  "procurement_lot_identifier",
  "procurement_round_identifier",
  "bidder_identity_identifier",
] as const;
export type CaptureIdentityName = (typeof captureIdentityNames)[number];
export const captureIdentityLabels: Record<CaptureIdentityName, string> = {
  procurement_issuer_identifier: "采购方编号",
  procurement_project_identifier: "工程项目编号",
  procurement_lot_identifier: "标段编号",
  procurement_round_identifier: "投标轮次编号",
  bidder_identity_identifier: "投标主体编号",
};

export function isCaptureIdentityName(
  name: string,
): name is CaptureIdentityName {
  return captureIdentityNames.some((identity) => identity === name);
}
