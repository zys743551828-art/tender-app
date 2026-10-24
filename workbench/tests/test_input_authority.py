"""Closed native record codec; serialized metadata never creates a live capability."""

from copy import deepcopy
from uuid import uuid4

import pytest

from packages.domain.review_identity import digest
from packages.model_governance import material_input_authority as authority


def fact():
    d = {k: str(uuid4()) for k in authority.UUID_FIELDS}
    d |= {k: "a" * 64 for k in authority.SHA_FIELDS}
    d |= {k: True for k in authority.TRUE_FIELDS}
    d |= {k: False for k in authority.ORIGIN_FIELDS | authority.FALSE_FIELDS}
    d |= {
        "version": "material-input-verification/1",
        "origin": "synthetic_mechanism",
        "policy_head_revision": 1,
        "recorded_by": "synthetic_verifier",
        "recorded_by_oid": 100,
        "recorded_at": "2026-10-24T10:00:00Z",
        "status": "mechanism_input_verified",
    }
    return {"document": d, "digest": digest(d)}


def test_binding_uses_actual_native_record_identity_and_digest():
    value = fact()
    record = authority._record(value)
    assert record.binding == {
        "version": "package-technical-verification-binding/3",
        "verification_id": value["document"]["verification_id"],
        "verification_receipt_digest": value["digest"],
        "context_digest": "a" * 64,
        "context_method_digest": "a" * 64,
    }
    value["document"]["recorded_by"] = "changed"
    assert record.metadata["document"]["recorded_by"] == "synthetic_verifier"


@pytest.mark.parametrize("key", sorted(authority.ORIGIN_FIELDS | authority.FALSE_FIELDS))
def test_synthetic_origin_cannot_promote_itself_even_with_rehashed_root(key):
    value = fact()
    value["document"][key] = True
    value["digest"] = digest(value["document"])
    with pytest.raises(authority.InputAuthorityError, match="NATIVE_RESULT_INVALID"):
        authority._record(value)


@pytest.mark.parametrize(
    "key,value",
    [
        ("recorded_by_oid", True),
        ("policy_head_revision", 0),
        ("context_digest", "0" * 64),
        ("origin", ["current_prebid"]),
        ("recorded_at", "2026-10-24T10:00:00"),
        ("extra", True),
    ],
)
def test_closed_record_rejects_invalid_types_identity_and_time(key, value):
    metadata = deepcopy(fact())
    metadata["document"][key] = value
    metadata["digest"] = digest(metadata["document"])
    with pytest.raises(ValueError):
        authority._record(metadata)


def test_method_is_portable_code_and_fixed_sql_fingerprint():
    assert len(authority.method_digest()) == 64
    assert authority.method_digest() == authority.method_digest()
