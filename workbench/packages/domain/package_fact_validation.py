"""Explain fact provenance gaps; free-text subject/scope never grants package applicability."""

import json
import math

from packages.domain.fact_sets import identity
from packages.domain.runtime import sha

CODES = (
    "FACT_SET_EMPTY",
    "FACT_DECISION_UNCONFIRMED",
    "FACT_DECISION_BINDING_UNPROVEN",
    "FACT_DECISION_BASIS_UNPROVEN",
    "FACT_EVIDENCE_OUTSIDE_FROZEN_INPUT",
    "FACT_EVIDENCE_QUALITY_UNPROVEN",
    "FACT_SOURCE_BINDING_UNPROVEN",
    "FACT_SOURCE_NOT_EFFECTIVE",
    "FACT_SCOPE_MAPPING_REQUIRED",
)


def _reject_constant(value):
    raise ValueError("non_finite_json")


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate_basis_key")
        result[key] = value
    return result


def _float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non_finite_json")
    return result


def assess(item, proof):
    fact, decision = item["fact"], item["decision"]
    codes = []
    if not decision or decision["decision"] != "confirmed":
        codes.append("FACT_DECISION_UNCONFIRMED")
    if not proof["decision_binding"]:
        codes.append("FACT_DECISION_BINDING_UNPROVEN")
    basis = None
    try:
        basis = json.loads(
            item["decision_basis_jsonb_text"],
            object_pairs_hook=_pairs,
            parse_constant=_reject_constant,
            parse_float=_float,
        )
        value = json.loads(
            fact["value_jsonb_text"],
            object_pairs_hook=_pairs,
            parse_constant=_reject_constant,
            parse_float=_float,
        )
        expected_identity = identity({**fact, "value": value})
        if (
            set(basis) != {"fact_identity", "evidence"}
            or basis["fact_identity"] != expected_identity
        ):
            raise ValueError("fact_basis_identity")
        if set(basis["evidence"]) != {"references", "source_closure_digest"}:
            raise ValueError("fact_basis_shape")
    except (TypeError, ValueError, KeyError, OverflowError):
        codes.append("FACT_DECISION_BASIS_UNPROVEN")
        basis = None
    if item["scope_binding"] != "selected_frozen_parse":
        codes.append("FACT_EVIDENCE_OUTSIDE_FROZEN_INPUT")
    if not proof["evidence_usable"]:
        codes.append("FACT_EVIDENCE_QUALITY_UNPROVEN")
    if (
        basis is None
        or proof["closure"] is None
        or basis["evidence"]
        != {"references": proof["references"], "source_closure_digest": sha(proof["closure"])}
    ):
        codes.append("FACT_SOURCE_BINDING_UNPROVEN")
    if not proof["sources_effective"]:
        codes.append("FACT_SOURCE_NOT_EFFECTIVE")
    provenance = not codes
    codes.append("FACT_SCOPE_MAPPING_REQUIRED")
    return {
        "fact_id": fact["id"],
        "provenance_status": "verified" if provenance else "unproven",
        "scope_binding": "unproven",
        "facts_qualified": False,
        "blockers": codes,
    }
