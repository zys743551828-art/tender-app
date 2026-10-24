"""Frozen request identity survives current evidence renewal, without execution."""
# ruff: noqa: F401,F811

from uuid import uuid4

import pytest
from test_package_technical_material import context, synthetic

from packages.domain.review_identity import digest
from packages.model_governance import material_input_renewals as renewals
from packages.model_governance import package_technical_complete_vision as vision
from packages.model_governance import package_technical_material as material
from packages.storage.private_cas import sha


def fact():
    d = {k: str(uuid4()) for k in renewals.UUID_FIELDS}
    d |= {k: "a" * 64 for k in renewals.SHA_FIELDS}
    d["current_verification_digest"] = "b" * 64
    d |= {k: True for k in renewals.TRUE_FIELDS}
    d |= {k: False for k in renewals.FALSE_FIELDS}
    d |= {
        "version": "material-input-renewal/1",
        "profile_head_revision": 1,
        "origin": "synthetic_mechanism",
        "recorded_by": "synthetic_renewer",
        "recorded_by_oid": 100,
        "recorded_at": "2026-10-24T12:00:00Z",
        "status": "synthetic_current_evidence_registered",
        "budget_sufficient_under_policy": True,
    }
    return {"document": d, "digest": digest(d)}


def test_native_renewal_decodes_two_explicit_verifications_without_grant():
    value = fact()
    result = renewals._record(value)
    assert result.metadata == value
    value["document"]["input_authority_granted"] = True
    assert result.metadata["document"]["input_authority_granted"] is False


@pytest.mark.parametrize("key", sorted(renewals.FALSE_FIELDS))
def test_rehashed_record_cannot_grant_funds_or_execution(key):
    value = fact()
    value["document"][key] = True
    value["digest"] = digest(value["document"])
    with pytest.raises(renewals.InputRenewalError, match="NATIVE_RESULT_INVALID"):
        renewals._record(value)


@pytest.mark.parametrize(
    "mutation", ["same_id", "same_digest", "boolean_revision", "integer_budget", "extra"]
)
def test_closed_record_does_not_relabel_original_proof_as_new(mutation):
    value = fact()
    d = value["document"]
    if mutation == "same_id":
        d["current_verification_id"] = d["admission_verification_id"]
    elif mutation == "same_digest":
        d["current_verification_digest"] = d["admission_verification_digest"]
    elif mutation == "boolean_revision":
        d["profile_head_revision"] = True
    elif mutation == "integer_budget":
        d["budget_sufficient_under_policy"] = 1
    else:
        d["extra"] = True
    value["digest"] = digest(d)
    with pytest.raises(renewals.InputRenewalError, match="NATIVE_RESULT_INVALID"):
        renewals._record(value)


def test_naive_new_binding_changes_wire_but_original_binding_stays_exact(synthetic):
    ctx = context(synthetic)
    binding = {
        "version": "package-technical-verification-binding/3",
        "verification_id": str(uuid4()),
        "verification_receipt_digest": "a" * 64,
        "context_digest": ctx.metadata["digest"],
        "context_method_digest": ctx.metadata["context_method_digest"],
    }

    def wire(reference):
        bundle = material.bind_input(
            ctx,
            reference,
            expected_context_digest=ctx.metadata["digest"],
            expected_binding_digest=digest(reference),
            expected_method_digest=material.method_digest(),
        )
        rule = next(r["rule_id"] for r in ctx.metadata["rules"] if r["selection"] == "include")
        request = vision.prepare_request(
            bundle,
            rule,
            expected_input_digest=bundle.metadata["digest"],
            expected_serializer_digest=vision.serializer_digest(),
        )
        return (
            bundle.metadata["digest"],
            sha(request.body),
            request.receipt["semantic_input_digest"],
        )

    before = wire(binding)
    assert all(
        a != b
        for a, b in zip(
            before,
            wire(
                binding | {"verification_id": str(uuid4()), "verification_receipt_digest": "b" * 64}
            ),
            strict=True,
        )
    )
    assert wire(binding) == before
