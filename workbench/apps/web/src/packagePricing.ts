import type { PricingPackagePricingBinding } from "./contracts";

export type PackagePricingBinding = PricingPackagePricingBinding;

export function samePricingBinding(
  left: PackagePricingBinding | undefined,
  right: PackagePricingBinding | undefined,
) {
  if (!left || !right) return !left && !right;
  return (
    left.package_id === right.package_id &&
    left.revision_id === right.revision_id &&
    left.authority_package_id === right.authority_package_id &&
    left.authority_revision_id === right.authority_revision_id
  );
}

export function pricingScopeKey(binding?: PackagePricingBinding) {
  return binding
    ? `:${JSON.stringify({
        package_id: binding.package_id,
        revision_id: binding.revision_id,
        authority_package_id: binding.authority_package_id,
        authority_revision_id: binding.authority_revision_id,
      })}`
    : "";
}

export function pricingContextPath(
  bidId: string,
  binding?: PackagePricingBinding,
) {
  return binding
    ? `/bids/${bidId}/package-pricing-context?${new URLSearchParams(binding)}`
    : `/bids/${bidId}/pricing-context`;
}
