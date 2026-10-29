"""Explicit whole-package selection for evidence-backed price formulas."""

from uuid import UUID

from packages.pricing.models import RegisterFormula, Strict


class PackagePricingBinding(Strict):
    package_id: UUID
    revision_id: UUID
    authority_package_id: UUID
    authority_revision_id: UUID


class RegisterPackageFormula(RegisterFormula):
    package_binding: PackagePricingBinding
