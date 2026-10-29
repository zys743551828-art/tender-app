"""Task content and rerun identity vectors, without database/provider authorization."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from packages.domain.package_review_execution_identity import SCHEMA, identify, verify


def binding():
    return {
        **{
            key: f"00000000-0000-4000-8000-{number:012d}"
            for number, key in enumerate(
                ("bid_id", "package_id", "revision_id", "inventory_id", "frozen_input_id"), 1
            )
        },
        **{
            key: str(number) * 64
            for number, key in enumerate(
                (
                    "identity_digest",
                    "frozen_digest",
                    "input_digest",
                    "evidence_digest",
                    "context_digest",
                    "method_digest",
                    "policy_digest",
                ),
                1,
            )
        },
        "purpose": "prebid_compliance",
    }


def test_schema_and_fixed_vectors():
    Draft202012Validator.check_schema(SCHEMA)
    vectors = json.loads(
        (Path(__file__).parent / "fixtures/package-review-execution-vectors.json").read_text(
            "utf-8"
        )
    )
    for vector in vectors:
        assert identify(vector["binding"], vector["rerun"]) == vector["expected"], vector["name"]
        assert verify(vector["expected"]) == vector["expected"]


def test_repeat_same_intent_is_stable_and_rerun_does_not_create_new_content():
    original = identify(binding())
    rerun = {"nonce": "00000000-0000-4000-8000-000000000099", "reason": "显式重跑核对"}
    again = identify(binding(), rerun)
    assert original == identify(dict(reversed(list(binding().items()))))
    assert again == identify(binding(), deepcopy(rerun))
    assert original["content_digest"] == again["content_digest"]
    assert original["execution_digest"] != again["execution_digest"]
    changed = rerun | {"reason": "另一明确原因"}
    assert identify(binding(), changed)["execution_digest"] != again["execution_digest"]


@pytest.mark.parametrize("field", [*binding().keys()][:-1])
def test_each_scope_or_frozen_or_semantic_binding_changes_both_identities(field):
    original = identify(binding())
    value = binding()
    value[field] = "00000000-0000-4000-8000-000000000999" if field.endswith("_id") else "a" * 64
    changed = identify(value)
    assert original["content_digest"] != changed["content_digest"]
    assert original["execution_digest"] != changed["execution_digest"]


@pytest.mark.parametrize(
    "invalid",
    [
        "missing",
        "body",
        "latest",
        "uppercase",
        "bad_uuid",
        "bad_sha",
        "newline_sha",
        "newline_id",
        "purpose",
        "grant",
        "as_of",
    ],
)
def test_rejects_incomplete_or_single_body_or_authorization_inputs(invalid):
    value = binding()
    if invalid == "missing":
        del value["frozen_input_id"]
    elif invalid == "body":
        value["body_version_id"] = value.pop("frozen_input_id")
    elif invalid == "latest":
        value["parse_run_id"] = "latest"
    elif invalid == "uppercase":
        value["context_digest"] = "A" * 64
    elif invalid == "bad_uuid":
        value["bid_id"] = "synthetic-bid"
    elif invalid == "bad_sha":
        value["frozen_digest"] = "0" * 63
    elif invalid == "newline_sha":
        value["frozen_digest"] += "\n"
    elif invalid == "newline_id":
        value["bid_id"] += "\n"
    elif invalid == "purpose":
        value["purpose"] = "formal_scoring"
    elif invalid == "grant":
        value["launch_available"] = True
    else:
        value["as_of"] = "2026-10-20T01:00:00Z"
    with pytest.raises(ValueError):
        identify(value)


@pytest.mark.parametrize(
    "intent",
    [
        {},
        {"nonce": "bad", "reason": "reason"},
        {"nonce": "00000000-0000-4000-8000-000000000099", "reason": "   "},
        {"nonce": "00000000-0000-4000-8000-000000000099", "reason": " padded "},
        {"nonce": "00000000-0000-4000-8000-000000000099", "reason": "x" * 2001},
    ],
)
def test_rerun_requires_explicit_nonce_and_reason(intent):
    with pytest.raises(ValueError):
        identify(binding(), intent)


@pytest.mark.parametrize("field", ["content_digest", "execution_digest", "binding", "extra"])
def test_persisted_identity_recomputes_instead_of_trusting_digest_shape(field):
    value = identify(binding())
    if field == "binding":
        value["binding"]["context_digest"] = "a" * 64
    elif field == "extra":
        value["publication_authorized"] = True
    else:
        value[field] = "a" * 64
    with pytest.raises(ValueError):
        verify(value)


def test_inputs_and_returned_identity_are_owned_copies():
    value = binding()
    rerun = {"nonce": "00000000-0000-4000-8000-000000000099", "reason": "显式重跑"}
    result = identify(value, rerun)
    original = deepcopy(result)
    value["context_digest"] = "a" * 64
    rerun["reason"] = "caller mutation"
    assert result == original
    rebuilt = verify(result)
    rebuilt["binding"].clear()
    assert result == original
