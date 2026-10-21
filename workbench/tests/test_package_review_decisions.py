"""Synthetic immutable reports verify human-opinion bindings, never factual qualification."""
# ruff: noqa: F401,F811

from copy import deepcopy

import pytest
from test_package_scope_review import case, response, uid

from packages.contracts.package_review_decisions_api import valid
from packages.contracts.package_review_runs_api import valid as run_valid
from packages.domain import package_review_decisions as decisions
from packages.domain import package_scope_review as review
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError


@pytest.fixture
def report(case):
    manifest = case["manifest"]
    batch = review.batches(case["payload"])[0]
    matrix = review.validate_batch(batch, response(batch))
    result = review.result_manifest(uid(50), manifest, case["payload"], matrix)
    timestamp = "2026-10-21T01:00:00.000000Z"
    run = {
        "kind": "package_review_run",
        "id": uid(50),
        "actor_id": uid(60),
        "created_at": timestamp,
        "scope": manifest["scope"],
        "frozen_input_id": manifest["frozen_input"]["id"],
        "frozen_input_digest": manifest["frozen_input"]["digest"],
        "execution_input_id": manifest["execution_input"]["id"],
        "execution_input_digest": manifest["execution_input"]["digest"],
        "execution_digest": manifest["execution_input"]["identity"]["execution_digest"],
        "dependency_plan_id": manifest["dependency_plan"]["id"],
        "dependency_plan_digest": manifest["dependency_plan"]["digest"],
        "input_digest": digest(manifest),
        "method_digest": manifest["executor_method"]["digest"],
        "operation": {
            "id": uid(51),
            "kind": "package-scope-review",
            "state": "succeeded",
            "input_digest": digest(manifest),
            "handler_version": review.HANDLER,
            "error_code": None,
            "created_at": timestamp,
            "finished_at": timestamp,
        },
        "result": {"manifest": result, "digest": digest(result)},
    }
    assert run_valid("PackageReviewRunView", run)
    return run


def request(report, *, expected=None, state="confirmed"):
    row = report["result"]["manifest"]["matrix"][0]
    return {
        "result_digest": report["result"]["digest"],
        "row_digest": digest(row),
        "expected_head": expected,
        "state": state,
        "reason": "合成人工意见：已逐字核对原引用，并保留本次判断的适用边界。",
        "selected_quotes": deepcopy(row["target_quotes"] + row["authority_quotes"]),
    }


def make(report, body=None, **overrides):
    return decisions.make(
        report,
        report["result"]["manifest"]["matrix"][0]["requirement_id"],
        request(report) if body is None else body,
        **{
            "decision_id": uid(70),
            "actor_id": uid(60),
            "created_at": "2026-10-21T01:00:01.000000Z",
            "sequence_no": 1,
            **overrides,
        },
    )


@pytest.mark.parametrize("state", ["confirmed", "rejected", "needs_review"])
def test_human_states_bind_original_row_without_changing_machine_or_qualification(report, state):
    old = deepcopy(report)
    value = make(report, request(report, state=state))
    assert valid("PackageReviewHumanDecisionView", value)
    assert value["manifest"]["state"] == state
    assert value["manifest"]["row_digest"] == digest(report["result"]["manifest"]["matrix"][0])
    assert not any(value["manifest"][flag] for flag in decisions.FLAGS)
    assert report == old
    assert report["result"]["manifest"]["matrix"][0]["human_review_state"] == "unreviewed"
    assert report["result"]["manifest"]["overall_coverage"] == "partial"


def test_human_opinion_may_have_no_selected_quote_but_always_needs_reason(report):
    body = request(report, state="needs_review") | {"selected_quotes": []}
    value = make(report, body)
    assert value["manifest"]["selected_quotes"] == []
    with pytest.raises(DomainError) as error:
        make(report, body | {"reason": " \n\t "})
    assert error.value.code == "PACKAGE_REVIEW_DECISION_REASON_REQUIRED"


@pytest.mark.parametrize("field", ["result_digest", "row_digest"])
def test_different_report_or_row_digest_is_not_a_human_decision_basis(report, field):
    with pytest.raises(DomainError) as error:
        make(report, request(report) | {field: "0" * 64})
    assert error.value.code == "PACKAGE_REVIEW_DECISION_BASIS_CHANGED"


@pytest.mark.parametrize(
    "field,value",
    [
        ("package_role", "authority"),
        ("member_id", "foreign-member"),
        ("evidence_id", uid(999)),
        ("document_version_id", uid(998)),
        ("parse_run_id", uid(997)),
        ("physical_page", 2),
        ("part_ids", ["another-part"]),
        ("evidence_digest", "0" * 64),
        ("quote", "工期为 95 日历天"),
    ],
)
def test_human_selected_evidence_must_be_an_exact_original_quote(report, field, value):
    body = request(report)
    body["selected_quotes"][0][field] = value
    with pytest.raises(DomainError) as error:
        make(report, body)
    assert error.value.code == "PACKAGE_REVIEW_DECISION_EVIDENCE_INVALID"


@pytest.mark.parametrize(
    "change", ["duplicate_quote", "unknown_state", "extra_flag", "long_reason", "head"]
)
def test_human_request_shape_is_closed_and_bounded(report, change):
    body = request(report)
    if change == "duplicate_quote":
        body["selected_quotes"] *= 2
    elif change == "unknown_state":
        body["state"] = "resolved"
    elif change == "extra_flag":
        body["formal_scoring_eligible"] = True
    elif change == "long_reason":
        body["reason"] = "意" * 2001
    else:
        body["expected_head"] = {"id": uid(72)}
    with pytest.raises(DomainError) as error:
        make(report, body)
    assert error.value.code == "PACKAGE_REVIEW_DECISION_INVALID"


@pytest.mark.parametrize(
    "field",
    [
        "run_id",
        "requirement_id",
        "input_digest",
        "row_digest",
        "result_digest",
        "formal_scoring_eligible",
    ],
)
def test_rehashed_stored_decision_cannot_cross_identity_or_grant_qualification(report, field):
    value = make(report)
    value["manifest"][field] = (
        True
        if field == "formal_scoring_eligible"
        else uid(998)
        if field.endswith("_id")
        else "0" * 64
    )
    value["digest"] = digest(value["manifest"])
    with pytest.raises(DomainError) as error:
        decisions.check(value, report)
    assert error.value.code == "PACKAGE_REVIEW_DECISION_CORRUPT"


def test_pending_run_cannot_be_human_reviewed(report):
    report["result"] = None
    report["operation"]["state"] = "running"
    with pytest.raises(DomainError) as error:
        decisions.binding(report)
    assert error.value.code == "PACKAGE_REVIEW_RESULT_UNAVAILABLE"


def test_human_chain_is_explicit_and_defensive_copies_preserve_original(report):
    first = make(report)
    expected = {"id": first["manifest"]["id"], "digest": first["digest"]}
    body = request(report, expected=expected, state="rejected")
    second = make(report, body, decision_id=uid(71), sequence_no=2)
    assert second["manifest"]["previous_head"] == expected
    body["selected_quotes"].clear()
    assert second["manifest"]["selected_quotes"]
    assert first["manifest"]["previous_head"] is None
