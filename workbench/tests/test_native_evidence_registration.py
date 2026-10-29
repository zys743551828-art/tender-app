"""Closed v2 refs never become v1 file commits or input authority."""

from copy import deepcopy
from uuid import uuid4

import pytest

from packages.domain.review_identity import digest
from packages.model_governance import package_native_evidence_registration as registration


def fixture_packet():
    p = {
        "version": "package-native-material-registration-packet/2",
        "storage_record_id": str(uuid4()),
        **{k: "a" * 64 for k in registration.ROOTS},
    }
    m = {
        **{k: "a" * 64 for k in registration.OBS_ROOTS},
        **{k: True for k in registration.OBS_TRUE},
        **{k: False for k in registration.OBS_FALSE},
        "version": "package-native-material-evidence-recovery/1",
        "storage_record_id": p["storage_record_id"],
        "store_command_id": str(uuid4()),
        "observed_at": "2026-10-24T00:00:00Z",
        "all_findings_claimed_confirmed": False,
        "scope_changes_requested": False,
    }
    m["digest"] = digest({k: v for k, v in m.items() if k != "digest"})
    p["native_recovery_observation_digest"] = m["digest"]
    return p, m


def test_v2_packet_and_complete_observation_preserve_unconfirmed_claim():
    p, m = fixture_packet()
    registration._packet(p)
    assert registration._observation(m, p) == m
    assert not any("commit" in key for key in p)
    assert m["all_findings_claimed_confirmed"] is False


@pytest.mark.parametrize(
    "mutation", ["v1_version", "cas_field", "zero_digest", "storage_id", "unknown_field"]
)
def test_v2_rejects_legacy_or_malformed_refs(mutation):
    p, _ = fixture_packet()
    if mutation == "v1_version":
        p["version"] = "package-native-material-registration-packet/1"
    elif mutation == "cas_field":
        p["recovery_commit_digest"] = "b" * 64
    elif mutation == "zero_digest":
        p["storage_record_digest"] = "0" * 64
    elif mutation == "storage_id":
        p["storage_record_id"] = "not-a-uuid"
    else:
        p["input_authority_granted"] = True
    with pytest.raises(registration.NativeEvidenceRegistrationError):
        registration._packet(p)


@pytest.mark.parametrize(
    "mutation", ["extra", "grant", "claim_type", "naive_time", "missing_proof", "root_mismatch"]
)
def test_rehashed_observation_still_cannot_change_schema_or_qualification(mutation):
    p, m = fixture_packet()
    m = deepcopy(m)
    if mutation == "extra":
        m["private_locator"] = "not permitted"
    elif mutation == "grant":
        m["input_authority_granted"] = True
    elif mutation == "claim_type":
        m["all_findings_claimed_confirmed"] = 1
    elif mutation == "naive_time":
        m["observed_at"] = "2026-10-24T00:00:00"
    elif mutation == "missing_proof":
        m["current_native_parse_and_originals_rechecked"] = False
    else:
        m["context_digest"] = "b" * 64
    m["digest"] = digest({k: v for k, v in m.items() if k != "digest"})
    p["native_recovery_observation_digest"] = m["digest"]
    with pytest.raises(registration.NativeEvidenceRegistrationError):
        registration._observation(m, p)
