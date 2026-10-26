"""Complete original serialization, native ownership boundaries, and recovery wiring."""

# ruff: noqa: F401,F811
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from psycopg.pq import TransactionStatus
from test_package_technical_material import bound, reseal, synthetic, uid
from test_preparation_leases import sample

from packages.domain.review_identity import canonical, digest
from packages.model_governance import material_preparation_leases as leases
from packages.model_governance import material_request_preflight as preflight
from packages.model_governance import package_technical_complete_vision as vision
from packages.model_governance import package_technical_material as material
from packages.storage.private_cas import sha


def idle_connection():
    return SimpleNamespace(info=SimpleNamespace(transaction_status=TransactionStatus.IDLE))


@pytest.fixture
def owned(synthetic, monkeypatch):
    bundle = bound(deepcopy(synthetic))
    record = sample()
    d = record["document"]
    d.update(
        context_digest=bundle.context.metadata["digest"],
        material_input_digest=bundle.metadata["digest"],
        preparation_method_digest=leases.method_digest(),
    )
    record["digest"] = digest(d)
    lease = leases._lease(record)
    projected = {
        "lease": record,
        "lease_id": d["lease_id"],
        "job_id": d["job_id"],
        "generation": 1,
        "fence": 1,
        "evidence_revision": 1,
        "context": deepcopy(bundle.context.metadata),
        "context_object_digest": sha(canonical(bundle.context.metadata)),
        "material_input": deepcopy(bundle.metadata),
    }
    state = {"inspect": 0, "context": 0, "assets": 0, "current": True}
    objects = {
        sha(raw): raw
        for b in bundle.context.origin.page_bundles.values()
        for raw in b.blobs.values()
    }
    connection = idle_connection()

    def inspect(c, **refs):
        assert c is connection and c.info.transaction_status == TransactionStatus.IDLE
        assert refs["lease_id"] == d["lease_id"]
        assert refs["expected_lease_digest"] == record["digest"]
        state["inspect"] += 1
        return leases.PreparationObservation(
            lease,
            {
                "current": {
                    "preparation_lease_current": state["current"],
                    "observed_at": "2026-10-24T12:00:01.000000Z",
                    "lease_until": d["lease_until"],
                }
            },
        )

    def owned_context(c, **refs):
        assert c is connection and c.info.transaction_status == TransactionStatus.IDLE
        state["context"] += 1
        result = deepcopy(projected)
        if state.get("change_after") and state["context"] > 1:
            result["evidence_revision"] += 1
        return leases.OwnedMaterialProjection(result)

    def owned_assets(c, *, expected_object_digests, **refs):
        assert c is connection and c.info.transaction_status == TransactionStatus.IDLE
        assert expected_object_digests == sorted(objects)
        state["assets"] += 1
        if state.get("revoke_after_assets"):
            state["current"] = False
        data = dict(objects)
        if state.get("replace_asset"):
            data[next(iter(data))] = b"wrong but same asserted object key"
        return leases.OwnedMaterialBatch(d["lease_id"], data)

    monkeypatch.setattr(leases, "inspect", inspect)
    monkeypatch.setattr(leases, "owned_context", owned_context)
    monkeypatch.setattr(leases, "owned_assets", owned_assets)
    args = {
        "lease_id": d["lease_id"],
        "expected_lease_digest": record["digest"],
        "expected_input_digest": bundle.metadata["digest"],
        "expected_preparation_method_digest": leases.method_digest(),
        "expected_serializer_digest": vision.serializer_digest(),
        "expected_method_digest": preflight.method_digest(),
    }
    return SimpleNamespace(
        bundle=bundle,
        record=record,
        lease=lease,
        projection=projected,
        state=state,
        objects=objects,
        connection=connection,
        args=args,
    )


def test_preflight_uses_complete_serializer_and_three_slots_reuse_same_bytes(owned):
    result = preflight.preflight(owned.connection, owned.bundle, **owned.args)
    m = result.metadata
    assert m["rule_count"] == 1 and m["required_valid_slots"] == 3
    assert m["job_id"] == owned.record["document"]["job_id"]
    assert m["context_digest"] == owned.bundle.context.metadata["digest"]
    assert m["asset_set_digest"] == digest(sorted(owned.objects))
    assert all(m[k] is False for k in preflight.FALSE_FIELDS)
    assert "Synthetic complete" not in repr(result)
    assert "base64" not in canonical(m).decode() and "body" not in m
    expected = vision.prepare_request(
        owned.bundle,
        uid(61),
        expected_input_digest=owned.args["expected_input_digest"],
        expected_serializer_digest=vision.serializer_digest(),
    )
    assert m["requests"] == [expected.receipt]
    actual = [
        preflight.prepare_rule_request(
            owned.connection,
            owned.bundle,
            result,
            uid(61),
            expected_preflight_digest=m["digest"],
            expected_method_digest=owned.args["expected_method_digest"],
        )
        for _ in range(3)
    ]
    assert all(r.body == expected.body and r.receipt == expected.receipt for r in actual)
    assert owned.state == {"inspect": 8, "context": 8, "assets": 4, "current": True}


@pytest.mark.parametrize(
    "field",
    ["expected_method_digest", "expected_serializer_digest", "expected_preparation_method_digest"],
)
def test_changed_method_rejects_before_any_database_read(owned, field):
    with pytest.raises(preflight.MaterialPreflightError, match="METHOD_MISMATCH"):
        preflight.preflight(owned.connection, owned.bundle, **(owned.args | {field: "f" * 64}))
    assert owned.state["inspect"] == owned.state["context"] == owned.state["assets"] == 0


def test_active_transaction_is_not_reused(owned):
    owned.connection.info.transaction_status = TransactionStatus.INTRANS
    with pytest.raises(preflight.MaterialPreflightError, match="IDLE_CONNECTION"):
        preflight.preflight(owned.connection, owned.bundle, **owned.args)
    assert owned.state["inspect"] == 0


def test_json_projection_cannot_substitute_for_material_input(owned):
    fake = leases.OwnedMaterialProjection(deepcopy(owned.projection))
    with pytest.raises(material.MaterialInputError, match="INPUT_MISMATCH"):
        preflight.preflight(owned.connection, fake, **owned.args)
    assert owned.state["assets"] == 0


def test_original_pdf_bytes_are_still_verified(owned):
    broken = deepcopy(owned.bundle)
    broken.context.origin.originals[uid(1)] += b"changed after seal"
    with pytest.raises(material.MaterialInputError, match="ORIGINAL_BYTES"):
        preflight.preflight(owned.connection, broken, **owned.args)
    assert owned.state["assets"] == 0


def test_same_input_hash_with_different_native_metadata_is_rejected(owned):
    owned.projection["material_input"]["binding_reference"]["verification_id"] = uid(999)
    with pytest.raises(preflight.MaterialPreflightError, match="OWNED_INPUT_MISMATCH"):
        preflight.preflight(owned.connection, owned.bundle, **owned.args)
    assert owned.state["assets"] == 0


def test_complete_asset_set_is_compared_by_bytes_not_only_declared_hash(owned):
    owned.state["replace_asset"] = True
    with pytest.raises(preflight.MaterialPreflightError, match="OWNED_ASSET_MISMATCH"):
        preflight.preflight(owned.connection, owned.bundle, **owned.args)


@pytest.mark.parametrize("change", ["expired_before", "revoke_after_assets", "change_after"])
def test_expiry_revocation_or_evidence_change_never_returns_partial_preflight(owned, change):
    if change == "expired_before":
        owned.state["current"] = False
    else:
        owned.state[change] = True
    with pytest.raises(
        preflight.MaterialPreflightError, match="LEASE_NOT_CURRENT|OWNED_INPUT_CHANGED"
    ):
        preflight.preflight(owned.connection, owned.bundle, **owned.args)
    if change == "expired_before":
        assert owned.state["context"] == 0


@pytest.mark.parametrize("rule_id", [uid(62), uid(999)])
def test_excluded_or_missing_rule_cannot_be_prepared_from_receipt(owned, rule_id):
    result = preflight.preflight(owned.connection, owned.bundle, **owned.args)
    with pytest.raises(preflight.MaterialPreflightError, match="RECEIPT_INPUT_MISMATCH"):
        preflight.prepare_rule_request(
            owned.connection,
            owned.bundle,
            result,
            rule_id,
            expected_preflight_digest=result.metadata["digest"],
            expected_method_digest=owned.args["expected_method_digest"],
        )


@pytest.mark.parametrize("field", sorted(preflight.FALSE_FIELDS))
def test_rehashed_receipt_cannot_grant_send_funds_or_scoring(owned, field):
    result = preflight.preflight(owned.connection, owned.bundle, **owned.args)
    m = result.metadata
    m[field] = True
    m["digest"] = digest({k: v for k, v in m.items() if k != "digest"})
    with pytest.raises(preflight.MaterialPreflightError, match="RECEIPT_INVALID"):
        preflight.prepare_rule_request(
            owned.connection,
            owned.bundle,
            result,
            uid(61),
            expected_preflight_digest=m["digest"],
            expected_method_digest=owned.args["expected_method_digest"],
        )


def test_earlier_receipt_cannot_revive_expired_lease(owned):
    result = preflight.preflight(owned.connection, owned.bundle, **owned.args)
    owned.state["current"] = False
    with pytest.raises(preflight.MaterialPreflightError, match="LEASE_NOT_CURRENT"):
        preflight.prepare_rule_request(
            owned.connection,
            owned.bundle,
            result,
            uid(61),
            expected_preflight_digest=result.metadata["digest"],
            expected_method_digest=owned.args["expected_method_digest"],
        )


def test_changed_request_receipt_cannot_replace_actual_complete_payload(owned):
    result = preflight.preflight(owned.connection, owned.bundle, **owned.args)
    m = result.metadata
    m["requests"][0]["request_digest"] = "f" * 64
    m["digest"] = digest({k: v for k, v in m.items() if k != "digest"})
    with pytest.raises(preflight.MaterialPreflightError, match="REQUEST_CHANGED"):
        preflight.prepare_rule_request(
            owned.connection,
            owned.bundle,
            result,
            uid(61),
            expected_preflight_digest=m["digest"],
            expected_method_digest=owned.args["expected_method_digest"],
        )


def test_all_included_rules_are_serialized_without_retaining_their_bodies(owned, monkeypatch):
    origin = deepcopy(owned.bundle.context.origin)
    rules = origin.material["scope"]["manifest"]["preview"]["manifest"]["rules"]
    rules[1]["selection"] = "include"
    rules[1]["part_ids"] = ["target"]
    changed = bound(reseal(origin))
    owned.bundle = changed
    owned.projection["context"] = deepcopy(changed.context.metadata)
    owned.projection["material_input"] = deepcopy(changed.metadata)
    owned.projection["lease"]["document"]["material_input_digest"] = changed.metadata["digest"]
    owned.projection["lease"]["document"]["context_digest"] = changed.context.metadata["digest"]
    owned.record["digest"] = digest(owned.record["document"])
    owned.lease.metadata.clear()
    owned.lease.metadata.update(deepcopy(owned.record))
    owned.projection["context_object_digest"] = sha(canonical(changed.context.metadata))
    owned.args["expected_lease_digest"] = owned.record["digest"]
    owned.args["expected_input_digest"] = changed.metadata["digest"]
    # The native fixture returns the exact same immutable lease on final read;
    # this test changes only its explicitly synthetic fixed input beforehand.
    called = []
    original = vision.prepare_request

    def preparing(bundle, rule_id, **kwargs):
        called.append(rule_id)
        return original(bundle, rule_id, **kwargs)

    monkeypatch.setattr(vision, "prepare_request", preparing)
    checked = preflight.preflight(owned.connection, changed, **owned.args)
    assert called == [uid(61), uid(62)]
    assert checked.metadata["rule_count"] == 2
    assert checked.metadata["required_valid_slots"] == 6
    assert all("body" not in row for row in checked.metadata["requests"])


def test_request_body_limit_is_not_relaxed_by_native_ownership(owned, monkeypatch):
    monkeypatch.setattr(vision, "MAX_BODY_BYTES", 1)
    owned.args["expected_serializer_digest"] = vision.serializer_digest()
    owned.args["expected_method_digest"] = preflight.method_digest()
    with pytest.raises(material.MaterialInputError, match="BODY_LIMIT"):
        preflight.preflight(owned.connection, owned.bundle, **owned.args)


@pytest.mark.parametrize(
    "mutation", ["unknown", "missing", "wrong_requests", "bool_count", "false_complete"]
)
def test_malformed_rehashed_preflight_receipt_is_rejected(owned, mutation):
    result = preflight.preflight(owned.connection, owned.bundle, **owned.args)
    m = result.metadata
    if mutation == "unknown":
        m["unexpected"] = "private data"
    elif mutation == "missing":
        m.pop("lease_id")
    elif mutation == "wrong_requests":
        m["requests"] = ["not a request receipt"]
    elif mutation == "bool_count":
        m["rule_count"] = True
    else:
        m["all_included_rules_serialized"] = False
    m["digest"] = digest({k: v for k, v in m.items() if k != "digest"})
    with pytest.raises(preflight.MaterialPreflightError, match="RECEIPT_INVALID"):
        preflight.prepare_rule_request(
            owned.connection,
            owned.bundle,
            result,
            uid(61),
            expected_preflight_digest=m["digest"],
            expected_method_digest=owned.args["expected_method_digest"],
        )


def test_native_recovery_entry_uses_independent_readers_and_exact_binding(owned, monkeypatch):
    connections = [idle_connection() for _ in range(4)]
    seen = []

    async def restore(*readers, **kwargs):
        assert readers == tuple(connections)
        assert all(
            c.info.transaction_status == TransactionStatus.IDLE
            for c in [owned.connection, *readers]
        )
        assert kwargs["expected_context_digest"] == owned.bundle.context.metadata["digest"]
        assert kwargs["bid_id"] == owned.bundle.context.metadata["bid_id"]
        seen.append(kwargs)
        return SimpleNamespace(context=deepcopy(owned.bundle.context))

    monkeypatch.setattr(preflight.recovery, "restore", restore)
    args = owned.args | {
        "store_command_id": uid(700),
        "expected_packet_digest": "b" * 64,
        "expected_storage_record_digest": "c" * 64,
        "profile": "development_s3",
        "url_for_locator": lambda _: "http://127.0.0.1/private-original",
    }
    bundle, checked = asyncio.run(
        preflight.restore_and_preflight(owned.connection, *connections, **args)
    )
    assert bundle.metadata == owned.bundle.metadata
    assert checked.metadata["input_digest"] == owned.bundle.metadata["digest"]
    assert len(seen) == 1 and owned.state["assets"] == 1
    with pytest.raises(preflight.MaterialPreflightError, match="INDEPENDENT_CONNECTIONS"):
        asyncio.run(
            preflight.restore_and_preflight(owned.connection, *([owned.connection] * 4), **args)
        )


def test_revocation_during_recovery_prevents_any_request_preparation(owned, monkeypatch):
    async def restore(*readers, **kwargs):
        owned.state["current"] = False
        return SimpleNamespace(context=deepcopy(owned.bundle.context))

    monkeypatch.setattr(preflight.recovery, "restore", restore)
    with pytest.raises(preflight.MaterialPreflightError, match="LEASE_NOT_CURRENT"):
        asyncio.run(
            preflight.restore_and_preflight(
                owned.connection,
                *[idle_connection() for _ in range(4)],
                **owned.args,
                store_command_id=uid(700),
                expected_packet_digest="b" * 64,
                expected_storage_record_digest="c" * 64,
                profile="development_s3",
                url_for_locator=lambda _: "http://127.0.0.1/private-original",
            )
        )
    assert owned.state["assets"] == 0
