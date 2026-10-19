from copy import deepcopy
from uuid import uuid4

import pytest

from packages.contracts.bid_package_requirements_api import valid
from packages.domain.bid_package_extraction import _full_page_parts


def uuid():
    return str(uuid4())


def package_requirement_inventory(version="bid-package-requirements/1"):
    value = {
        "version": version,
        "id": uuid(),
        "bid_id": uuid(),
        "package_id": uuid(),
        "target_revision_id": uuid(),
        "package_digest": "a" * 64,
        "authority_revision_id": uuid(),
        "authority_digest": "b" * 64,
        "rule_set_id": uuid(),
        "rule_set_digest": "c" * 64,
        "revision": 1,
        "predecessor_digest": None,
        "identity_digest": "d" * 64,
        "source_snapshot": [],
        "requirements": [],
        "inventory_complete": False,
        "extraction_binding": "unproven_legacy_rule_set",
        "review_ready": False,
        "actor_id": uuid(),
    }
    if version == "bid-package-requirements/2":
        value.update(
            {
                "extraction_binding": "exact_frozen_input_result",
                "extraction_input_digest": "e" * 64,
                "extraction_result_digest": "f" * 64,
                "extraction_result_id": uuid(),
                "extraction_range_status": "all_frozen_evidence_submitted",
                "extraction_coverage": "partial",
                "extraction_quality_status": "not_measured",
            }
        )
    return value


@pytest.mark.parametrize(
    "parts,count,expected",
    [
        ([{"first_page": 1, "last_page": 4}], 4, True),
        ([{"first_page": 1, "last_page": 2}, {"first_page": 3, "last_page": 4}], 4, True),
        ([{"first_page": 1, "last_page": 2}, {"first_page": 4, "last_page": 4}], 4, False),
        ([{"first_page": 1, "last_page": 3}], 4, False),
        ([{"first_page": 1, "last_page": 4}], 3, False),
    ],
)
def test_extraction_scope_requires_all_pages_to_be_in_declared_parts(parts, count, expected):
    member = {
        "page_count": count,
        "parse": {"status": "frozen"},
        "parts": parts,
    }
    assert _full_page_parts(member) is expected


def test_exact_binding_contract_does_not_change_legacy_or_prove_completeness():
    legacy = package_requirement_inventory()
    exact = package_requirement_inventory("bid-package-requirements/2")
    assert valid("PackageRequirementInventoryManifest", legacy)
    assert valid("PackageRequirementInventoryManifest", exact)

    forged_complete = deepcopy(exact)
    forged_complete["inventory_complete"] = True
    assert not valid("PackageRequirementInventoryManifest", forged_complete)
    forged_quality = deepcopy(exact)
    forged_quality["extraction_quality_status"] = "complete"
    assert not valid("PackageRequirementInventoryManifest", forged_quality)
    forged_binding = deepcopy(exact)
    forged_binding["extraction_binding"] = "unproven_legacy_rule_set"
    assert not valid("PackageRequirementInventoryManifest", forged_binding)
