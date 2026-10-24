"""Joint native material read guards reject before any connection is used."""

import asyncio

import pytest

from packages.model_governance import package_native_current_review as joint


def args():
    return {
        "registration_command_id": "unused",
        "expected_registration_packet_digest": "a" * 64,
        "expected_registration_digest": "a" * 64,
        "issuer_command_id": "unused",
        "expected_issuer_reference_digest": "a" * 64,
        "expected_issuer_digest": "a" * 64,
        "expected_context_digest": "a" * 64,
        "expected_method_digest": joint.method_digest(),
        "bid_id": "unused",
        "scope_id": "unused",
        "expected_scope_digest": "a" * 64,
        "profile": "unused",
        "url_for_locator": None,
    }


def test_joint_method_drift_rejects_before_any_port():
    values = args() | {"expected_method_digest": "b" * 64}
    with pytest.raises(joint.NativeCurrentReviewError, match="METHOD_MISMATCH"):
        asyncio.run(joint.observe(*(object() for _ in range(6)), **values))


@pytest.mark.parametrize("field", ["expected_issuer_digest", "expected_registration_digest"])
def test_joint_record_pins_cannot_be_unknown_or_zero(field):
    values = args() | {field: "0" * 64}
    with pytest.raises(joint.NativeCurrentReviewError, match="NATIVE_DIGEST_REQUIRED"):
        asyncio.run(joint.observe(*(object() for _ in range(6)), **values))


def test_joint_aliasing_purpose_connections_rejects_before_any_port():
    connection = object()
    with pytest.raises(joint.NativeCurrentReviewError, match="INDEPENDENT_CONNECTIONS_REQUIRED"):
        asyncio.run(joint.observe(*(connection for _ in range(6)), **args()))
