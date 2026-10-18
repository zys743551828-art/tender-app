"""Immutable projections of canonical rules; never another writable clause authority."""

from dataclasses import asdict
from typing import Any

from packages.domain.bid_packages import (
    BidScope,
    CoverageState,
    InspectedRange,
    PackageRevision,
    Requirement,
    RequirementCoverage,
    assess_coverage,
    require,
)
from packages.domain.review_identity import digest


def project_requirement(
    package: PackageRevision,
    rule: dict[str, Any],
    decision: dict[str, Any] | None,
    mapping: dict[str, Any] | None,
    *,
    source_bound: bool = False,
) -> dict[str, Any]:
    """Structured human check-plan annotation; original statement stays in frozen rule."""
    mapping = mapping or {}
    origin = "authority" if rule["origin_kind"] == "model_extracted" else "manual"
    conditions = tuple(
        f"{kind}:{index}:{digest(value)}"
        for kind in ("conditions", "exceptions")
        for index, value in enumerate(rule[kind])
    )
    rule_digest = digest(rule)
    requirement = Requirement(
        rule["id"],
        package.scope,
        origin,
        (
            f"rule:{rule['id']}:{rule_digest}",
            *tuple(f"evidence:{item}" for item in rule["evidence_ids"]),
        ),
        tuple(mapping.get("categories", ["未分类"])),
        tuple(mapping.get("target_part_ids", [])),
        mapping.get("minimum_count"),
        mapping.get("applicability", "unknown"),
        tuple(f"evidence:{item}" for item in mapping.get("applicability_evidence_ids", [])),
        mapping.get("valid_at"),
        conditions,
        tuple(mapping.get("checks", [])),
    )
    # Validate all part/category/scope bindings immediately even without any result.
    assess_coverage(package, (requirement,), ())
    return {
        "rule_id": rule["id"],
        "rule_digest": rule_digest,
        "rule_snapshot": rule,
        "decision_id": decision["id"] if decision else None,
        "decision_snapshot": decision,
        "requirement": requirement.manifest(),
        "requirement_digest": requirement.manifest_digest,
        "source_bound": source_bound and bool(rule["evidence_ids"]),
        "annotation": {
            "kind": "human_check_plan_declaration",
            "mapped": bool(mapping),
            "reason": mapping.get("reason"),
            "basis_evidence_ids": mapping.get("basis_evidence_ids", []),
        },
    }


def decode_requirement(value: dict[str, Any]) -> Requirement:
    fields = dict(value)
    fields["scope"] = BidScope(**fields["scope"])
    for key in (
        "source_refs",
        "categories",
        "target_part_ids",
        "applicability_evidence",
        "conditions",
        "checks",
    ):
        fields[key] = tuple(fields[key])
    return Requirement(**fields)


def coverage_record(
    package: PackageRevision, binding: dict[str, Any], item: dict[str, Any]
) -> dict[str, Any]:
    require(
        item["requirement_digest"] == binding["requirement_digest"],
        "PACKAGE_COVERAGE_REQUIREMENT_STALE",
    )
    state = CoverageState(item["state"])
    if state in {CoverageState.VERIFIED, CoverageState.NOT_APPLICABLE}:
        require(
            item["basis_type"] == "human_scope_declaration",
            "PACKAGE_COVERAGE_HUMAN_DECLARATION_REQUIRED",
        )
        require(bool(item.get("reason", "").strip()), "PACKAGE_COVERAGE_REASON_REQUIRED")
    result = RequirementCoverage(
        binding["rule_id"],
        package.manifest_digest,
        binding["requirement_digest"],
        state,
        tuple(InspectedRange(**row) for row in item["inspected"]),
        tuple(f"evidence:{identity}" for identity in item["evidence_ids"]),
        item.get("reason"),
    )
    value = asdict(result)
    value["state"] = state.value
    value["inspected"] = [asdict(row) for row in result.inspected]
    value["evidence_refs"] = list(result.evidence_refs)
    return {
        "coverage": value,
        "basis_type": item["basis_type"],
        "evidence_ids": list(item["evidence_ids"]),
    }


def assess_records(
    package: PackageRevision, bindings: list[dict[str, Any]], records: list[dict[str, Any]]
) -> dict[str, Any]:
    requirements = tuple(decode_requirement(row["requirement"]) for row in bindings)
    results = []
    for row in records:
        value = row["coverage"]
        results.append(
            RequirementCoverage(
                value["requirement_id"],
                value["package_digest"],
                value["requirement_digest"],
                CoverageState(value["state"]),
                tuple(InspectedRange(**item) for item in value["inspected"]),
                tuple(value["evidence_refs"]),
                value["reason"],
            )
        )
    # Existing rule_sets never froze the full extraction parse input. Do not infer history.
    return assess_coverage(
        package, requirements, tuple(results), requirement_inventory_complete=False
    )
