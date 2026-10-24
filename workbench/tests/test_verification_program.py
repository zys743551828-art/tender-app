"""Strict execution envelopes do not grant any independent input qualification."""

from copy import deepcopy
from uuid import uuid4

import pytest

from packages.domain.review_identity import digest
from packages.model_governance import material_verification_program as port


def observation():
    capsule = {
        "version": "fusion-live-verified-material/1",
        "method_digest": "a" * 64,
        "context_digest": "a" * 64,
        "findings_digest": "a" * 64,
        "initial_current_review": {},
        "live_derivation": {},
        "final_current_review": {},
        "status": "synthetic_review_only",
        **{k: False for k in port.FALSE_FIELDS},
        **{
            k: True
            for k in (
                "actual_current_derivation_and_review_combined",
                "trusted_derivation_bound",
                "issuer_state_unchanged_across_all_stages",
                "exact_frozen_context_and_report_preserved",
            )
        },
    }
    capsule["digest"] = digest(capsule)
    value = {
        "version": "material-verification-execution/1",
        "command_id": str(uuid4()),
        **{k: "a" * 64 for k in port.OBS_ROOTS},
        "byte_profile": "development_s3",
        "verified_material": capsule,
    }
    value["digest"] = digest({k: v for k, v in value.items() if k != "digest"})
    return value


def test_execution_statement_keeps_all_input_authority_false():
    value = observation()
    assert port._observation(value) == value
    assert value["verified_material"]["input_authority_granted"] is False


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "zero",
        "digest",
        "profile_type",
        "bad_id",
        "grant",
        "kernel_false",
        "capsule_hash",
        "capsule_extra",
    ],
)
def test_rehashed_execution_cannot_bypass_shape_or_capability_boundary(change):
    value = deepcopy(observation())
    capsule = value["verified_material"]
    if change == "extra":
        value["official_score"] = 99
    elif change == "zero":
        value["policy_digest"] = "0" * 64
    elif change == "digest":
        value["program_method_digest"] = "b" * 64
    elif change == "profile_type":
        value["byte_profile"] = {}
    elif change == "bad_id":
        value["command_id"] = "bad"
    elif change == "grant":
        capsule["input_authority_granted"] = True
    elif change == "kernel_false":
        capsule["trusted_derivation_bound"] = False
    elif change == "capsule_extra":
        capsule["unexpected"] = True
    else:
        capsule["unexpected"] = True
    if change != "capsule_hash":
        capsule["digest"] = digest({k: v for k, v in capsule.items() if k != "digest"})
    if change != "digest":
        value["digest"] = digest({k: v for k, v in value.items() if k != "digest"})
    with pytest.raises(ValueError):
        port._observation(value)
