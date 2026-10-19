"""Projection semantics only; live PG/ASGI/commit behavior requires grouped integration."""

from copy import deepcopy

import pytest
from test_bid_packages import package

from packages.contracts.bid_package_requirements_api import BASE, extend_openapi, valid
from packages.domain.bid_package_requirements import (
    assess_records,
    coverage_record,
    project_requirement,
)
from packages.domain.bid_packages import PackageError


def rule():
    return {
        "id": "rule-1",
        "origin_kind": "model_extracted",
        "statement": "完整原规则，不另建可写条款",
        "conditions": ["当" + "条件" * 160],
        "exceptions": ["除非另有明确依据"],
        "evidence_ids": ["authority-evidence"],
        "provenance_status": "effective",
    }


def mapping():
    return {
        "categories": ["technical"],
        "target_part_ids": ["part-member-1"],
        "minimum_count": None,
        "applicability": "applicable",
        "applicability_evidence_ids": [],
        "valid_at": None,
        "checks": [],
        "reason": "明确人工检查计划",
        "basis_evidence_ids": ["authority-evidence"],
    }


def result(binding, **changes):
    return {
        "rule_id": binding["rule_id"],
        "requirement_digest": binding["requirement_digest"],
        "state": "verified",
        "inspected": [{"part_id": "part-member-1", "first_page": 1, "last_page": 4}],
        "evidence_ids": ["body-evidence"],
        "reason": "人工声明已核对明确物理范围，不表示合规结论",
        "basis_type": "human_scope_declaration",
    } | changes


def test_projection_does_not_mutate_or_alias_the_canonical_rule_and_long_conditions():
    original = rule()
    annotation = mapping()
    decision = {"id": "decision-1", "decision": "confirmed"}
    saved = project_requirement(package(), original, decision, annotation, source_bound=True)
    frozen = deepcopy(saved)
    original["statement"] = "外部变更"
    original["conditions"].clear()
    annotation["basis_evidence_ids"].clear()
    decision["decision"] = "rejected"
    assert saved == frozen
    assert saved["rule_snapshot"]["statement"] == "完整原规则，不另建可写条款"
    assert saved["requirement"]["conditions"][0].startswith("conditions:0:")
    assert len(saved["rule_snapshot"]["conditions"][0]) > 200


def test_unmapped_rules_missing_results_and_empty_authority_evidence_are_unknown():
    source = rule() | {"evidence_ids": []}
    saved = project_requirement(package(), source, None, None, source_bound=True)
    assert saved["source_bound"] is False
    assert saved["requirement"]["categories"] == ["未分类"]
    assert saved["requirement"]["minimum_count"] is None
    assessment = assess_records(package(), [saved], [])
    assert assessment["requirement_states"] == {"rule-1": "unknown"}
    assert assessment["complete"] is False and assessment["requirement_inventory_complete"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"minimum_count": 20, "checks": ["quantity"]},
        {"valid_at": "2026-10-19T00:00:00Z"},
        {"categories": ["technical", "qualification"]},
        {"applicability": "unknown"},
    ],
)
def test_mapping_revision_changes_requirement_digest_and_rejects_old_result(change):
    p = package()
    original = project_requirement(p, rule(), None, mapping(), source_bound=True)
    checked = coverage_record(p, original, result(original))
    revised = project_requirement(p, rule(), None, mapping() | change, source_bound=True)
    assert revised["requirement_digest"] != original["requirement_digest"]
    with pytest.raises(PackageError, match="PACKAGE_COVERAGE_REQUIREMENT_STALE"):
        assess_records(p, [revised], [checked])


def test_even_full_manual_verified_ranges_do_not_bless_unproven_extraction_inventory():
    p = package()
    saved = project_requirement(p, rule(), None, mapping(), source_bound=True)
    checked = coverage_record(p, saved, result(saved))
    assessment = assess_records(p, [saved], [checked])
    assert assessment["requirement_states"] == {"rule-1": "verified"}
    assert assessment["complete"] is False and assessment["requirement_inventory_complete"] is False


@pytest.mark.parametrize(
    "change,code",
    [
        ({"basis_type": "human_observation"}, "PACKAGE_COVERAGE_HUMAN_DECLARATION_REQUIRED"),
        ({"reason": ""}, "PACKAGE_COVERAGE_REASON_REQUIRED"),
        ({"evidence_ids": []}, "PACKAGE_COVERAGE_EVIDENCE_REQUIRED"),
        ({"state": "matrix_satisfied"}, "PACKAGE_COVERAGE_STATE_INVALID"),
    ],
)
def test_positive_is_explicit_manual_scope_not_arbitrary_state_or_old_matrix(change, code):
    p = package()
    saved = project_requirement(p, rule(), None, mapping(), source_bound=True)
    with pytest.raises(PackageError, match=code):
        coverage_record(p, saved, result(saved, **change))


def test_wrong_target_part_and_unproven_not_applicable_are_rejected():
    p = package()
    with pytest.raises(PackageError, match="PACKAGE_TARGET_PART_UNKNOWN"):
        project_requirement(p, rule(), None, mapping() | {"target_part_ids": ["other-part"]})
    with pytest.raises(PackageError, match="PACKAGE_NOT_APPLICABLE_EVIDENCE_REQUIRED"):
        project_requirement(p, rule(), None, mapping() | {"applicability": "not_applicable"})


def test_exact_page_union_must_not_have_holes_or_leave_frozen_parts():
    p = package()
    saved = project_requirement(p, rule(), None, mapping(), source_bound=True)
    for ranges, code in [
        (
            [{"part_id": "part-member-1", "first_page": 1, "last_page": 3}],
            "PACKAGE_VERIFIED_SCOPE_INCOMPLETE",
        ),
        (
            [{"part_id": "part-member-1", "first_page": 1, "last_page": 5}],
            "PACKAGE_INSPECTED_OUT_OF_BOUNDS",
        ),
    ]:
        checked = coverage_record(p, saved, result(saved, inspected=ranges))
        with pytest.raises(PackageError, match=code):
            assess_records(p, [saved], [checked])


@pytest.mark.parametrize("bad", ["bad\x00id", "bad\ud800id", "bad\udfffid"])
def test_new_attempt_schema_rejects_invalid_unicode_in_nested_inspected_part(bad):
    value = {
        "inventory_digest": "a" * 64,
        "package_digest": "b" * 64,
        "results": [
            {
                "rule_id": "00000000-0000-0000-0000-000000000001",
                "requirement_digest": "c" * 64,
                "state": "unknown",
                "inspected": [{"part_id": bad, "first_page": 1, "last_page": 1}],
                "evidence_ids": [],
                "reason": "明确未知",
                "basis_type": "human_observation",
            }
        ],
    }
    assert not valid("CreatePackageCoverageAttempt", value)
    value["results"][0]["inspected"][0]["part_id"] = "附件😀"
    assert valid("CreatePackageCoverageAttempt", value)


def test_inventory_and_attempt_directories_have_distinct_actual_response_schemas():
    paths = {BASE: {"get": {}}, BASE + "/{inventory_id}/coverage-attempts": {"get": {}}}
    actual = {"paths": paths}
    extend_openapi(actual)
    expected = [
        (BASE, "PackageRequirementInventoryPage"),
        (BASE + "/{inventory_id}/coverage-attempts", "PackageRequirementHistoryPage"),
    ]
    for path, name in expected:
        response = paths[path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        assert response == {"$ref": "#/components/schemas/" + name}
    page = {"items": [], "has_more": False, "next_cursor": None}
    assert valid("PackageRequirementHistoryPage", page)
    assert not valid("PackageRequirementInventoryPage", page)
    assert valid("PackageRequirementInventoryPage", page | {"current_inventory_id": None})
    assert not valid("PackageRequirementHistoryPage", page | {"current_inventory_id": None})
