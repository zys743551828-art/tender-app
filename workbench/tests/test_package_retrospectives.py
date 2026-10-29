"""No database or paid services: explicit scope and honest retrospective contracts."""

from copy import deepcopy
from uuid import UUID

import pytest

from packages.contracts import package_retrospectives_api as contract
from packages.domain.runtime import DomainError
from packages.retrospectives import policy


def identity(n):
    return str(UUID(int=n))


def missing():
    return {
        "submission_id": identity(1),
        "outcome_id": None,
        "outcome_missing_reason": "官方总分原件待补",
        "business_result_id": None,
        "business_result_missing_reason": "阶段结果待核",
        "baseline_run_id": None,
        "submitted_run_id": None,
        "reviews_missing_reason": "第二轮核查待执行",
    }


def test_missing_records_are_explicit_not_inferred_or_zero_filled():
    chosen = missing()
    result = policy.selection(chosen)
    assert result == chosen and result is not chosen
    assert result["outcome_id"] is None and result["business_result_id"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"outcome_missing_reason": None},
        {"outcome_id": identity(2)},
        {"business_result_missing_reason": None},
        {"baseline_run_id": identity(2)},
        {
            "baseline_run_id": identity(2),
            "submitted_run_id": identity(2),
            "reviews_missing_reason": None,
        },
        {"baseline_run_id": identity(2), "submitted_run_id": identity(3)},
        {"submission_id": "latest"},
        {"outcome_missing_reason": "  "},
        {"allow_latest": True},
    ],
)
def test_ambiguous_selection_and_missing_reason_are_rejected(change):
    with pytest.raises(DomainError) as failure:
        policy.selection(missing() | change)
    assert failure.value.status == 422


def test_two_distinct_runs_and_records_need_no_absence_story():
    value = missing() | {
        "outcome_id": identity(2),
        "outcome_missing_reason": None,
        "business_result_id": identity(3),
        "business_result_missing_reason": None,
        "baseline_run_id": identity(4),
        "submitted_run_id": identity(5),
        "reviews_missing_reason": None,
    }
    assert policy.selection(value) == value


def test_explicit_handoff_is_closed_and_cannot_request_publication_or_samples():
    body = {"retrospective_digest": "a" * 64, "reason": "明确建立待核知识候选"}
    assert contract.valid("PackageRetrospectiveKnowledgeRequest", body)
    for field in ("publish", "sample_eligible", "model_qualified", "risk_resolved"):
        assert not contract.valid("PackageRetrospectiveKnowledgeRequest", body | {field: True})
    assert not contract.valid("PackageRetrospectiveKnowledgeRequest", body | {"reason": " "})


def test_openapi_only_adds_implemented_routes_with_resolved_contracts():
    document = {
        "paths": {contract.BASE: {"post": {"responses": {}}}},
        "components": {"schemas": {}},
    }
    contract.extend_openapi(document)
    assert set(document["paths"]) == {contract.BASE}
    operation = document["paths"][contract.BASE]["post"]
    assert operation["security"] == [{"SessionCookie": []}]
    assert operation["responses"]["201"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "PackageRetrospectiveApplied"
    )

    def check_refs(value):
        if isinstance(value, dict):
            if "$ref" in value:
                assert value["$ref"].split("/")[-1] in document["components"]["schemas"]
            for child in value.values():
                check_refs(child)
        elif isinstance(value, list):
            for child in value:
                check_refs(child)

    check_refs(deepcopy(document))
