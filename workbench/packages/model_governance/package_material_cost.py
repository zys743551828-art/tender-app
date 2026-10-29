"""Integer reservation quotes under an explicitly pinned policy, never invoices.

No tokenizer estimate is treated as a fit proof. No price discovery, budget
ledger mutation, provider request, automatic retry or execution authority.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import NoReturn
from uuid import UUID

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_technical_complete_vision as vision
from packages.model_governance import package_technical_material as material
from packages.storage.private_cas import is_digest, sha

SAFE_INTEGER = 9_007_199_254_740_991
MINOR_PER_UNIT = 1_000_000
MAX_ATTEMPTS_PER_SLOT = 5
POLICY_FIELDS = frozenset(
    {
        "version",
        "policy_id",
        "profile_digest",
        "model_alias",
        "currency",
        "minor_per_unit",
        "input_per_million_minor",
        "output_per_million_minor",
        "context_token_capacity",
        "provider_output_token_capacity",
        "source_observation_digest",
        "source_observed_at",
        "valid_from",
        "valid_until",
        "reservation_basis",
    }
)


class MaterialCostError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise MaterialCostError("MATERIAL_COST_" + code)


@dataclass(frozen=True, repr=False)
class CostPolicy:
    metadata: dict


@dataclass(frozen=True, repr=False)
class ReservationQuote:
    metadata: dict
    context: material.MaterialContext
    policy: CostPolicy


def method_digest():
    return digest(
        {
            "version": "package-material-cost-method/1",
            "source": sha(Path(__file__).read_bytes()),
            "context_method": material.context_method_digest(),
            "profile_digest": vision.profile_digest(),
            "serializer_digest": vision.serializer_digest(),
            "safe_integer": SAFE_INTEGER,
            "minor_per_unit": MINOR_PER_UNIT,
            "maximum_attempts_per_slot": MAX_ATTEMPTS_PER_SLOT,
            "reservation_is_not_invoice_cap": True,
            "authority_grants": False,
        }
    )


def _integer(value, *, minimum=0, maximum=SAFE_INTEGER):
    return type(value) is int and minimum <= value <= maximum


def _time(value):
    result = None
    try:
        if type(value) is str and len(value) <= 40:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                result = parsed
    except (ValueError, TypeError):
        pass
    if result is None:
        fail("TIME_INVALID")
    return result


def bind_policy(value, *, expected_policy_digest):
    p = deepcopy(value)
    if (
        type(p) is not dict
        or set(p) != POLICY_FIELDS
        or p["version"] != "package-material-cost-policy/1"
        or not is_digest(expected_policy_digest)
        or p["profile_digest"] != vision.profile_digest()
        or p["model_alias"] != vision.profile()["model_alias"]
        or type(p["currency"]) is not str
        or p["currency"] not in {"USD", "CNY"}
        or type(p["minor_per_unit"]) is not int
        or p["minor_per_unit"] != MINOR_PER_UNIT
        or not _integer(p["input_per_million_minor"])
        or not _integer(p["output_per_million_minor"])
        or not _integer(p["context_token_capacity"], minimum=1)
        or not _integer(
            p["provider_output_token_capacity"], minimum=vision.profile()["max_output_tokens"]
        )
        or p["provider_output_token_capacity"] > p["context_token_capacity"]
        or not is_digest(p["source_observation_digest"])
        or p["reservation_basis"] != "full_context_capacity_no_discount"
    ):
        fail("POLICY_INVALID")
    valid = False
    try:
        valid = type(p["policy_id"]) is str and str(UUID(p["policy_id"])) == p["policy_id"]
    except (ValueError, TypeError, AttributeError):
        pass
    if not valid:
        fail("POLICY_INVALID")
    observed, start, end = (
        _time(p[k]) for k in ("source_observed_at", "valid_from", "valid_until")
    )
    if not observed <= start < end or end - observed > timedelta(hours=24):
        fail("POLICY_WINDOW_INVALID")
    if digest(p) != expected_policy_digest:
        fail("POLICY_INVALID")
    return CostPolicy(p | {"digest": expected_policy_digest})


def _policy(policy, expected_policy_digest, as_of):
    if type(policy) is not CostPolicy or type(policy.metadata) is not dict:
        fail("POLICY_REQUIRED")
    checked = bind_policy(
        {k: v for k, v in policy.metadata.items() if k != "digest"},
        expected_policy_digest=expected_policy_digest,
    )
    if canonical(checked.metadata) != canonical(policy.metadata):
        fail("POLICY_INVALID")
    at = _time(as_of)
    if not _time(checked.metadata["valid_from"]) <= at < _time(checked.metadata["valid_until"]):
        fail("POLICY_NOT_EFFECTIVE")
    return checked


def ceiling_charge(input_tokens, output_tokens, input_per_million_minor, output_per_million_minor):
    if any(
        not _integer(value)
        for value in (
            input_tokens,
            output_tokens,
            input_per_million_minor,
            output_per_million_minor,
        )
    ):
        fail("AMOUNT_INVALID")
    numerator = input_tokens * input_per_million_minor + output_tokens * output_per_million_minor
    result = (numerator + 999_999) // 1_000_000
    if result > SAFE_INTEGER:
        fail("AMOUNT_OVERFLOW")
    return result


def quote(
    context,
    policy,
    *,
    expected_context_digest,
    expected_policy_digest,
    expected_method_digest,
    as_of,
    max_attempts_per_slot,
    budget_currency,
    budget_ceiling_minor,
):
    method = method_digest()
    if expected_method_digest != method:
        fail("METHOD_MISMATCH")
    p = _policy(policy, expected_policy_digest, as_of)
    ctx = material.verify_context(context, expected_context_digest)
    if (
        ctx.metadata["provider_profile_digest"] != vision.profile_digest()
        or ctx.metadata["judgment_method_digest"] != vision.judgment_method_digest()
    ):
        fail("PROFILE_MISMATCH")
    if not _integer(max_attempts_per_slot, minimum=1, maximum=MAX_ATTEMPTS_PER_SLOT):
        fail("ATTEMPT_LIMIT_INVALID")
    if not _integer(budget_ceiling_minor) or budget_currency != p.metadata["currency"]:
        fail("BUDGET_INVALID")
    rules = [r for r in ctx.metadata["rules"] if r["selection"] == "include"]
    if not rules:
        fail("NO_INCLUDED_RULES")
    if any(r["source_coverage"] != "complete" for r in rules):
        fail("RULE_SOURCE_INCOMPLETE")
    per_call = ceiling_charge(
        p.metadata["context_token_capacity"],
        vision.profile()["max_output_tokens"],
        p.metadata["input_per_million_minor"],
        p.metadata["output_per_million_minor"],
    )
    minimum_calls = len(rules) * 3
    maximum_calls = minimum_calls * max_attempts_per_slot
    required = per_call * maximum_calls
    if required > SAFE_INTEGER:
        fail("AMOUNT_OVERFLOW")
    metadata = {
        "version": "package-material-reservation-quote/1",
        "method_digest": method,
        "context_digest": expected_context_digest,
        "policy_digest": expected_policy_digest,
        "profile_digest": vision.profile_digest(),
        "serializer_digest": vision.serializer_digest(),
        "as_of": as_of,
        "currency": p.metadata["currency"],
        "minor_per_unit": MINOR_PER_UNIT,
        "rule_ids": [r["rule_id"] for r in rules],
        "required_valid_slots": minimum_calls,
        "max_attempts_per_slot": max_attempts_per_slot,
        "maximum_external_calls": maximum_calls,
        "reserved_input_tokens_per_call": p.metadata["context_token_capacity"],
        "reserved_output_tokens_per_call": vision.profile()["max_output_tokens"],
        "per_call_ceiling_minor": per_call,
        "required_reservation_minor": required,
        "budget_ceiling_minor": budget_ceiling_minor,
        "budget_sufficient_under_policy": budget_ceiling_minor >= required,
        "all_declared_included_rules_retained": True,
        "reservation_is_not_invoice_cap": True,
        "price_policy_native_verified": False,
        "model_context_fit_proven": False,
        "request_body_limit_verified": False,
        "fee_ledger_reserved": False,
        "automatic_retry": False,
        "native_binding_verified": False,
        "execution_authorized": False,
    }
    if method_digest() != method:
        fail("METHOD_CHANGED")
    return ReservationQuote(metadata | {"digest": digest(metadata)}, ctx, p)


def verify(value, *, expected_digest):
    if (
        type(value) is not ReservationQuote
        or type(value.metadata) is not dict
        or value.metadata.get("digest") != expected_digest
    ):
        fail("QUOTE_MISMATCH")
    m = deepcopy(value.metadata)
    rebuilt = quote(
        value.context,
        value.policy,
        expected_context_digest=m["context_digest"],
        expected_policy_digest=m["policy_digest"],
        expected_method_digest=m["method_digest"],
        as_of=m["as_of"],
        max_attempts_per_slot=m["max_attempts_per_slot"],
        budget_currency=m["currency"],
        budget_ceiling_minor=m["budget_ceiling_minor"],
    )
    if canonical(rebuilt.metadata) != canonical(m):
        fail("QUOTE_MISMATCH")
    return rebuilt


def require_budget(value, *, expected_digest, expected_policy_digest, as_of):
    checked = verify(value, expected_digest=expected_digest)
    _policy(checked.policy, expected_policy_digest, as_of)
    if _time(as_of) < _time(checked.metadata["as_of"]):
        fail("CLOCK_REGRESSION")
    if checked.metadata["budget_sufficient_under_policy"] is not True:
        fail("BUDGET_INSUFFICIENT")
    return checked
