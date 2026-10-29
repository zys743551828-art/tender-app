"""Synthetic counterexamples for summary meaning and observation-bound cursors."""
# ruff: noqa: F401,F811

import base64
import json
from copy import deepcopy

import pytest
from test_package_review_decisions import case, make, report, uid

from packages.contracts import work_context_api as contract
from packages.domain.package_review_decisions import binding
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError, secret_hash
from packages.work_contexts import cursors, policy, service


def human(run, decision=None):
    return {
        **binding(run),
        "items": [
            {
                "requirement_id": row["requirement_id"],
                "row_digest": digest(row),
                "current": (
                    {
                        **{
                            key: decision["manifest"][key]
                            for key in (
                                "id",
                                "sequence_no",
                                "actor_id",
                                "created_at",
                                "state",
                                "reason",
                            )
                        },
                        "digest": decision["digest"],
                    }
                    if decision
                    else None
                ),
            }
            for row in run["result"]["manifest"]["matrix"]
        ],
    }


def test_full_scope_counts_and_human_opinions_do_not_invent_whole_package_clearance(case, report):
    original = deepcopy(report)
    unchecked = policy.review_summary(report, case["payload"], human(report))
    assert unchecked["machine_counts"]["satisfied"] == unchecked["requirement_count"] == 1
    assert unchecked["human_counts"]["unreviewed"] == 1
    checked = policy.review_summary(report, case["payload"], human(report, make(report)))
    assert checked["machine_counts"] == unchecked["machine_counts"]
    assert checked["human_counts"]["confirmed"] == 1
    assert checked["human_heads_digest"] != unchecked["human_heads_digest"]
    assert checked["overall_coverage"] == "partial"
    assert not checked["inventory_complete"] and not checked["risk_resolution_assessed"]
    result = policy.summary(checked)
    assert result["whole_package_blocking_risk_count"] is result["whole_package_passed"] is None
    assert result["formal_scoring"]["numeric_prediction"] is None
    assert not result["official_labels_read"]
    assert result["action_mode"] == "navigation_only"
    assert report == original


@pytest.mark.parametrize(
    "mutation",
    ["counts", "coverage", "duplicate", "definition", "ranges", "documents", "limitations"],
)
def test_resealed_native_result_cannot_forge_a_scoped_summary(case, report, mutation):
    result = report["result"]["manifest"]
    if mutation == "counts":
        result["counts"]["satisfied"] = 0
        result["counts"]["violated"] = 1
    elif mutation == "coverage":
        result["matrix_coverage"] = "partial"
    elif mutation == "duplicate":
        result["matrix"].append(deepcopy(result["matrix"][0]))
        result["requirement_count"] += 1
        result["counts"]["satisfied"] += 1
    elif mutation == "definition":
        result["matrix"][0]["rule_kind"] = "scoring"
    elif mutation == "ranges":
        result["matrix"][0]["inspected_ranges"] = []
    elif mutation == "documents":
        result["submitted_documents"][0]["document_version_id"] = uid(9999)
    else:
        result["limitations"] = []
    report["result"]["digest"] = digest(result)
    with pytest.raises(DomainError):
        policy.review_summary(report, case["payload"], human(report))


@pytest.mark.parametrize("field", ["run_id", "result_digest", "row_digest", "missing", "duplicate"])
def test_human_observations_cannot_cross_result_or_silently_omit_rows(case, report, field):
    value = human(report)
    if field == "run_id":
        value[field] = uid(9999)
    elif field == "result_digest":
        value[field] = "0" * 64
    elif field == "row_digest":
        value["items"][0][field] = "0" * 64
    elif field == "missing":
        value["items"] = []
    else:
        value["items"] *= 2
    with pytest.raises(DomainError):
        policy.review_summary(report, case["payload"], value)


def test_missing_result_is_unknown_and_later_report_requires_explicit_submitted_binding():
    no_run = policy.summary(None, submission=True)
    unfinished_bound = policy.summary(None, submission=True, bound_missing=True)
    pending = policy.summary(None)
    assert no_run["review_status"] == "not_selected"
    assert unfinished_bound["review_status"] == "bound_result_missing"
    assert pending["review_status"] == "run_unfinished"
    assert all(
        value["review"] is None and value["whole_package_blocking_risk_count"] is None
        for value in (no_run, unfinished_bound, pending)
    )


def test_later_completed_report_never_fills_a_missing_submission_result(case, report):
    completed = policy.review_summary(report, case["payload"], human(report))
    bound = deepcopy(report)
    bound["result"] = None
    assert policy.submission_review(bound, completed) is None
    assert policy.submission_review(None, completed) is None
    assert policy.submission_review(report, completed) == completed


@pytest.mark.parametrize("field", ["run_id", "input_digest", "result_digest"])
def test_bound_submission_cannot_use_another_review_summary(case, report, field):
    completed = policy.review_summary(report, case["payload"], human(report))
    completed[field] = uid(9999) if field == "run_id" else "0" * 64
    with pytest.raises(DomainError):
        policy.submission_review(report, completed)


def test_contract_remains_closed_and_never_accepts_a_formal_numeric_prediction(case, report):
    value = policy.summary(policy.review_summary(report, case["payload"], human(report)))
    assert contract.valid("WorkContextSummary", value)
    value["formal_scoring"]["numeric_prediction"] = 0
    assert not contract.valid("WorkContextSummary", value)
    value["formal_scoring"]["numeric_prediction"] = None
    value["official_score"] = "100"
    assert not contract.valid("WorkContextSummary", value)


def test_cursor_distinguishes_foreign_scope_tamper_and_changed_observation(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "explicit-synthetic-work-context-cursor-secret")
    scope, observation, last = (digest(key) for key in ("scope", "observation", "last"))
    token = cursors.encode(scope, observation, last)
    assert cursors.decode(token, scope, observation) == last
    for bad in (token + "x", "", token.split(".")[0], "A" * 4097):
        with pytest.raises(DomainError) as error:
            cursors.decode(bad, scope, observation)
        assert error.value.code == "WORK_CONTEXT_CURSOR_INVALID"
    with pytest.raises(DomainError) as error:
        cursors.decode(token, digest("other project"), observation)
    assert error.value.code == "WORK_CONTEXT_CURSOR_INVALID"
    with pytest.raises(DomainError) as error:
        cursors.decode(token, scope, digest("source or relationship changed"))
    assert error.value.code == "WORK_CONTEXT_OBSERVATION_CHANGED"


@pytest.mark.parametrize("raw", ['{"version":1,"version":1}', '{"version":true}', "[]"])
def test_even_signed_cursor_must_have_closed_nonduplicate_keys(monkeypatch, raw):
    monkeypatch.setenv("SESSION_SECRET", "explicit-synthetic-work-context-cursor-secret")
    token = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    signed = token + "." + secret_hash("work-context-cursor/1:" + token)
    with pytest.raises(DomainError) as error:
        cursors.decode(signed, digest("scope"), digest("observation"))
    assert error.value.status == 422


@pytest.mark.parametrize("value", [None, "", "latest", "00000000000000000000000000000001", 1])
def test_no_implicit_or_noncanonical_identity_is_accepted(value):
    with pytest.raises(DomainError) as error:
        service.request_ids(uid(1), value)
    assert error.value.status == 422
