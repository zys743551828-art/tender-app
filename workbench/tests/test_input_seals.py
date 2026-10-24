"""Closed seal references cannot promote synthetic origin or substitute input."""

from uuid import uuid4

import pytest

from packages.domain.review_identity import digest
from packages.model_governance import material_input_seals as seals


def fact():
    d = {k: str(uuid4()) for k in seals.UUID_FIELDS}
    d |= {k: "a" * 64 for k in seals.SHA_FIELDS}
    d |= {k: True for k in seals.TRUE_FIELDS}
    d |= {k: False for k in seals.ORIGIN_FIELDS | seals.FALSE_FIELDS}
    d |= {
        "version": "material-input-seal/1",
        "profile_head_revision": 1,
        "authority_policy_revision": 1,
        "recorded_by": "synthetic_sealer",
        "recorded_by_oid": 100,
        "recorded_at": "2026-10-24T11:00:00Z",
        "origin": "synthetic_mechanism",
        "status": "mechanism_input_sealed",
    }
    d["material_input"] = seals._input_for(d)
    d["material_input_digest"] = d["material_input"]["digest"]
    return {"document": d, "digest": digest(d)}


def test_sealed_input_preserves_old_reference_metadata_without_authority_promotion():
    value = fact()
    result = seals._record(value)
    assert result.metadata == value
    assert result.metadata["document"]["material_input"]["input_authority_granted"] is False
    value["document"]["material_input"]["execution_authorized"] = True
    assert result.metadata["document"]["material_input"]["execution_authorized"] is False


@pytest.mark.parametrize("key", sorted(seals.ORIGIN_FIELDS | seals.FALSE_FIELDS))
def test_synthetic_origin_does_not_grant_formal_or_execution_flags(key):
    value = fact()
    value["document"][key] = True
    value["digest"] = digest(value["document"])
    with pytest.raises(seals.InputSealError, match="NATIVE_RESULT_INVALID"):
        seals._record(value)


@pytest.mark.parametrize(
    "change", ["other_verification", "other_context", "extra", "grant_old_input"]
)
def test_rehashed_inner_input_cannot_substitute_native_binding(change):
    value = fact()
    inner = value["document"]["material_input"]
    if change == "other_verification":
        inner["binding_reference"]["verification_id"] = str(uuid4())
    elif change == "other_context":
        inner["context_digest"] = "b" * 64
    elif change == "extra":
        inner["unapproved"] = True
    else:
        inner["native_binding_verified"] = True
    inner["binding_reference_digest"] = digest(inner["binding_reference"])
    inner["digest"] = digest({k: v for k, v in inner.items() if k != "digest"})
    value["document"]["material_input_digest"] = inner["digest"]
    value["digest"] = digest(value["document"])
    with pytest.raises(seals.InputSealError, match="NATIVE_RESULT_INVALID"):
        seals._record(value)
