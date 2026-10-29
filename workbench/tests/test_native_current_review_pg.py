"""Joint current material and independent native issuer checks without POSIX CAS."""
# ruff: noqa: F401,F811

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus
from test_native_evidence_issuers_pg import (
    SIGNER,
    api,
    attest,
    database,
    exact,
    pdf_data,
    reference,
    requirements,
    saved,
    setup,
    world,
)
from test_native_evidence_registration_pg import record as register
from test_native_material_recovery_pg import restore
from test_native_material_store_pg import put, ready
from test_package_current_original_set_pg import wire
from test_package_material_scope_findings import checked, draft_for
from test_scope_review_issuers_pg import assign

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_native_current_review as joint
from packages.model_governance import package_native_material_store as store

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_NATIVE_CURRENT_REVIEW_PG") != "1",
    reason="explicit grouped native current material and issuer verification required",
)
KEYS = (
    "native_registrar",
    "material_reader",
    "scope_verifier",
    "original_verifier",
    "parse_verifier",
    "native_issuer_reader",
)


def prepared(wire, **changes):
    data = setup(wire, **changes)
    command = str(uuid4())
    record = attest(wire[0], data, command)
    return data, command, record


def observe(wire, prepared, *, connections=None, **changes):
    w, _, url = wire
    data, command, record = prepared
    pending, r, _, _ = data
    d = pending.metadata["document"]
    args = {
        "registration_command_id": d["command_id"],
        "expected_registration_packet_digest": d["packet_digest"],
        "expected_registration_digest": pending.metadata["digest"],
        "issuer_command_id": command,
        "expected_issuer_reference_digest": digest(reference(data)),
        "expected_issuer_digest": record.metadata["digest"],
        "expected_context_digest": r.context.metadata["digest"],
        "expected_method_digest": joint.method_digest(),
        "bid_id": r.context.metadata["bid_id"],
        "scope_id": r.context.metadata["scope_id"],
        "expected_scope_digest": r.context.metadata["scope_digest"],
        "profile": "development_s3",
        "url_for_locator": url,
    } | changes
    connections = [w["database"][k] for k in KEYS] if connections is None else connections
    return asyncio.run(joint.observe(*connections, **args))


def test_joint_six_connections_current_sources_native_report_and_issuer_same_context(wire):
    w, state, _ = wire
    p = prepared(wire)
    old_context = canonical(p[0][1].context.metadata)
    old_registration = canonical(p[0][0].metadata)

    def idle():
        assert all(w["database"][k].info.transaction_status == TransactionStatus.IDLE for k in KEYS)

    state["callback"] = idle
    result = observe(wire, p)
    m = result.metadata
    assert state["attempts"] == state["idle_checks"] == 6
    assert canonical(result.context.metadata) == old_context
    assert canonical(p[0][0].metadata) == old_registration
    assert result.findings.metadata == p[0][1].findings.metadata
    assert m["status"] == "synthetic_review_only" and m["all_findings_claimed_confirmed"]
    assert m["current_native_sources_rechecked"] and m["configured_issuer_identity_verified"]
    assert m["issuer_before"]["record"] == m["issuer_after"]["record"]
    assert m["current_recovery"]["digest"] != p[0][1].metadata["digest"]
    assert m["digest"] == digest({k: v for k, v in m.items() if k != "digest"})
    for k in (
        "configured_current_review_confirmed",
        "trusted_derivation_bound",
        "actual_human_reading_verified",
        "necessary_scope_verified",
        "native_binding_verified",
        "input_authority_granted",
        "execution_authorized",
        "historical_existence_verified",
        "atomic_snapshot_verified",
        "send_lease_granted",
    ):
        assert m[k] is False
    directory = os.environ.get("FUSION_NATIVE_CURRENT_REVIEW_EVIDENCE")
    if directory:
        (Path(directory) / "native-current-review-proof.json").write_text(
            json.dumps(
                {
                    "joint_method_digest": joint.method_digest(),
                    "observation": m,
                    "actual_loopback_gets_total": 6,
                    "joint_recovery_loopback_gets": 2,
                    "independent_connections_idle_during_http": 6,
                    "exact_context_report_and_registration_preserved": True,
                    "current_issuer_checked_before_and_after_source_recovery": True,
                    "synthetic_material_issuer_and_derivation_claims": True,
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


def test_simulated_current_prebid_profile_remains_identity_claim_not_input_authority(wire):
    p = prepared(wire, profile_changes={"origin": "current_prebid"})
    result = observe(wire, p)
    assert result.metadata["status"] == "configured_review_confirmed"
    assert result.metadata["configured_current_review_confirmed"]
    assert result.metadata["actual_human_reading_verified"] is False
    assert result.metadata["input_authority_granted"] is False


@pytest.mark.parametrize("change", ["profile", "case", "reenable"])
def test_revocation_or_reactivation_during_get_rejects_even_if_final_active(wire, change):
    w, state, _ = wire
    p = prepared(wire)

    def mutate():
        if state["attempts"] != 6:
            return
        owner = w["database"]["owner"]
        if change == "case":
            owner.execute(
                "UPDATE scope_review_issuer.case_heads SET enabled=false,revision=revision+1 WHERE case_id=%s",
                (p[0][3],),
            )
        else:
            owner.execute(
                "UPDATE scope_review_issuer.profile_heads SET enabled=false,revision=revision+1 WHERE login_name=%s",
                (SIGNER,),
            )
            if change == "reenable":
                owner.execute(
                    "UPDATE scope_review_issuer.profile_heads SET enabled=true,revision=revision+1 WHERE login_name=%s",
                    (SIGNER,),
                )

    state["callback"] = mutate
    with pytest.raises(joint.NativeCurrentReviewError, match="UNAVAILABLE|STATE_CHANGED"):
        observe(wire, p)


def test_revoked_issuer_rejects_before_any_new_original_get(wire):
    w, state, _ = wire
    p = prepared(wire)
    w["database"]["owner"].execute(
        "UPDATE scope_review_issuer.profile_heads SET enabled=false,revision=revision+1 WHERE login_name=%s",
        (SIGNER,),
    )
    with pytest.raises(joint.NativeCurrentReviewError, match="UNAVAILABLE"):
        observe(wire, p)
    assert state["attempts"] == 4


@pytest.mark.parametrize("change", ["close", "withdraw", "revision"])
def test_changed_material_after_last_get_rejects_whole_joint_observation(wire, change):
    w, state, _ = wire
    p = prepared(wire)

    def mutate():
        if state["attempts"] != 6:
            return
        owner = w["database"]["owner"]
        if change == "close":
            owner.execute(
                "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s",
                (w["technical_scope"][0],),
            )
        else:
            source = w["saved_scope"]["manifest"]["preview"]["manifest"]["source_snapshot"][0][
                "source_id"
            ]
            if change == "withdraw":
                owner.execute(
                    "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
                    (source,),
                )
            else:
                owner.execute(
                    "UPDATE retrieval.source_heads SET revision=revision+1 WHERE source_id=%s",
                    (source,),
                )

    state["callback"] = mutate
    with pytest.raises(ValueError, match="SOURCE|CURRENT_PREBID|GRAPH_CHANGED"):
        observe(wire, p)


@pytest.mark.parametrize(
    "field",
    [
        "expected_registration_digest",
        "expected_registration_packet_digest",
        "expected_issuer_digest",
        "expected_issuer_reference_digest",
        "expected_context_digest",
        "expected_scope_digest",
    ],
)
def test_joint_independent_roots_are_exact_before_new_get(wire, field):
    p = prepared(wire)
    with pytest.raises(ValueError):
        observe(wire, p, **{field: "e" * 64})
    assert wire[1]["attempts"] == 4


def test_corrupt_current_original_cannot_be_hidden_by_old_issuer_fact(wire):
    p = prepared(wire)
    wire[1]["corrupt"] = True
    with pytest.raises(ValueError):
        observe(wire, p)


@pytest.mark.parametrize(
    "position,role", [(0, "issuer_reader"), (1, "material_writer"), (5, "native_issuer")]
)
def test_wrong_native_purposes_cannot_replace_own_readers(wire, position, role):
    w, _, _ = wire
    p = prepared(wire)
    connections = [w["database"][k] for k in KEYS]
    connections[position] = w["database"][role]
    with pytest.raises(ValueError):
        observe(wire, p, connections=connections)


def test_read_uses_owned_idle_transactions_and_does_not_rollback_callers_work(wire):
    w, state, _ = wire
    p = prepared(wire)
    c = w["database"]["native_issuer_reader"]
    with c.transaction():
        c.execute("SELECT 1")
        with pytest.raises(ValueError, match="IDLE"):
            observe(wire, p)
        assert c.info.transaction_status == TransactionStatus.INTRANS
    assert state["attempts"] == 4


@pytest.mark.parametrize(
    "outcome,status",
    [("unable_to_verify", "review_incomplete"), ("change_required", "scope_changes_requested")],
)
def test_stored_incomplete_report_cannot_be_promoted_by_current_issuer(wire, outcome, status):
    w, _, _ = wire
    original = ready(wire)
    plan = original.findings.review_packet
    draft = draft_for(plan)
    draft["findings"][0]["outcome"] = outcome
    report = checked(plan, draft)
    changed = store.prepare(
        original.live,
        report,
        expected_context_digest=original.live.context.metadata["digest"],
        expected_findings_digest=report.metadata["digest"],
        expected_derivation_digest=original.live.metadata["digest"],
        expected_producer_method_digest=original.producer_method_digest,
        expected_method_digest=store.method_digest(),
    )
    command = str(uuid4())
    stored = put(w, changed, command)
    r = restore(wire, (changed, command, stored))
    pending = register(w, r, str(uuid4()))
    profile_id, case_id = assign(
        w,
        pending,
        r.findings.metadata["review_digest"],
        profile_changes={
            "login_name": SIGNER,
            "store": store.method_digest(),
            "origin": "current_prebid",
        },
    )
    data = (pending, r, profile_id, case_id)
    issuer_command = str(uuid4())
    attested = attest(w, data, issuer_command)
    result = observe(wire, (data, issuer_command, attested))
    assert result.metadata["status"] == status
    assert result.metadata["all_findings_claimed_confirmed"] is False
    assert result.metadata["configured_current_review_confirmed"] is False
    assert result.metadata["input_authority_granted"] is False
