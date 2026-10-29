"""Registration codec rejects forged references; synthetic recovery is not native."""
# ruff: noqa: F811

from copy import deepcopy

import pytest
from test_package_material_recovery import MemoryStore
from test_package_technical_material import context, synthetic, uid  # noqa: F401

from packages.domain.review_identity import digest
from packages.model_governance import package_material_recovery as recovery
from packages.model_governance import package_material_registration as registration


def recovered(synthetic):
    ctx = context(synthetic)
    meta = {
        "version": "package-native-material-recovery-observation/1",
        "method_digest": recovery.method_digest(),
        "context_digest": ctx.metadata["digest"],
        "recovery_commit_digest": "a" * 64,
        "original_source_observation_digest": ctx.metadata["source_observation_digest"],
        "exact_frozen_context_recovered": True,
        "current_native_parse_and_originals_rechecked": True,
        "native_binding_verified": False,
        "necessary_scope_verified": False,
        "input_authority_granted": False,
        "execution_authorized": False,
        "historical_existence_verified": False,
    }
    return recovery.RecoveredContext(ctx, meta | {"digest": digest(meta)})


def packet(value):
    return registration.packet_for(
        value,
        expected_context_digest=value.context.metadata["digest"],
        expected_recovery_commit_digest="a" * 64,
    )


def native_value(synthetic):
    result = {
        "version": "package-native-material-registration/1",
        "registration_id": uid(91),
        "bid_id": uid(40),
        "scope_id": uid(41),
        "scope_digest": "b" * 64,
        "command_id": uid(92),
        "recorded_by": "synthetic_registration",
        "recorded_at": "2026-10-24T00:00:00.000000Z",
        "packet": packet(recovered(synthetic)),
        "status": "awaiting_independent_verification",
        "native_binding_verified": False,
        "necessary_scope_verified": False,
        "input_authority_granted": False,
        "execution_authorized": False,
    }
    return {"document": result, "digest": digest(result)}


def test_closed_packet_contains_only_references_no_positive_grant(synthetic):
    p = packet(recovered(synthetic))
    assert set(p) == registration.PACKET_FIELDS | {"version"}
    assert p["registration_method_digest"] == registration.method_digest()
    assert "input_authority_granted" not in p
    value = native_value(synthetic)
    checked = registration._validate_record(value, bid_id=uid(40), expected_digest=value["digest"])
    assert checked.metadata["native_record_identity_verified"] is True
    assert checked.metadata["document"]["native_binding_verified"] is False
    assert "synthetic_registration" not in repr(checked)


@pytest.mark.parametrize(
    "field",
    [
        "native_binding_verified",
        "necessary_scope_verified",
        "input_authority_granted",
        "execution_authorized",
        "historical_existence_verified",
    ],
)
def test_recovery_cannot_claim_positive_qualification(synthetic, field):
    value = recovered(synthetic)
    value.metadata[field] = True
    value.metadata["digest"] = digest({k: v for k, v in value.metadata.items() if k != "digest"})
    with pytest.raises(registration.MaterialRegistrationError, match="RECOVERY_REFERENCE_MISMATCH"):
        packet(value)


@pytest.mark.parametrize("mutation", ["version", "extra", "missing", "boolean", "zero_digest"])
def test_packet_contract(synthetic, mutation):
    p = packet(recovered(synthetic))
    if mutation == "version":
        p["version"] = None
    elif mutation == "extra":
        p["verified"] = True
    elif mutation == "missing":
        del p["recovery_commit_digest"]
    elif mutation == "boolean":
        p["context_digest"] = False
    else:
        p["context_digest"] = "0" * 64
    with pytest.raises(registration.MaterialRegistrationError, match="PACKET_INVALID"):
        registration._packet(p)


@pytest.mark.parametrize(
    "mutation", ["true", "zero", "status", "timestamp", "actor", "scope_hash", "command", "extra"]
)
def test_rehashed_native_record_still_requires_pending_contract(synthetic, mutation):
    value = deepcopy(native_value(synthetic))
    document = value["document"]
    if mutation == "true":
        document["input_authority_granted"] = True
    elif mutation == "zero":
        document["execution_authorized"] = 0
    elif mutation == "status":
        document["status"] = "verified"
    elif mutation == "timestamp":
        document["recorded_at"] = "2026-10-24"
    elif mutation == "actor":
        document["recorded_by"] = {}
    elif mutation == "scope_hash":
        document["scope_digest"] = "0" * 64
    elif mutation == "command":
        document["command_id"] = "not-an-id"
    else:
        document["qualification"] = True
    value["digest"] = digest(document)
    with pytest.raises(registration.MaterialRegistrationError):
        registration._validate_record(value, bid_id=uid(40))


def stage(synthetic):
    value = recovered(synthetic)
    store = MemoryStore()
    key = registration.stage_command(
        store,
        value,
        command_id=uid(95),
        expected_context_digest=value.context.metadata["digest"],
        expected_recovery_commit_digest="a" * 64,
        expected_method_digest=registration.method_digest(),
    )
    return store, key, value


def test_staged_command_is_exact_and_contains_only_frozen_references(synthetic):
    store, key, value = stage(synthetic)
    command = registration._command(store, key)
    assert command["command_id"] == uid(95) and command["packet"] == packet(value)
    assert command["bid_id"] == value.context.metadata["bid_id"]
    assert len(store.commits) == 1 and not store.objects
    raw = store.commits[key]
    value.context.metadata["rules"].clear()
    assert store.commits[key] == raw and b"Synthetic" not in raw


@pytest.mark.parametrize("mutation", ["extra", "scope", "packet_method", "command", "method"])
def test_rehashed_command_contract(synthetic, mutation):
    from packages.domain.review_identity import canonical

    store, key, value = stage(synthetic)
    command = registration._command(store, key)
    if mutation == "extra":
        command["verified"] = True
    elif mutation == "scope":
        command["scope_digest"] = False
    elif mutation == "packet_method":
        command["packet"]["registration_method_digest"] = "b" * 64
    elif mutation == "command":
        command["command_id"] = "not-an-id"
    else:
        command["method_digest"] = "b" * 64
    other = store.publish(canonical(command))
    with pytest.raises(registration.MaterialRegistrationError):
        registration._command(store, other)


def test_invalid_context_command_never_persists(synthetic):
    store = MemoryStore()
    value = recovered(synthetic)
    with pytest.raises(ValueError):
        registration.stage_command(
            store,
            value,
            command_id=uid(95),
            expected_context_digest="b" * 64,
            expected_recovery_commit_digest="a" * 64,
            expected_method_digest=registration.method_digest(),
        )
    assert not store.commits and not store.objects
