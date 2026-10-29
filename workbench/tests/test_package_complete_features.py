"""Three explicit /3 records; no provider dispatch, retry or scoring authority."""
# ruff: noqa: F811

from copy import deepcopy
from dataclasses import replace

import pytest
from test_package_technical_material import (  # noqa: F401
    bound,
    judgment,
    prepared,
    response,
    synthetic,
    uid,
)

from packages.domain.providers.deepseek_vision import parse_response
from packages.model_governance import package_complete_features as features
from packages.model_governance import package_technical_material as inputs


def attempt(bundle, slot, number=1, *, state="succeeded", data=None, call=None):
    request = prepared(bundle)
    generation = None
    if state == "succeeded":
        generation = parse_response(
            response(
                judgment(bundle) if data is None else data, id=f"synthetic-response-{slot}-{number}"
            ),
            f"synthetic-request-{slot}-{number}",
            request.receipt["request_digest"],
        )
    return features.CompleteJudgmentAttempt(
        uid(61), slot, number, uid(call or 1000 + slot * 10 + number), state, request, generation
    )


def aggregate(bundle, attempts):
    return features.aggregate_rule(
        bundle,
        uid(61),
        attempts,
        expected_input_digest=bundle.metadata["digest"],
        expected_method_digest=features.method_digest(),
    )


def test_three_distinct_valid_calls_produce_only_bound_votes(synthetic):
    bundle = bound(deepcopy(synthetic))
    rows = [attempt(bundle, slot) for slot in (1, 2, 3)]
    result = aggregate(bundle, rows)
    assert result["feature_coverage"] == "complete" and result["valid_slots"] == [1, 2, 3]
    assert result["features"]["band_votes"][0]["count"] == 3
    assert result["raw_numeric_total"] is None and result["formal_prediction"] is None
    assert result["native_binding_verified"] is False and result["training_eligible"] is False


@pytest.mark.parametrize("slots", [[], [1], [1, 2]])
def test_missing_slots_do_not_become_zero_votes_or_numeric_result(synthetic, slots):
    bundle = bound(deepcopy(synthetic))
    result = aggregate(bundle, [attempt(bundle, s) for s in slots])
    assert result["feature_coverage"] == "partial" and result["features"] is None
    assert result["missing_valid_slots"] == [s for s in (1, 2, 3) if s not in slots]


def test_known_semantic_failure_can_be_followed_by_explicit_new_attempt(synthetic):
    bundle = bound(deepcopy(synthetic))
    bad = judgment(bundle)
    bad["evidence"][0]["quote"] = "synthetic unsupported quote"
    rows = [
        attempt(bundle, 1, data=bad),
        attempt(bundle, 1, 2),
        attempt(bundle, 2),
        attempt(bundle, 3),
    ]
    result = aggregate(bundle, rows)
    assert result["feature_coverage"] == "complete" and result["attempt_count"] == 4
    assert result["attempts"][0]["semantic_rejection"] == "MATERIAL_INPUT_JUDGMENT_CITATION_INVALID"


@pytest.mark.parametrize("state", ["succeeded", "unknown"])
def test_success_or_unknown_cannot_be_silently_retried(synthetic, state):
    bundle = bound(deepcopy(synthetic))
    rows = [attempt(bundle, 1, state=state), attempt(bundle, 1, 2)]
    with pytest.raises(inputs.MaterialInputError, match="RETRIED"):
        aggregate(bundle, rows)


@pytest.mark.parametrize(
    "mutation",
    [
        "response_id",
        "call_id",
        "sequence",
        "bool_slot",
        "unknown_with_response",
        "body",
        "invalid_response_id",
    ],
)
def test_duplicate_or_misbound_attempts_reject(synthetic, mutation):
    bundle = bound(deepcopy(synthetic))
    rows = [attempt(bundle, s) for s in (1, 2, 3)]
    if mutation == "response_id":
        rows[1] = replace(rows[1], generation=rows[0].generation)
    elif mutation == "call_id":
        rows[1] = replace(rows[1], call_id=rows[0].call_id)
    elif mutation == "sequence":
        rows[0] = replace(rows[0], attempt=2)
    elif mutation == "bool_slot":
        rows[0] = replace(rows[0], slot=True)
    elif mutation == "unknown_with_response":
        rows[0] = replace(rows[0], state="unknown")
    elif mutation == "invalid_response_id":
        rows[0] = replace(
            rows[0], generation=replace(rows[0].generation, response_id=["synthetic-invalid-id"])
        )
    else:
        rows[0] = replace(rows[0], request=replace(rows[0].request, body=b"tampered"))
    with pytest.raises(inputs.MaterialInputError):
        aggregate(bundle, rows)


def test_unknown_slot_is_preserved_and_votes_remain_absent(synthetic):
    bundle = bound(deepcopy(synthetic))
    result = aggregate(bundle, [attempt(bundle, 1, state="unknown"), attempt(bundle, 2)])
    assert result["unresolved_slots"] == [1] and result["missing_valid_slots"] == [1, 3]
    assert result["features"] is None


def test_raw_generation_tamper_is_not_downgraded_to_retryable_semantic_failure(synthetic):
    bundle = bound(deepcopy(synthetic))
    row = attempt(bundle, 1)
    row.generation.data["reason"] = "tampered parsed response"
    with pytest.raises(inputs.MaterialInputError, match="RESPONSE_BINDING_MISMATCH"):
        aggregate(bundle, [row])
