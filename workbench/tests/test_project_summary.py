"""Directory completeness is not review completeness, zero risk or qualified prediction."""

from copy import deepcopy
from uuid import uuid4

import pytest

from packages.contracts.project_summary_api import validate
from packages.domain.project_summary import project
from packages.domain.runtime import DomainError


def row(**changes):
    return {
        "id": uuid4(),
        "phase": "working",
        "archived_at": None,
        "authority_count": 1,
        "bid_count": 1,
        "member_count": 3,
        "not_frozen_members": 0,
        "invalid_heads": 0,
    } | changes


@pytest.mark.parametrize(
    "changes,action",
    [
        ({}, "choose_package_revision"),
        ({"bid_count": 0}, "assemble_packages"),
        ({"authority_count": 0}, "assemble_packages"),
        ({"not_frozen_members": 1}, "inspect_package_parses"),
        ({"phase": "closed"}, "view_history"),
        ({"phase": "terminated"}, "view_history"),
        ({"archived_at": "2026-10-23T00:00:00Z"}, "view_history"),
    ],
)
def test_directory_action_never_implies_qualified_risk_or_score(changes, action):
    source = row(**changes)
    before = deepcopy(source)
    value = project(source)
    assert value["next_action"]["action"] == action
    assert (
        value["critical_risk_count"]
        is value["other_risk_count"]
        is value["predicted_score"]
        is None
    )
    assert value["risk_status"] == value["prediction_status"] == "not_evaluated"
    assert not any(
        value[key]
        for key in ("inventory_complete", "formal_scoring_eligible", "submission_eligible")
    )
    assert value["next_action"]["target_url"].startswith(f"/bids/{source['id']}/")
    assert before == source


@pytest.mark.parametrize(
    "field",
    [
        "critical_risk_count",
        "other_risk_count",
        "predicted_score",
        "inventory_complete",
        "formal_scoring_eligible",
        "submission_eligible",
    ],
)
def test_false_green_or_zero_is_rejected_by_the_closed_contract(field):
    value = project(row())
    value[field] = True if field.endswith(("eligible", "complete")) else 0
    with pytest.raises(DomainError, match="项目摘要"):
        validate("ProjectWorkSummary", value)


def test_inconsistent_head_is_an_error_instead_of_an_empty_directory():
    with pytest.raises(DomainError) as caught:
        project(row(invalid_heads=1))
    assert caught.value.code == "PROJECT_SUMMARY_PACKAGE_HEAD_INVALID"
