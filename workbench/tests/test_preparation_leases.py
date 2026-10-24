"""Preparation facts never self-grant execution or unlimited ownership."""

from uuid import uuid4

import pytest

from packages.domain.review_identity import digest
from packages.model_governance import material_preparation_leases as leases
from packages.storage.private_cas import sha


def sample():
    d = (
        {k: str(uuid4()) for k in leases.UUID_FIELDS}
        | {k: "a" * 64 for k in leases.SHA_FIELDS}
        | {k: True for k in leases.TRUE_FIELDS}
        | {k: False for k in leases.FALSE_FIELDS}
    )
    d.update(
        version="material-preparation-lease/1",
        profile_head_revision=1,
        generation=1,
        fence=1,
        lease_seconds=30,
        lease_until="2026-10-24T12:00:30.000000Z",
        origin="synthetic_mechanism",
        recorded_by="assigned_preparation_worker",
        recorded_by_oid=20001,
        recorded_at="2026-10-24T12:00:00.000000Z",
    )
    return {"document": d, "digest": digest(d)}


def test_closed_claim_records_original_lease_without_execution_grants():
    value = sample()
    record = leases._lease(value)
    assert record.metadata == value
    value["document"]["fence"] = 2
    assert record.metadata["document"]["fence"] == 1


@pytest.mark.parametrize("field", sorted(leases.FALSE_FIELDS))
def test_rehashing_a_claim_cannot_grant_spending_or_send(field):
    value = sample()
    d = value["document"]
    d[field] = True
    value["digest"] = digest(d)
    with pytest.raises(leases.PreparationError):
        leases._lease(value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("fence", True),
        ("fence", 0),
        ("generation", True),
        ("lease_seconds", 121),
        ("lease_seconds", True),
        ("lease_until", "2026-10-24T13:00:00.000000Z"),
        ("recorded_by_oid", True),
        ("unknown", "body"),
    ],
)
def test_unbounded_or_malformed_lease_is_rejected(field, value):
    record = sample()
    d = record["document"]
    d[field] = value
    record["digest"] = digest(d)
    with pytest.raises(leases.PreparationError):
        leases._lease(record)


def heartbeat_sample():
    d = {
        "version": "material-preparation-heartbeat/1",
        "heartbeat_id": str(uuid4()),
        "command_id": str(uuid4()),
        "lease_id": str(uuid4()),
        "lease_digest": "a" * 64,
        "job_id": str(uuid4()),
        "generation": 1,
        "fence": 1,
        "previous_lease_until": "2026-10-24T12:00:30.000000Z",
        "lease_until": "2026-10-24T12:00:45.000000Z",
        "recorded_at": "2026-10-24T12:00:15.000000Z",
        "recorded_by": "assigned_preparation_worker",
        "recorded_by_oid": 20001,
    } | {k: False for k in leases.BLOCKED_CURRENT}
    return {"document": d, "digest": digest(d)}


def test_heartbeat_preserves_prior_expiry_as_a_separate_fact():
    value = heartbeat_sample()
    assert leases._heartbeat(value).metadata == value


@pytest.mark.parametrize("mutation", ["send_grant", "shrink", "expired", "bool_fence"])
def test_heartbeat_cannot_shrink_or_forge_execution(mutation):
    value = heartbeat_sample()
    d = value["document"]
    if mutation == "send_grant":
        d["send_lease_granted"] = True
    elif mutation == "shrink":
        d["lease_until"] = "2026-10-24T12:00:20.000000Z"
    elif mutation == "expired":
        d["recorded_at"] = d["lease_until"]
    elif mutation == "bool_fence":
        d["fence"] = True
    value["digest"] = digest(d)
    with pytest.raises(leases.PreparationError):
        leases._heartbeat(value)


def test_complete_binary_batch_cannot_be_truncated_reordered_or_substituted():
    objects = {sha(raw): raw for raw in (b"first image bytes", b"second image bytes")}
    keys = sorted(objects)
    raws = [objects[key] for key in keys]
    identity = str(uuid4())
    assert leases._batch(raws, keys, identity).objects == objects
    for candidate in (raws[:-1], raws[::-1], [b"other bytes", raws[1]]):
        with pytest.raises(leases.PreparationError):
            leases._batch(candidate, keys, identity)
