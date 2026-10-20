"""Synthetic comparison ports; real nonowner sources/heads are covered by PG integration."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator
from test_package_fact_scope import case as scope_case

from packages.domain import package_fact_admission as policy
from packages.domain import package_fact_scope as declarations
from packages.domain import package_fact_usage as usage_policy
from packages.domain.bid_package_fact_scope_repository import head
from packages.domain.package_execution_input import PreparedExecutionInput
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError


@pytest.fixture
def case():
    source = scope_case.__wrapped__()
    current = source["current"]
    cm = current["context"]["manifest"]
    facts = cm["facts"]
    facts["items"][0]["decision"]["created_at"] = "2026-10-20T00:00:00.000000Z"
    cm["facts_digest"] = digest(facts)
    semantic = digest({k: v for k, v in cm.items() if k != "as_of"})
    current["context"]["semantic_digest"] = current["binding"]["context_digest"] = semantic
    current["context"]["snapshot_digest"] = digest(cm)
    current["result"]["current_context"]["semantic_digest"] = semantic
    current["result"]["current_context"]["snapshot_digest"] = digest(cm)
    old = source["packet"]
    public = {
        "id": old.input_id,
        "identity": {"binding": current["binding"]},
        "execution_context": {
            "fact_set_id": facts["head"]["fact_set_id"],
            "facts_digest": cm["facts_digest"],
            "fact_count": 1,
        },
    }
    packet = PreparedExecutionInput(
        old.scope,
        old.frozen_id,
        old.input_id,
        old.digest,
        json.dumps({"manifest": public}),
        json.dumps(current | {"version": "package-review-prepared-snapshot/1"}),
    )
    record = declarations.declare(
        packet, current, source["fact_id"], source["proof"], source["subject"], **source["audit"]
    )
    usage = usage_policy.select(
        packet, {"purpose": "prebid_compliance", "fact_ids": [source["fact_id"]]}
    )
    return {
        "usage": usage,
        "current_identity": cm["identity"],
        "current_items": {source["fact_id"]: facts["items"][0]},
        "declarations": {source["fact_id"]: record},
        "proofs": {source["fact_id"]: source["proof"]},
        "policy_digest": "c" * 64,
        "checked_at": "2026-10-20T00:02:00.000000Z",
    }


def test_complete_selected_proof_admits_only_chosen_facts_at_observation(case):
    Draft202012Validator.check_schema(policy.SCHEMA)
    result = policy.admit(**case)
    m = result.view()["manifest"]
    assert (
        m["selected_count"] == 1
        and m["admission"] == "verified_for_selected_use"
        and m["facts_qualified"] is True
    )
    assert m["required_facts_assessment"] == "not_performed"
    assert all(
        m[key] is False for key in ("review_ready", "launch_available", "publication_authorized")
    )
    assert "amount" not in str(result.view()) + repr(result)
    items = result.selected_items()
    items.clear()
    assert len(result.selected_items()) == 1
    view = result.view()
    view["manifest"]["fact_declarations"].clear()
    assert len(result.view()["manifest"]["fact_declarations"]) == 1
    assert case["usage"].view()["manifest"]["facts_qualified"] is False


def test_empty_usage_needs_no_company_confirmation_and_never_proves_no_required_facts(case):
    # The supplied usage is a verified private projection with no selected facts.
    usage = case["usage"]
    view = usage.view()
    m = view["manifest"]
    m["selected"] = []
    m["selected_facts_digest"] = digest([])
    selection = {
        "version": "package-fact-usage-content/1",
        "purpose": m["purpose"],
        "scope": {
            k: m["prepared"][k] for k in ("bid_id", "package_id", "revision_id", "inventory_id")
        },
        "identity_digest": m["identity_digest"],
        "selected": [],
    }
    m["selection_digest"] = digest(selection)
    empty = usage_policy.SelectedPreparedFacts(
        digest(m), json.dumps(m), "[]", json.dumps(usage.prepared_authority())
    )
    result = policy.admit(empty, None, {}, {}, {}, case["policy_digest"], case["checked_at"])
    assert result.view()["manifest"]["admission"] == "not_used"
    assert result.view()["manifest"]["facts_qualified"] is False
    assert result.view()["manifest"]["required_facts_assessment"] == "not_performed"


@pytest.mark.parametrize(
    "change",
    [
        "missing_fact",
        "extra_fact",
        "fact_value",
        "missing_scope",
        "withdrawn",
        "proof_binding",
        "ineffective",
        "quality",
        "identity",
        "scope_subject",
        "scope_digest",
        "future_scope",
        "old_time",
    ],
)
def test_each_current_dependency_or_scope_failure_denies_admission(case, change):
    fact_id = next(iter(case["current_items"]))
    item = case["current_items"][fact_id]
    head = case["declarations"][fact_id]
    proof = case["proofs"][fact_id]
    if change == "missing_fact":
        case["current_items"].clear()
    if change == "extra_fact":
        case["current_items"]["unselected"] = deepcopy(item)
    if change == "fact_value":
        item["fact"]["value_jsonb_text"] = "2"
    if change == "missing_scope":
        case["declarations"][fact_id] = None
    if change == "withdrawn":
        case["declarations"][fact_id] = declarations.withdraw(
            head,
            record_id="00000000-0000-4000-8000-000000000999",
            actor_id=head["manifest"]["actor_id"],
            command_id=head["manifest"]["command_id"],
            recorded_at=case["checked_at"],
            reason="撤回",
        )
    if change == "proof_binding":
        proof["decision_binding"] = False
    if change == "ineffective":
        proof["sources_effective"] = False
    if change == "quality":
        proof["evidence_usable"] = False
    if change == "identity":
        case["current_identity"]["bidder_id"] = "00000000-0000-4000-8000-000000000999"
    if change == "scope_subject":
        head["manifest"]["subject"]["id"] = "00000000-0000-4000-8000-000000000999"
        head["digest"] = digest(head["manifest"])
    if change == "scope_digest":
        head["manifest"]["binding"]["proof_digest"] = "f" * 64
        head["digest"] = digest(head["manifest"])
    if change == "future_scope":
        head["manifest"]["recorded_at"] = "2026-10-21T00:00:00.000000Z"
        head["digest"] = digest(head["manifest"])
    if change == "old_time":
        case["checked_at"] = "2026-10-19T00:00:00.000000Z"
    with pytest.raises(ValueError):
        policy.admit(**case)


def test_time_refresh_preserves_content_identity_but_not_observation_receipt(case):
    old = policy.admit(**case)
    case["checked_at"] = "2026-10-20T00:03:00.000000Z"
    fresh = policy.admit(**case)
    assert fresh.digest != old.digest
    assert fresh.view()["manifest"]["content_digest"] == old.view()["manifest"]["content_digest"]
    assert fresh._proof_text == old._proof_text


def test_new_scope_head_and_policy_version_create_new_admission_content(case):
    old = policy.admit(**case)
    fact_id = next(iter(case["declarations"]))
    record = case["declarations"][fact_id]
    record["manifest"]["id"] = "00000000-0000-4000-8000-000000000999"
    record["digest"] = digest(record["manifest"])
    assert (
        policy.admit(**case).view()["manifest"]["content_digest"]
        != old.view()["manifest"]["content_digest"]
    )
    case["policy_digest"] = "d" * 64
    assert policy.admit(**case).view()["manifest"]["policy_digest"] == "d" * 64


def test_corrupt_stored_head_is_server_integrity_failure():
    c = SimpleNamespace(
        execute=lambda *args: SimpleNamespace(
            fetchall=lambda: [{"manifest": {}, "digest": "0" * 64}]
        )
    )
    with pytest.raises(DomainError) as error:
        head(c, "bid", "prepared", "fact")
    assert error.value.code == "PACKAGE_FACT_SCOPE_CORRUPT" and error.value.status == 500
