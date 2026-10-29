"""Provenance proof is deliberately narrower than semantic package applicability."""

import json
from copy import deepcopy

import pytest

from packages.contracts.bid_package_requirements_api import SCHEMAS
from packages.domain.fact_sets import identity
from packages.domain.package_fact_validation import CODES, assess
from packages.domain.runtime import sha


@pytest.fixture
def case():
    fact = {
        "id": "00000000-0000-4000-8000-000000000001",
        "subject": "same name is not identity",
        "scope": "free text scope",
        "name": "quantity",
        "value_jsonb_text": '{"amount": 1.25}',
        "unit": None,
        "evidence_ids": ["evidence"],
    }
    proof = {
        "decision_binding": True,
        "references": [{"evidence_id": "evidence", "source_revision": 1}],
        "closure": [{"status": "published", "revision": 1}],
        "sources_effective": True,
        "evidence_usable": True,
    }
    basis = {
        "fact_identity": identity({**fact, "value": {"amount": 1.25}}),
        "evidence": {
            "references": proof["references"],
            "source_closure_digest": sha(proof["closure"]),
        },
    }
    return {
        "fact": fact,
        "decision": {"decision": "confirmed"},
        "decision_basis_jsonb_text": json.dumps(basis),
        "scope_binding": "selected_frozen_parse",
    }, proof


def test_exact_valid_provenance_still_requires_explicit_scope_mapping(case):
    item, proof = case
    result = assess(item, proof)
    assert result["provenance_status"] == "verified"
    assert result["blockers"] == ["FACT_SCOPE_MAPPING_REQUIRED"]
    assert result["facts_qualified"] is False and result["scope_binding"] == "unproven"
    assert "quantity" not in str(result) and "1.25" not in str(result)


@pytest.mark.parametrize(
    "change,code",
    [
        ("decision", "FACT_DECISION_UNCONFIRMED"),
        ("binding", "FACT_DECISION_BINDING_UNPROVEN"),
        ("scope", "FACT_EVIDENCE_OUTSIDE_FROZEN_INPUT"),
        ("quality", "FACT_EVIDENCE_QUALITY_UNPROVEN"),
        ("closure", "FACT_SOURCE_BINDING_UNPROVEN"),
        ("refs", "FACT_SOURCE_BINDING_UNPROVEN"),
        ("effective", "FACT_SOURCE_NOT_EFFECTIVE"),
        ("fact", "FACT_DECISION_BASIS_UNPROVEN"),
    ],
)
def test_each_current_proof_change_invalidates_provenance(case, change, code):
    item, proof = deepcopy(case)
    if change == "decision":
        item["decision"] = None
    if change == "binding":
        proof["decision_binding"] = False
    if change == "scope":
        item["scope_binding"] = "unproven"
    if change == "quality":
        proof["evidence_usable"] = False
    if change == "closure":
        proof["closure"].append({"revision": 2})
    if change == "refs":
        proof["references"] = [{"evidence_id": "other"}]
    if change == "effective":
        proof["sources_effective"] = False
    if change == "fact":
        item["fact"]["value_jsonb_text"] = '{"amount":2}'
    result = assess(item, proof)
    assert result["provenance_status"] == "unproven" and code in result["blockers"]
    assert result["facts_qualified"] is False


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "null",
        "[]",
        '{"fact_identity":"x","fact_identity":"y"}',
        "NaN",
        '{"fact_identity":1,"evidence":{}}',
        "{broken",
    ],
)
def test_missing_duplicate_or_corrupt_decision_basis_is_not_proof(case, raw):
    item, proof = case
    item["decision_basis_jsonb_text"] = raw
    assert "FACT_DECISION_BASIS_UNPROVEN" in assess(item, proof)["blockers"]


@pytest.mark.parametrize("raw", ['{"amount":NaN}', '{"amount":1e999}', '{"amount":1,"amount":2}'])
def test_ambiguous_or_nonfinite_fact_values_do_not_get_provenance(case, raw):
    item, proof = case
    item["fact"]["value_jsonb_text"] = raw
    assert "FACT_DECISION_BASIS_UNPROVEN" in assess(item, proof)["blockers"]


def test_contract_and_policy_reason_codes_are_identical():
    assert SCHEMAS["PackageFactValidationItem"]["properties"]["blockers"]["items"]["enum"] == list(
        CODES[1:]
    )
