"""Quote arithmetic and native record decoding do not create spend authority."""
# ruff: noqa: F401,F811

from uuid import uuid4

import pytest
from test_package_material_cost import policy_data, synthetic
from test_package_material_cost import quote as pure_quote

from packages.domain.review_identity import digest
from packages.model_governance import material_cost_quotes as quotes
from packages.model_governance import package_material_cost as cost
from packages.model_governance import package_technical_complete_vision as vision


def fact(synthetic):
    trial = pure_quote(synthetic, max_attempts_per_slot=5)
    d = {k: str(uuid4()) for k in quotes.UUID_FIELDS}
    d |= {k: "a" * 64 for k in quotes.SHA_FIELDS}
    d |= {k: True for k in quotes.TRUE_FIELDS}
    d |= {k: False for k in quotes.FALSE_FIELDS}
    d |= {
        "version": "material-cost-quote/1",
        "policy_id": trial.policy.metadata["policy_id"],
        "policy_head_revision": 1,
        "origin": "synthetic_mechanism",
        "price_policy": {k: v for k, v in trial.policy.metadata.items() if k != "digest"},
        "price_policy_digest": trial.policy.metadata["digest"],
        "quote": trial.metadata,
        "quote_digest": trial.metadata["digest"],
        "context_digest": trial.context.metadata["digest"],
        "cost_method_digest": cost.method_digest(),
        "provider_profile_digest": vision.profile_digest(),
        "serializer_digest": vision.serializer_digest(),
        "judgment_method_digest": vision.judgment_method_digest(),
        "recorded_by": "synthetic_quoter",
        "recorded_by_oid": 100,
        "recorded_at": trial.metadata["as_of"],
        "status": "quoted_sufficient",
    }
    return {"document": d, "digest": digest(d)}


def rehash(value):
    q = value["document"]["quote"]
    q["digest"] = digest({k: v for k, v in q.items() if k != "digest"})
    value["document"]["quote_digest"] = q["digest"]
    value["digest"] = digest(value["document"])


def test_native_quote_keeps_pure_quote_flags_and_amounts_without_spending(synthetic):
    value = fact(synthetic)
    result = quotes._record(value)
    assert result.metadata == value
    assert result.metadata["document"]["quote"]["per_call_ceiling_minor"] == 319488
    value["document"]["quote"]["fee_ledger_reserved"] = True
    assert result.metadata["document"]["quote"]["fee_ledger_reserved"] is False


def test_fractional_price_is_rejected_before_a_policy_can_be_frozen():
    value = policy_data() | {"output_per_million_minor": 1.2}
    with pytest.raises(cost.MaterialCostError, match="POLICY_INVALID"):
        cost.bind_policy(value, expected_policy_digest="a" * 64)


@pytest.mark.parametrize("key", sorted(quotes.FALSE_FIELDS))
def test_rehashed_record_cannot_claim_account_fit_reservation_or_send(synthetic, key):
    value = fact(synthetic)
    value["document"][key] = True
    rehash(value)
    with pytest.raises(quotes.CostQuoteError, match="NATIVE_RESULT_INVALID"):
        quotes._record(value)


@pytest.mark.parametrize(
    "key,value",
    [
        ("per_call_ceiling_minor", 0),
        ("required_reservation_minor", 0),
        ("maximum_external_calls", 3),
        ("required_valid_slots", 0),
        ("max_attempts_per_slot", True),
        ("budget_sufficient_under_policy", False),
        ("fee_ledger_reserved", True),
        ("extra", True),
    ],
)
def test_rehashed_inner_amount_or_slot_mutations_are_rejected(synthetic, key, value):
    metadata = fact(synthetic)
    metadata["document"]["quote"][key] = value
    rehash(metadata)
    with pytest.raises(quotes.CostQuoteError, match="NATIVE_RESULT_INVALID"):
        quotes._record(metadata)
