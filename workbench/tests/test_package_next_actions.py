"""Adverse selected-run priorities; human agreement never closes machine risks."""
# ruff: noqa: F401,F811

from copy import deepcopy

import pytest
from test_package_review_decisions import case, make, report, request, uid
from test_work_contexts import human

from packages.contracts import package_next_actions as contract
from packages.contracts import work_context_api as context_contract
from packages.domain import package_next_actions as actions
from packages.domain import package_scope_review as review
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError
from packages.work_contexts import policy


@pytest.fixture
def scenario(case, report):
    def build(definitions=(("mandatory", "satisfied"),), *, changed=None, pending=True):
        run, payload = deepcopy(report), deepcopy(case["payload"])
        prototype = deepcopy(payload["requirements"][0])
        original = deepcopy(run["result"]["manifest"]["matrix"][0])
        payload["requirements"] = []
        matrix = []
        confirmations = {}
        for index, (kind, verdict) in enumerate(definitions):
            rid = uid(2000 + index)
            req = deepcopy(prototype)
            req["requirement_id"] = req["rule"]["id"] = req["requirement"]["requirement_id"] = rid
            req["rule"]["kind"] = kind
            req["rule_digest"] = digest(req["rule"])
            req["requirement_digest"] = digest(req["requirement"])
            payload["requirements"].append(req)
            row = deepcopy(original)
            row.update(
                requirement_id=rid,
                rule_kind=kind,
                verdict=verdict,
                rule_digest=req["rule_digest"],
                requirement_digest=req["requirement_digest"],
            )
            matrix.append(row)
            if kind in actions.CRITICAL:
                confirmations[rid] = "pending" if pending else "confirmed"
        result = review.result_manifest(run["id"], case["manifest"], payload, matrix)
        result["input_digest"] = run["input_digest"]
        run["result"] = {"manifest": result, "digest": digest(result)}
        observations = {
            key: policy.dimension("matched", "EXACT_MATCH", "a" * 64, "a" * 64)
            for key in context_contract.DIMENSIONS
        }
        for key in ("review_run_head", "submission_head", "bound_run_state"):
            observations[key] = policy.dimension("not_applicable", "NO_NATIVE_HEAD")
        if changed:
            observations[changed] = policy.dimension("changed", "INPUT_CHANGED", "a" * 64, "b" * 64)
        return {
            "run": run,
            "payload": payload,
            "human": human(run),
            "observations": observations,
            "phase": "working",
            "archived_at": None,
            "accept_rules_as_written": False,
            "confirmations": confirmations,
            "method_digest": "e" * 64,
            "confirmation_digest": "f" * 64,
            "observed_at": "2026-10-23T00:00:00.000000Z",
        }

    return build


def test_priority_and_remaining_counts_are_unique_rows_not_sum_of_overlapping_groups(scenario):
    values = scenario(
        (
            ("mandatory", "unable_to_judge"),
            ("disqualification", "violated"),
            ("mandatory", "satisfied"),
            ("scoring", "violated"),
            ("advisory", "violated"),
        )
    )
    old = deepcopy(values)
    value = actions.make(**values)
    assert value["primary"]["level"] == 2
    assert [item["level"] for item in value["other_actions"]] == [3, 4, 5, 6]
    assert value["current_scope_counts"] == {
        "critical": 2,
        "suggestions": 2,
        "pending_critical_rules": 3,
    }
    assert value["remaining_critical_count"] == value["remaining_suggestion_count"] == 2
    ids = [
        rid
        for action in [value["primary"], *value["other_actions"]]
        for rid in action["requirement_ids"]
    ]
    assert len(ids) == len(set(ids))
    assert values == old
    assert not any(
        value[key]
        for key in ("inventory_complete", "formal_scoring_eligible", "submission_eligible")
    )


@pytest.mark.parametrize("state", ["confirmed", "rejected", "needs_review"])
def test_human_agreement_or_disagreement_never_resolves_the_original_critical_verdict(
    scenario, state
):
    values = scenario((("mandatory", "violated"),), pending=False)
    decision = make(values["run"], request(values["run"], state=state))
    values["human"] = human(values["run"], decision)
    value = actions.make(**values)
    assert value["primary"]["key"] == "inspect_critical_risks"
    assert value["current_scope_counts"]["critical"] == 1
    assert value["binding"]["result_digest"] == values["run"]["result"]["digest"]


@pytest.mark.parametrize(
    "dimension",
    [
        "identity",
        "package_head",
        "authority_head",
        "inventory_head",
        "rule_set_head",
        "sources",
        "selected_facts",
        "executor_method",
    ],
)
def test_changed_basis_hides_current_counts_but_retains_separately_labelled_history(
    scenario, dimension
):
    value = actions.make(**scenario((("mandatory", "violated"),), changed=dimension))
    assert value["basis_status"] == "changed" and value["primary"]["level"] == 1
    assert value["current_scope_counts"] is value["remaining_critical_count"] is None
    assert value["historical_scope_counts"]["critical"] == 1
    assert value["other_actions"] == []


def test_unavailable_required_identity_is_not_treated_as_a_match(scenario):
    values = scenario()
    values["observations"]["sources"] = policy.dimension("not_applicable", "NOT_OBSERVED")
    value = actions.make(**values)
    assert value["basis_status"] == "unknown"
    assert value["current_scope_counts"] is None


def test_current_rule_confirmation_changes_recommendation_without_rewriting_the_result(scenario):
    values = scenario()
    original = deepcopy(values["run"])
    before = actions.make(**values)
    assert before["primary"]["key"] == "confirm_critical_rules"
    values["confirmations"] = dict.fromkeys(values["confirmations"], "confirmed")
    after = actions.make(**values)
    assert after["primary"]["key"] == "inspect_package_limitations"
    assert after["basis_digest"] != before["basis_digest"] and values["run"] == original
    assert after["current_scope_counts"]["pending_critical_rules"] == 0


def test_explicit_original_rule_acceptance_suppresses_only_confirmation_prompt(scenario):
    values = scenario((("mandatory", "violated"),))
    values["accept_rules_as_written"] = True
    value = actions.make(**values)
    assert value["current_scope_counts"]["pending_critical_rules"] == 0
    assert value["primary"]["key"] == "inspect_critical_risks"
    assert value["current_scope_counts"]["critical"] == 1


@pytest.mark.parametrize("state", ["queued", "running", "cancel_requested", "failed", "cancelled"])
def test_unfinished_run_never_fills_zero_counts_or_uses_another_report(scenario, state):
    values = scenario()
    values["run"]["result"] = None
    values["run"]["operation"]["state"] = state
    if state in {"queued", "running", "cancel_requested"}:
        values["run"]["operation"]["finished_at"] = None
    values["human"] = None
    value = actions.make(**values)
    assert value["current_scope_counts"] is value["historical_scope_counts"] is None
    assert value["primary"]["level"] == 2


def test_archived_scope_is_history_and_never_recommends_a_fresh_write(scenario):
    values = scenario((("mandatory", "violated"),))
    values["phase"] = "closed"
    value = actions.make(**values)
    assert value["basis_status"] == "archived" and value["primary"]["key"] == "view_archived_run"
    assert value["current_scope_counts"] is None and value["action_mode"] == "navigation_only"


@pytest.mark.parametrize(
    "mutation",
    ["human", "malformed_head", "confirmation_missing", "observation_missing", "row_definition"],
)
def test_partial_or_cross_result_inputs_cannot_supply_recommendation_counts(scenario, mutation):
    values = scenario()
    if mutation == "human":
        values["human"]["result_digest"] = "f" * 64
    elif mutation == "malformed_head":
        values["human"]["items"][0]["current"] = {"state": "confirmed"}
    elif mutation == "confirmation_missing":
        values["confirmations"] = {}
    elif mutation == "observation_missing":
        del values["observations"]["sources"]
    else:
        values["payload"]["requirements"][0]["rule"]["kind"] = "advisory"
    with pytest.raises(DomainError):
        actions.make(**values)


@pytest.mark.parametrize("accepted,status", [(False, "unknown"), (True, "matched")])
def test_unavailable_current_confirmation_stays_unknown_unless_explicit_original_rule_policy_applies(
    scenario, accepted, status
):
    values = scenario()
    values["confirmations"] = dict.fromkeys(values["confirmations"], "unknown")
    values["accept_rules_as_written"] = accepted
    value = actions.make(**values)
    assert value["basis_status"] == status
    assert (value["current_scope_counts"] is None) is (not accepted)
    assert not value["submission_eligible"]


def test_succeeded_run_missing_its_result_cannot_be_projected_as_processing(scenario):
    values = scenario()
    values["run"]["result"] = None
    values["human"] = None
    with pytest.raises(DomainError):
        actions.make(**values)
