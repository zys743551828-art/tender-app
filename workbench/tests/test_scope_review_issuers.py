"""Issuer command encoding and native record format, without issuer authentication."""
# ruff: noqa: F401,F811

from copy import deepcopy

import pytest
from test_package_material_recovery import MemoryStore
from test_package_material_scope_findings import build, checked, draft_for, review_origin, synthetic
from test_package_technical_material import uid

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_scope_findings_store as findings_store
from packages.model_governance import package_scope_review_issuers as issuers


def staged(review_origin):
    packet = build(review_origin)
    report = checked(packet, draft_for(packet))
    store = MemoryStore()
    sealed = findings_store.save(
        store,
        report,
        expected_findings_digest=report.metadata["digest"],
        expected_method_digest=findings_store.method_digest(),
    )
    key = issuers.stage_command(
        store,
        packet,
        case_id=uid(301),
        command_id=uid(302),
        findings_commit_digest=sealed,
        expected_findings_digest=report.metadata["digest"],
        expected_method_digest=issuers.method_digest(),
    )
    return store, key, issuers._command(store, key)


def record(command):
    document = {
        "version": "package-native-scope-review-attestation/1",
        "attestation_id": uid(303),
        "case_id": command["case_id"],
        "command_id": command["command_id"],
        "profile_id": uid(304),
        "subject_id": uid(305),
        "issuer_kind": "human",
        "issuer_origin": "synthetic_mechanism",
        "authority_policy_digest": "a" * 64,
        "profile_digest": "b" * 64,
        "case_digest": "c" * 64,
        "registration_id": uid(306),
        "registration_digest": "d" * 64,
        "bid_id": command["bid_id"],
        "scope_id": command["scope_id"],
        "recorded_by": "synthetic_issuer",
        "recorded_at": "2026-10-24T01:00:00.000000Z",
        "reference": command["reference"],
        "status": "issuer_attestation_recorded",
        "necessary_scope_verified": False,
        "native_binding_verified": False,
        "input_authority_granted": False,
        "execution_authorized": False,
    }
    return {"document": document, "digest": digest(document)}


def test_staged_issuer_command_binds_private_claims_without_self_reported_issuer(review_origin):
    store, key, command = staged(review_origin)
    assert set(command) == {
        "version",
        "method_digest",
        "case_id",
        "command_id",
        "bid_id",
        "scope_id",
        "reference",
    }
    assert set(command["reference"]) == issuers.REF_FIELDS | {"version"}
    assert len(store.commits) == 2 and len(store.objects) == 1
    assert issuers._record(record(command))["document"]["input_authority_granted"] is False
    assert b"synthetic_issuer" not in store.get_commit(key)


@pytest.mark.parametrize(
    "mutation",
    ["actor", "method", "case", "command", "profile_field", "reference_method", "reference_zero"],
)
def test_rehashed_command_cannot_select_identity_or_alter_protocol(review_origin, mutation):
    store, key, command = staged(review_origin)
    if mutation == "actor":
        command["issuer_id"] = uid(999)
    elif mutation == "method":
        command["method_digest"] = "a" * 64
    elif mutation == "case":
        command["case_id"] = "not-an-id"
    elif mutation == "command":
        command["command_id"] = False
    elif mutation == "profile_field":
        command["reference"]["issuer_origin"] = "current_prebid"
    elif mutation == "reference_method":
        command["reference"]["findings_method_digest"] = "a" * 64
    else:
        command["reference"]["findings_digest"] = "0" * 64
    changed = store.publish(canonical(command))
    with pytest.raises(issuers.ScopeIssuerError):
        issuers._command(store, changed)


@pytest.mark.parametrize(
    "mutation", ["qualification", "zero", "kind", "origin", "actor", "time", "profile", "unknown"]
)
def test_rehashed_native_record_cannot_fake_qualifications_or_shape(review_origin, mutation):
    store, key, command = staged(review_origin)
    value = deepcopy(record(command))
    d = value["document"]
    if mutation == "qualification":
        d["necessary_scope_verified"] = True
    elif mutation == "zero":
        d["execution_authorized"] = 0
    elif mutation == "kind":
        d["issuer_kind"] = "anybody"
    elif mutation == "origin":
        d["issuer_origin"] = "real=true"
    elif mutation == "actor":
        d["recorded_by"] = {}
    elif mutation == "time":
        d["recorded_at"] = "2026-10-24"
    elif mutation == "profile":
        d["profile_digest"] = "0" * 64
    else:
        d["verified"] = True
    value["digest"] = digest(d)
    with pytest.raises(issuers.ScopeIssuerError):
        issuers._record(value)
