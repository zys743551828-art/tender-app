"""Native private evidence, fresh exact sources and no replayed renderer trust."""
# ruff: noqa: F401,F811

import asyncio
import json
import os
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus
from test_native_material_store_pg import (
    api,
    database,
    exact,
    pdf_data,
    put,
    raw_put,
    ready,
    requirements,
    saved,
    world,
)
from test_package_current_original_set_pg import wire

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_material_scope_findings as findings
from packages.model_governance import package_native_material_recovery as recovery
from packages.model_governance import package_native_material_store as store
from packages.model_governance import package_technical_material as material
from packages.storage.private_cas import sha

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_NATIVE_MATERIAL_RECOVERY_PG") != "1",
    reason="explicit grouped native evidence recovery required",
)


def artifact(wire):
    w, _, _ = wire
    p = ready(wire)
    command = str(uuid4())
    record = put(w, p, command)
    return p, command, record


def restore(wire, saved_artifact, *, store_connection=None, **changes):
    w, state, url = wire
    p, command, record = saved_artifact
    m = p.live.context.metadata
    args = {
        "store_command_id": command,
        "expected_packet_digest": digest(p.packet),
        "expected_storage_record_digest": record.metadata["digest"],
        "expected_context_digest": m["digest"],
        "expected_method_digest": recovery.method_digest(),
        "bid_id": m["bid_id"],
        "scope_id": m["scope_id"],
        "expected_scope_digest": m["scope_digest"],
        "profile": "development_s3",
        "url_for_locator": url,
    } | changes
    return asyncio.run(
        recovery.restore(
            w["database"]["material_reader"] if store_connection is None else store_connection,
            *(w["database"][k] for k in ("scope_verifier", "original_verifier", "parse_verifier")),
            **args,
        )
    )


def test_native_evidence_recovery_preserves_exact_context_and_claim_boundaries(wire):
    w, state, url = wire
    saved_artifact = artifact(wire)
    p, command, record = saved_artifact
    before = canonical(p.live.context.metadata)

    def idle():
        assert all(
            w["database"][k].info.transaction_status == TransactionStatus.IDLE
            for k in ("material_reader", "scope_verifier", "original_verifier", "parse_verifier")
        )

    state["callback"] = idle
    result = restore(wire, saved_artifact)
    m = result.metadata
    assert (
        canonical(result.context.metadata) == before
        and result.context.origin.metadata == p.live.context.origin.metadata
    )
    assert canonical(result.findings.metadata) == canonical(p.findings.metadata)
    assert result.stored_record.metadata == record.metadata
    assert state["attempts"] == state["idle_checks"] == 4
    assert (
        m["exact_frozen_context_recovered"]
        and m["stored_scope_findings_revalidated"]
        and m["stored_derivation_claim_consistent"]
    )
    assert not any(
        m[k]
        for k in (
            "page_assets_rerendered",
            "trusted_derivation_freshly_verified",
            "actual_human_reading_verified",
            "necessary_scope_verified",
            "native_binding_verified",
            "input_authority_granted",
            "execution_authorized",
            "historical_existence_verified",
            "atomic_snapshot_verified",
            "send_lease_granted",
        )
    )
    assert m["digest"] == digest({k: v for k, v in m.items() if k != "digest"})
    directory = os.environ.get("FUSION_NATIVE_MATERIAL_RECOVERY_EVIDENCE")
    if directory:
        (Path(directory) / "native-material-recovery-proof.json").write_text(
            json.dumps(
                {
                    "recovery_method_digest": recovery.method_digest(),
                    "observation": m,
                    "actual_loopback_gets": 4,
                    "recovery_loopback_gets": 2,
                    "exact_context_source_observation_and_findings_preserved": True,
                    "four_independent_connections_idle_during_get": True,
                    "synthetic_material": True,
                    "stored_derivation_claims_synthetic": True,
                    "renderer_replayed": False,
                    "live_derivation_certificate_constructed": False,
                    "actual_human_review": False,
                    "input_authority_granted": False,
                    "provider_attempts": 0,
                    "body_exported": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


@pytest.mark.parametrize("mutation", ["closed", "withdrawn", "revision"])
def test_changed_sources_or_phase_reject_before_recovery_get(wire, mutation):
    w, state, url = wire
    a = artifact(wire)
    owner = w["database"]["owner"]
    if mutation == "closed":
        owner.execute(
            "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s",
            (w["technical_scope"][0],),
        )
    else:
        root = w["saved_scope"]["manifest"]["preview"]["manifest"]["source_snapshot"][0][
            "source_id"
        ]
        if mutation == "withdrawn":
            owner.execute(
                "UPDATE retrieval.source_heads SET status='withdrawn',revision=revision+1 WHERE source_id=%s",
                (root,),
            )
        else:
            owner.execute(
                "UPDATE retrieval.source_heads SET revision=revision+1 WHERE source_id=%s", (root,)
            )
    with pytest.raises(ValueError, match="SOURCE|CURRENT_PREBID|GRAPH_CHANGED"):
        restore(wire, a)
    assert state["attempts"] == 2


def test_close_during_last_original_get_rejects_whole_recovery(wire):
    w, state, url = wire
    a = artifact(wire)

    def closing():
        if state["attempts"] == 4:
            w["database"]["owner"].execute(
                "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s",
                (w["technical_scope"][0],),
            )

    state["callback"] = closing
    with pytest.raises(ValueError, match="CURRENT_PREBID"):
        restore(wire, a)


@pytest.mark.parametrize(
    "field", ["expected_packet_digest", "expected_storage_record_digest", "expected_context_digest"]
)
def test_native_record_packet_and_context_pins_are_exact(wire, field):
    a = artifact(wire)
    with pytest.raises(ValueError):
        restore(wire, a, **{field: "e" * 64})
    assert wire[1]["attempts"] == 2


def test_corrupt_fresh_original_cannot_be_replaced_by_stored_images(wire):
    a = artifact(wire)
    wire[1]["corrupt"] = True
    with pytest.raises(ValueError):
        restore(wire, a)


def test_store_writer_is_not_accepted_as_recovery_reader(wire):
    w, _, _ = wire
    a = artifact(wire)
    with pytest.raises(store.NativeMaterialStoreError):
        restore(wire, a, store_connection=w["database"]["material_writer"])


def raw_variant(wire, a, kind, mutate):
    w, _, _ = wire
    p, _, _ = a
    packet = deepcopy(p.packet)
    objects = dict(p.objects)
    old = packet[kind]["sha256"]
    body = json.loads(objects.pop(old))
    mutate(body)
    body["digest"] = digest({k: v for k, v in body.items() if k != "digest"})
    raw = canonical(body)
    key = sha(raw)
    objects[key] = raw
    packet[kind] = {"sha256": key, "byte_size": len(raw)}
    field = "findings_digest" if kind == "findings_object" else "derivation_observation_digest"
    packet[field] = body["digest"]
    keys = sorted(objects)
    command = str(uuid4())
    result = raw_put(w, p, command, packet=packet, keys=keys, values=[objects[k] for k in keys])
    record = store._record(result["put"])
    # This is deliberately an unqualified raw artifact: all bytes/digests are
    # native-valid, while report/derivation semantics still require recovery.
    from dataclasses import replace

    return replace(p, packet=packet, objects=objects), command, record


def test_native_storage_is_not_a_substitute_for_complete_report_revalidation(wire):
    a = artifact(wire)

    def missing_reading(body):
        body["draft"]["reviewed_image_ids"] = []

    bad = raw_variant(wire, a, "findings_object", missing_reading)
    with pytest.raises(findings.ScopeFindingsError):
        restore(wire, bad)


def test_native_storage_does_not_certify_a_rehashed_derivation_claim(wire):
    a = artifact(wire)

    def wrong_manifest(body):
        body["documents"][0]["receipt"]["result_manifest_digest"] = "e" * 64

    bad = raw_variant(wire, a, "derivation_object", wrong_manifest)
    with pytest.raises(ValueError, match="RECEIPT_MISMATCH"):
        restore(wire, bad)


def test_valid_incomplete_report_is_retained_without_input_authority(wire):
    w, _, _ = wire
    a = artifact(wire)
    p, _, _ = a
    draft = deepcopy(p.findings.metadata["draft"])
    draft["findings"][0]["outcome"] = "unable_to_verify"
    report = findings.validate(
        p.findings.review_packet,
        draft,
        expected_review_digest=p.packet["review_digest"],
        expected_method_digest=findings.method_digest(),
    )
    other = store.prepare(
        p.live,
        report,
        expected_context_digest=p.packet["context_digest"],
        expected_findings_digest=report.metadata["digest"],
        expected_derivation_digest=p.packet["derivation_observation_digest"],
        expected_producer_method_digest=p.producer_method_digest,
        expected_method_digest=store.method_digest(),
    )
    command = str(uuid4())
    record = put(w, other, command)
    result = restore(wire, (other, command, record))
    assert (
        result.metadata["all_findings_claimed_confirmed"] is False
        and result.metadata["input_authority_granted"] is False
    )
