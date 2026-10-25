"""Existing native lease and recovery APIs feed the unchanged full serializer."""

# ruff: noqa: F401,F811
import asyncio
import os
from copy import deepcopy

import pytest
from psycopg.pq import TransactionStatus
from test_preparation_leases_pg import (
    api,
    claim,
    database,
    exact,
    pdf_data,
    ready,
    requirements,
    saved,
    wire,
    world,
)

from packages.domain.review_identity import digest
from packages.model_governance import material_preparation_leases as leases
from packages.model_governance import material_request_preflight as preflight
from packages.model_governance import package_technical_complete_vision as vision
from packages.model_governance import package_technical_material as material

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_MATERIAL_REQUEST_PREFLIGHT_PG") != "1",
    reason="explicit native material request preflight fixture required",
)


def setup(wire, monkeypatch):
    w, _, _ = wire
    data, job, claim_args = ready(wire, monkeypatch, lease_seconds=120)
    claimed = claim(w, claim_args)
    bundle = material.bind_input(
        data[1],
        data[0].binding,
        expected_context_digest=data[1].metadata["digest"],
        expected_binding_digest=digest(data[0].binding),
        expected_method_digest=material.method_digest(),
    )
    args = {
        "lease_id": claimed.metadata["document"]["lease_id"],
        "expected_lease_digest": claimed.metadata["digest"],
        "expected_input_digest": bundle.metadata["digest"],
        "expected_preparation_method_digest": leases.method_digest(),
        "expected_serializer_digest": vision.serializer_digest(),
        "expected_method_digest": preflight.method_digest(),
    }
    return data, job, claimed, bundle, args


def test_native_owned_preflight_and_exact_three_slot_request_bytes(wire, monkeypatch):
    w, state, _ = wire
    _, job, _, bundle, args = setup(wire, monkeypatch)
    c = w["database"]["preparation_worker"]
    attempts = state["attempts"]
    result = preflight.preflight(c, bundle, **args)
    m = result.metadata
    d = job.metadata["document"]
    assert [r["rule_id"] for r in m["requests"]] == d["rule_ids"]
    assert m["required_valid_slots"] == len(d["slots"])
    assert m["quote_digest"] == d["quote_digest"]
    for row in m["requests"]:
        expected = vision.prepare_request(
            bundle,
            row["rule_id"],
            expected_input_digest=args["expected_input_digest"],
            expected_serializer_digest=vision.serializer_digest(),
        )
        for _ in range(3):
            actual = preflight.prepare_rule_request(
                c,
                bundle,
                result,
                row["rule_id"],
                expected_preflight_digest=m["digest"],
                expected_method_digest=preflight.method_digest(),
            )
            assert actual.body == expected.body and actual.receipt == expected.receipt
    assert state["attempts"] == attempts
    assert c.info.transaction_status == TransactionStatus.IDLE
    assert all(m[k] is False for k in preflight.FALSE_FIELDS)


def test_native_recovery_restores_sealed_input_before_preflight(wire, monkeypatch):
    w, state, url = wire
    data, _, _, original, args = setup(wire, monkeypatch)
    sealed = data[2].metadata["document"]
    command = (
        w["database"]["owner"]
        .execute(
            "SELECT command_id FROM technical_material_store.records WHERE id=%s",
            (sealed["storage_record_id"],),
        )
        .fetchone()["command_id"]
    )
    keys = (
        "preparation_worker",
        "material_reader",
        "scope_verifier",
        "original_verifier",
        "parse_verifier",
    )
    connections = [w["database"][key] for key in keys]
    attempts = state["attempts"]

    def idle():
        assert all(c.info.transaction_status == TransactionStatus.IDLE for c in connections)

    state["callback"] = idle
    recovered, result = asyncio.run(
        preflight.restore_and_preflight(
            *connections,
            **args,
            store_command_id=str(command),
            expected_packet_digest=sealed["storage_packet_digest"],
            expected_storage_record_digest=sealed["storage_record_digest"],
            profile="development_s3",
            url_for_locator=url,
        )
    )
    assert recovered.metadata == original.metadata
    assert recovered.context.metadata == original.context.metadata
    assert result.metadata["input_digest"] == original.metadata["digest"]
    assert state["attempts"] == attempts + 2
    idle()


def test_native_source_change_during_serialization_rejects_batch(wire, monkeypatch):
    w, _, _ = wire
    _, _, _, bundle, args = setup(wire, monkeypatch)
    original = vision.prepare_request
    changed = False

    def revoke(bundle, rule_id, **kwargs):
        nonlocal changed
        result = original(bundle, rule_id, **kwargs)
        if not changed:
            changed = True
            w["database"]["owner"].execute(
                "UPDATE material_preparation.profile_heads SET enabled=false,revision=revision+1"
            )
        return result

    monkeypatch.setattr(vision, "prepare_request", revoke)
    with pytest.raises(
        leases.PreparationError, match="LEASE_NOT_CURRENT|CURRENT_STATE_UNAVAILABLE"
    ):
        preflight.preflight(w["database"]["preparation_worker"], bundle, **args)
    assert changed


def test_native_ownership_does_not_accept_changed_original_pdf(wire, monkeypatch):
    w, _, _ = wire
    _, _, _, bundle, args = setup(wire, monkeypatch)
    broken = deepcopy(bundle)
    key = next(iter(broken.context.origin.originals))
    broken.context.origin.originals[key] += b"changed after input seal"
    with pytest.raises(material.MaterialInputError, match="ORIGINAL_BYTES_MISMATCH"):
        preflight.preflight(w["database"]["preparation_worker"], broken, **args)
