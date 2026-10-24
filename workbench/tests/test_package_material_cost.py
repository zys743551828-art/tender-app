"""Integer budget preview; explicit synthetic policy is not supplier authority."""
# ruff: noqa: F811

from copy import deepcopy

import pytest
from test_package_technical_material import context, reseal, synthetic, uid  # noqa: F401

from packages.domain.review_identity import digest
from packages.model_governance import package_material_cost as cost
from packages.model_governance import package_technical_complete_vision as vision


def policy_data():
    return {
        "version": "package-material-cost-policy/1",
        "policy_id": uid(200),
        "profile_digest": vision.profile_digest(),
        "model_alias": vision.profile()["model_alias"],
        "currency": "USD",
        "minor_per_unit": 1_000_000,
        "input_per_million_minor": 300000,
        "output_per_million_minor": 1200000,
        "context_token_capacity": 1048576,
        "provider_output_token_capacity": 393216,
        "source_observation_digest": digest("explicit synthetic pricing source"),
        "source_observed_at": "2026-10-24T00:00:00Z",
        "valid_from": "2026-10-24T00:00:00Z",
        "valid_until": "2026-10-25T00:00:00Z",
        "reservation_basis": "full_context_capacity_no_discount",
    }


def policy(**changes):
    value = policy_data() | changes
    return cost.bind_policy(value, expected_policy_digest=digest(value))


def quote(origin, *, price=None, **changes):
    ctx = context(origin)
    p = policy() if price is None else price
    args = {
        "expected_context_digest": ctx.metadata["digest"],
        "expected_policy_digest": p.metadata["digest"],
        "expected_method_digest": cost.method_digest(),
        "as_of": "2026-10-24T01:00:00Z",
        "max_attempts_per_slot": 1,
        "budget_currency": "USD",
        "budget_ceiling_minor": 10_000_000,
    } | changes
    return cost.quote(ctx, p, **args)


def guard(value, **changes):
    args = {
        "expected_digest": value.metadata["digest"],
        "expected_policy_digest": value.metadata["policy_digest"],
        "as_of": value.metadata["as_of"],
    } | changes
    return cost.require_budget(value, **args)


@pytest.mark.parametrize(
    "values,expected",
    [
        ((0, 0, 0, 0), 0),
        ((1, 0, 1, 0), 1),
        ((999999, 1, 1, 1), 1),
        ((1048576, 4096, 300000, 1200000), 319488),
        ((1000000, 4096, 300000, 1200000), 304916),
    ],
)
def test_ceiling_arithmetic(values, expected):
    assert cost.ceiling_charge(*values) == expected


@pytest.mark.parametrize("index", range(4))
def test_boolean_is_not_money_or_token_count(index):
    values = [1, 1, 1, 1]
    values[index] = True
    with pytest.raises(cost.MaterialCostError, match="AMOUNT_INVALID"):
        cost.ceiling_charge(*values)


def test_quote_counts_three_slots_and_explicit_retry_capacity_without_sending(synthetic):
    q = quote(synthetic, max_attempts_per_slot=5)
    m = q.metadata
    assert (
        m["rule_ids"] == [uid(61)]
        and m["required_valid_slots"] == 3
        and m["maximum_external_calls"] == 15
    )
    assert m["per_call_ceiling_minor"] == 319488 and m["required_reservation_minor"] == 4_792_320
    assert (
        m["reserved_input_tokens_per_call"] == 1048576
        and m["reserved_output_tokens_per_call"] == 4096
    )
    assert m["reservation_is_not_invoice_cap"] is True
    for field in (
        "price_policy_native_verified",
        "model_context_fit_proven",
        "request_body_limit_verified",
        "fee_ledger_reserved",
        "automatic_retry",
        "native_binding_verified",
        "execution_authorized",
    ):
        assert m[field] is False
    assert guard(q).metadata == m
    assert "synthetic" not in repr(q)


def test_insufficient_preview_shows_full_required_amount_and_guard_refuses(synthetic):
    q = quote(synthetic, budget_ceiling_minor=958463)
    assert q.metadata["required_reservation_minor"] == 958464
    assert q.metadata["budget_sufficient_under_policy"] is False
    with pytest.raises(cost.MaterialCostError, match="BUDGET_INSUFFICIENT"):
        guard(q)
    exact = quote(synthetic, budget_ceiling_minor=958464)
    assert guard(exact).metadata["budget_sufficient_under_policy"] is True


def test_round_each_call_up_before_operation_sum(synthetic):
    p = policy(
        context_token_capacity=4096,
        provider_output_token_capacity=4096,
        input_per_million_minor=1,
        output_per_million_minor=1,
    )
    q = quote(synthetic, price=p)
    assert (
        q.metadata["per_call_ceiling_minor"] == 1 and q.metadata["required_reservation_minor"] == 3
    )


def test_all_included_rules_are_counted_without_caller_subset(synthetic):
    origin = deepcopy(synthetic)
    row = origin.material["scope"]["manifest"]["preview"]["manifest"]["rules"][1]
    row.update(selection="include", part_ids=["target"])
    q = quote(reseal(origin))
    assert (
        q.metadata["rule_ids"] == [uid(61), uid(62)]
        and q.metadata["required_reservation_minor"] == 1_916_928
    )


def test_no_rules_cannot_look_like_free_success(synthetic):
    origin = deepcopy(synthetic)
    for row in origin.material["scope"]["manifest"]["preview"]["manifest"]["rules"]:
        row.update(selection="exclude", part_ids=[])
    with pytest.raises(cost.MaterialCostError, match="NO_INCLUDED_RULES"):
        quote(reseal(origin))


@pytest.mark.parametrize(
    "mutation",
    [
        "extra",
        "missing",
        "currency",
        "currency_object",
        "scale",
        "input_bool",
        "output_negative",
        "input_float",
        "context_bool",
        "output_small",
        "output_huge",
        "profile",
        "model",
        "source",
        "policy_id",
        "equal_window",
        "long_window",
        "late_source",
        "naive_time",
        "numeric_time",
        "wrong_digest",
    ],
)
def test_invalid_or_unbound_policy_never_qualifies(mutation):
    p = policy_data()
    if mutation == "extra":
        p["verified"] = True
    elif mutation == "missing":
        del p["input_per_million_minor"]
    elif mutation == "currency":
        p["currency"] = "EUR"
    elif mutation == "currency_object":
        p["currency"] = {}
    elif mutation == "scale":
        p["minor_per_unit"] = True
    elif mutation == "input_bool":
        p["input_per_million_minor"] = True
    elif mutation == "output_negative":
        p["output_per_million_minor"] = -1
    elif mutation == "input_float":
        p["input_per_million_minor"] = 0.3
    elif mutation == "context_bool":
        p["context_token_capacity"] = False
    elif mutation == "output_small":
        p["provider_output_token_capacity"] = 4095
    elif mutation == "output_huge":
        p["provider_output_token_capacity"] = 1048577
    elif mutation == "profile":
        p["profile_digest"] = "b" * 64
    elif mutation == "model":
        p["model_alias"] = "other"
    elif mutation == "source":
        p["source_observation_digest"] = "0" * 64
    elif mutation == "policy_id":
        p["policy_id"] = "not-an-id"
    elif mutation == "equal_window":
        p["valid_until"] = p["valid_from"]
    elif mutation == "long_window":
        p["valid_until"] = "2026-10-25T00:00:01Z"
    elif mutation == "late_source":
        p["source_observed_at"] = "2026-10-24T01:00:00Z"
    elif mutation == "naive_time":
        p["valid_from"] = "2026-10-24T00:00:00"
    elif mutation == "numeric_time":
        p["valid_until"] = 123
    with pytest.raises(cost.MaterialCostError):
        cost.bind_policy(p, expected_policy_digest="a" * 64)


@pytest.mark.parametrize(
    "as_of", ["2026-10-23T23:59:59Z", "2026-10-25T00:00:00Z", "2026-10-24T01:00:00"]
)
def test_expiry_and_timezone_are_explicit(synthetic, as_of):
    with pytest.raises(cost.MaterialCostError):
        quote(synthetic, as_of=as_of)


@pytest.mark.parametrize("attempts", [False, 0, 6, 1.5])
def test_attempt_budget_is_closed(synthetic, attempts):
    with pytest.raises(cost.MaterialCostError, match="ATTEMPT_LIMIT_INVALID"):
        quote(synthetic, max_attempts_per_slot=attempts)


def test_currency_is_not_implicitly_converted(synthetic):
    with pytest.raises(cost.MaterialCostError, match="BUDGET_INVALID"):
        quote(synthetic, budget_currency="CNY")


@pytest.mark.parametrize("rate", [cost.SAFE_INTEGER, cost.SAFE_INTEGER // 2])
def test_per_call_and_total_overflow_refuse_instead_of_wrapping(synthetic, rate):
    p = policy(input_per_million_minor=rate, output_per_million_minor=0)
    with pytest.raises(cost.MaterialCostError, match="AMOUNT_OVERFLOW"):
        quote(synthetic, price=p, budget_ceiling_minor=cost.SAFE_INTEGER)


@pytest.mark.parametrize(
    "mutation",
    [
        "lower_total",
        "lower_call",
        "drop_rule",
        "budget_true",
        "ledger",
        "token_fit",
        "zero",
        "extra",
    ],
)
def test_rehashed_quote_cannot_forge_cost_or_authority(synthetic, mutation):
    q = quote(synthetic, budget_ceiling_minor=0)
    m = q.metadata
    if mutation == "lower_total":
        m["required_reservation_minor"] -= 1
    elif mutation == "lower_call":
        m["per_call_ceiling_minor"] = 0
    elif mutation == "drop_rule":
        m["rule_ids"].clear()
    elif mutation == "budget_true":
        m["budget_sufficient_under_policy"] = True
    elif mutation == "ledger":
        m["fee_ledger_reserved"] = True
    elif mutation == "token_fit":
        m["model_context_fit_proven"] = True
    elif mutation == "zero":
        m["execution_authorized"] = 0
    else:
        m["verified"] = True
    m["digest"] = digest({k: v for k, v in m.items() if k != "digest"})
    with pytest.raises(cost.MaterialCostError, match="QUOTE_MISMATCH"):
        cost.verify(q, expected_digest=m["digest"])


def test_owned_policy_snapshot_cannot_be_changed_via_caller(synthetic):
    data = policy_data()
    p = cost.bind_policy(data, expected_policy_digest=digest(data))
    q = quote(synthetic, price=p)
    frozen = deepcopy(q.metadata)
    data["input_per_million_minor"] = 0
    p.metadata["output_per_million_minor"] = 0
    assert cost.verify(q, expected_digest=frozen["digest"]).metadata == frozen


@pytest.mark.parametrize(
    "changes",
    [
        {"as_of": "2026-10-25T00:00:00Z"},
        {"as_of": "2026-10-24T00:59:59Z"},
        {"expected_policy_digest": "b" * 64},
    ],
)
def test_live_budget_guard_rechecks_fresh_policy_and_clock(synthetic, changes):
    q = quote(synthetic)
    # Historical math remains inspectable; it cannot pass admission at another policy/time.
    assert cost.verify(q, expected_digest=q.metadata["digest"]).metadata == q.metadata
    with pytest.raises(cost.MaterialCostError):
        guard(q, **changes)
